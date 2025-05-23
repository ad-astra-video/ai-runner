import os
import asyncio
import logging
import multiprocessing as mp
import queue
import sys
import time
from typing import Any
import torch

from pipelines import load_pipeline, Pipeline
from log import config_logging, config_logging_fields, log_timing
from trickle import InputFrame, AudioFrame, VideoFrame, OutputFrame, VideoOutput, AudioOutput


class PipelineProcess:
    @staticmethod
    def start(pipeline_name: str, params: dict):
        instance = PipelineProcess(pipeline_name)
        if params:
            instance.update_params(params)
        instance.process.start()
        instance.start_time = time.time()
        return instance

    def __init__(self, pipeline_name: str):
        self.pipeline_name = pipeline_name
        self.ctx = mp.get_context("spawn")

        self.input_queue = self.ctx.Queue(maxsize=5)
        self.output_queue = self.ctx.Queue()
        self.param_update_queue = self.ctx.Queue()
        self.error_queue = self.ctx.Queue()
        self.log_queue = self.ctx.Queue(maxsize=100)  # Keep last 100 log lines

        self.done = self.ctx.Event()
        self.process = self.ctx.Process(target=self.process_loop, args=())
        self.start_time = 0.0
        self.request_id = ""

    async def stop(self):
        self._stop_sync()

    def _stop_sync(self):
        self.done.set()

        if not self.process.is_alive():
            logging.info("Process already not alive")
            return

        logging.info("Terminating pipeline process")

        stopped = False
        try:
            self.process.join(timeout=10)
            stopped = True
        except Exception as e:
            logging.error(f"Process join error: {e}")
        if not stopped or self.process.is_alive():
            logging.error("Failed to terminate process, killing")
            self.process.kill()

        for q in [self.input_queue, self.output_queue, self.param_update_queue,
                  self.error_queue, self.log_queue]:
            q.cancel_join_thread()
            q.close()

    def is_done(self):
        return self.done.is_set()

    def update_params(self, params: dict):
        self.param_update_queue.put(params)

    def reset_stream(self, request_id: str, stream_id: str):
        clear_queue(self.input_queue)
        clear_queue(self.output_queue)
        clear_queue(self.param_update_queue)
        clear_queue(self.error_queue)
        clear_queue(self.log_queue)
        self.param_update_queue.put({"request_id": request_id, "stream_id": stream_id})

    # TODO: Once audio is implemented, combined send_input with input_loop
    # We don't need additional queueing as comfystream already maintains a queue
    def send_input(self, frame: InputFrame):
        self._queue_put_fifo(self.input_queue, frame)

    async def recv_output(self) -> OutputFrame | None:
        # we cannot do a long get with timeout as that would block the asyncio
        # event loop, so we loop with nowait and sleep async instead.
        # TODO: use asyncio.to_thread instead
        while not self.is_done():
            try:
                output = self.output_queue.get_nowait()
                return output
            except queue.Empty:
                await asyncio.sleep(0.005)
                continue
        return None

    def get_recent_logs(self, n=None) -> list[str]:
        """Get recent logs from the subprocess. If n is None, get all available logs."""
        logs = []
        while not self.log_queue.empty():
            try:
                logs.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        return logs[-n:] if n is not None else logs  # Only limit if n is specified

    def process_loop(self):
        self._setup_logging()
        pipeline = None

        # Ensure CUDA environment is available inside the subprocess.
        # Multiprocessing (spawn mode) does not inherit environment variables by default,
        # causing `torch.cuda.current_device()` checks in ComfyUI's model_management.py to fail.
        # Explicitly setting `CUDA_VISIBLE_DEVICES` ensures the spawned process recognizes the GPU.
        if torch.cuda.is_available():
            os.environ["CUDA_VISIBLE_DEVICES"] = str(torch.cuda.current_device())

        # ComfystreamClient/embeddedComfyClient is not respecting config parameters
        # such as verbose='WARNING', logging_level='WARNING'
        # Setting here to override and supress excessive INFO logging
        # ( load_gpu_models is calling logging.info() for every frame )
        logging.getLogger("comfy").setLevel(logging.WARNING)

        try:
            asyncio.run(self._run_pipeline_loops())
        except Exception as e:
            self._report_error(f"Error in process run method: {e}")


    def _handle_logging_params(self, params: dict) -> dict:
        if isinstance(params, dict) and "request_id" in params and "stream_id" in params:
            logging.info(f"PipelineProcess: Resetting logging fields with request_id={params['request_id']}, stream_id={params['stream_id']}")
            self.request_id = params["request_id"]
            self._reset_logging_fields(
                params["request_id"], params["stream_id"]
            )
            return {}
        return params

    async def _initialize_pipeline(self):
        try:
            stream_id = ""
            params = {}
            try:
                params = self.param_update_queue.get_nowait()
                logging.info(f"PipelineProcess: Got params from param_update_queue {params}")
                params = self._handle_logging_params(params)
            except queue.Empty:
                logging.info("PipelineProcess: No params found in param_update_queue, loading with default params")

            with log_timing(f"PipelineProcess: Pipeline loading with {params}"):
                pipeline = load_pipeline(self.pipeline_name)
                await pipeline.initialize(**params)
                return pipeline
        except Exception as e:
            self._report_error(f"Error loading pipeline: {e}")
            if params:
                try:
                    with log_timing(f"PipelineProcess: Pipeline loading with default params due to error with params: {params}"):
                        pipeline = load_pipeline(self.pipeline_name)
                        await pipeline.initialize()
                        return pipeline
                except Exception as e:
                    self._report_error(f"Error loading pipeline with default params: {e}")
                    raise

    async def _run_pipeline_loops(self):
        pipeline = await self._initialize_pipeline()
        input_task = asyncio.create_task(self._input_loop(pipeline))
        output_task = asyncio.create_task(self._output_loop(pipeline))
        param_task = asyncio.create_task(self._param_update_loop(pipeline))

        async def wait_for_stop():
            while not self.is_done():
                await asyncio.sleep(0.1)

        tasks = [input_task, output_task, param_task, asyncio.create_task(wait_for_stop())]

        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except Exception as e:
            self._report_error(f"Error in pipeline loops: {e}")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._cleanup_pipeline(pipeline)

    async def _input_loop(self, pipeline: Pipeline):
        while not self.is_done():
            try:
                input_frame = await asyncio.to_thread(self.input_queue.get)
                if isinstance(input_frame, VideoFrame):
                    input_frame.log_timestamps["pre_process_frame"] = time.time()
                    await pipeline.put_video_frame(input_frame, self.request_id)
                elif isinstance(input_frame, AudioFrame):
                    await asyncio.to_thread(self.output_queue.put, AudioOutput([input_frame], self.request_id))
            except queue.Empty:
                continue
            except Exception as e:
                self._report_error(f"Error processing input frame: {e}")

    async def _output_loop(self, pipeline: Pipeline):
        while not self.is_done():
            try:
                output_frame = await pipeline.get_processed_video_frame()
                output_frame.log_timestamps["post_process_frame"] = time.time()
                await asyncio.to_thread(self.output_queue.put, output_frame)
            except Exception as e:
                self._report_error(f"Error processing output frame: {e}")

    async def _param_update_loop(self, pipeline: Pipeline):
        while not self.is_done():
            try:
                params = await asyncio.to_thread(self.param_update_queue.get)
                if self._handle_logging_params(params):
                    logging.info(f"PipelineProcess: Updating pipeline parameters: {params}")
                    await pipeline.update_params(**params)
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                self._report_error(f"Error updating params: {e}")

    def _report_error(self, error_msg: str):
        error_event = {
            "message": error_msg,
            "timestamp": time.time()
        }
        logging.error(error_msg)
        self._queue_put_fifo(self.error_queue, error_event)

    async def _cleanup_pipeline(self, pipeline):
        if pipeline is not None:
            try:
                await pipeline.stop()
            except Exception as e:
                logging.error(f"Error stopping pipeline: {e}")

    def _setup_logging(self):
        level = (
            logging.DEBUG if os.environ.get("VERBOSE_LOGGING") == "1" else logging.INFO
        )
        logger = config_logging(log_level=level)
        queue_handler = LogQueueHandler(self)
        config_logging_fields(queue_handler, "", "")
        logger.addHandler(queue_handler)

        self.queue_handler = queue_handler

        # Tee stdout and stderr to our log queue while preserving original output
        sys.stdout = QueueTeeStream(sys.stdout, self)
        sys.stderr = QueueTeeStream(sys.stderr, self)

    def _reset_logging_fields(self, request_id: str, stream_id: str):
        config_logging(request_id=request_id, stream_id=stream_id)
        config_logging_fields(self.queue_handler, request_id, stream_id)

    def _queue_put_fifo(self, _queue: mp.Queue, item: Any):
        """Helper to put an item on a queue, dropping oldest items if needed"""
        while not self.is_done():
            try:
                _queue.put_nowait(item)
                break
            except queue.Full:
                try:
                    _queue.get_nowait()  # remove oldest item
                except queue.Empty:
                    continue

    def get_last_error(self) -> tuple[str, float] | None:
        """Get the most recent error and its timestamp from the error queue, if any"""
        last_error = None
        while True:
            try:
                last_error = self.error_queue.get_nowait()
            except queue.Empty:
                break
        return (last_error["message"], last_error["timestamp"]) if last_error else None

class QueueTeeStream:
    """Tee all stream (stdout or stderr) messages to the process log queue"""
    def __init__(self, original_stream, process: PipelineProcess):
        self.original_stream = original_stream
        self.process = process

    def write(self, text):
        self.original_stream.write(text)
        text = text.strip()  # Only queue non-empty lines
        if text:
            self.process._queue_put_fifo(self.process.log_queue, text)

    def flush(self):
        self.original_stream.flush()

class LogQueueHandler(logging.Handler):
    """Send all log records to the process's log queue"""
    def __init__(self, process: PipelineProcess):
        super().__init__()
        self.process = process

    def emit(self, record):
        msg = self.format(record)
        self.process._queue_put_fifo(self.process.log_queue, msg)

# Function to clear the queue
def clear_queue(queue):
    while not queue.empty():
        try:
            queue.get_nowait()  # Remove items without blocking
        except Exception as e:
            logging.error(f"Error while clearing queue: {e}")
