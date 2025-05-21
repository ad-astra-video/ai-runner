import asyncio
import os
import json
from typing import Dict
import logging

from app.pipelines.base import Pipeline
from app.pipelines.utils import (
    SafetyChecker,
)
from app.pipelines.backends.comfyui import ComfyUIBackend

logger = logging.getLogger(__name__)


class BatchPipeline(Pipeline):
    def __init__(self, **kwargs):
        safety_checker_device = os.getenv("SAFETY_CHECKER_DEVICE", "cpu").lower()
        self._safety_checker = SafetyChecker(device=safety_checker_device)
        self.in_process = asyncio.Lock()

        BACKEND_TYPE = os.getenv("BACKEND_TYPE", "")
        self.backend = None
        if BACKEND_TYPE == "comfyui":
            self.backend = ComfyUIBackend()
    

    async def __call__(self, pipeline_name, model_id, params: Dict[str, any], files: Dict[str, any], **kwargs):
        #check if job in process, small wait to allow for other jobs to finish
        if self.in_process.locked():
            for i in range(4):
                if self.in_process.locked():
                    asyncio.sleep(0.15)
            return None
        
        self.in_process.acquire()
        result = await self.backend.process(pipeline_name, model_id, params, files, **kwargs)
        self.in_process.release()
        
        if "safety_check" in kwargs:
            if "images" in result:
                images, nsfws = self._safety_checker.check_nsfw_images(result["images"])
                for i, _ in enumerate(images):
                    result["imags"][i]["nsfw"] = nsfws[i]
        
        if result is None:
            raise ValueError("No result returned from backend.")
        
        return result

    async def get_pipelines(self):
        """
        Get the list of pipelines.
        """
        logger.info("Getting pipelines advertising info...")
        pipelines = []
        pipelines_path = "/app/settings/pipelines"
        for filename in os.listdir(pipelines_path):
            if filename.endswith('.json') and filename.startswith("comfyui--"):
                backend, pipeline = filename.split("--", 1)
                pipeline = pipeline.replace(".json", "")
                pipeline_name, model_id = pipeline.split("--", 1)
                model_id = model_id.replace("--", "/")
                pipeline_json = {
                    "pipeline": pipeline_name,
                    "model_id": model_id
                }
                with open(os.path.join(pipelines_path, filename), 'r') as f:
                    try:
                        pipeline_settings = json.load(f)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to get pipeline settings, JSON is invalid {filename}: {e}")
                        
                    if "pricing" in pipeline_settings:
                        if "price_per_unit" in pipeline_settings["pricing"]:
                            pipeline_json["price_per_unit"] = pipeline_settings["pricing"]["price_per_unit"]
                        if "currency" in pipeline_settings["pricing"]:
                            pipeline_json["currency"] = pipeline_settings["pricing"]["currency"]
                        if "price_scaling" in pipeline_settings["pricing"]:
                            pipeline_json["price_scaling"] = pipeline_settings["pricing"]["price_scaling"]
                        else:
                            pipeline_json["price_scaling"] = 1
                        
                    pipelines.append(pipeline_json)
        
        return pipelines
            
    async def refresh_pipelines(self):
        """
        Refresh the list of pipelines.
        """
        if self.backend:
            asyncio.to_thread(self.backend.setup_pipelines)
        else:
            raise ValueError("No backend available for refreshing pipelines.")
    
    async def stop_pipelines(self):
        """
        Stop the pipeline.
        """
        if self.backend:
            return await self.backend.stop_pipelines
        else:
            raise ValueError("No backend available for stopping pipelines.")