import json
import os
import shutil
import subprocess
import logging
import time
from git import Repo
from app.pipelines.utils import resumable_download
from app.pipelines.base import Backend
import re
from typing import Dict
import os
import httpx
import asyncio
from app.routes.utils import image_to_data_url, audio_to_data_url
from app.pipelines.backends.utils import run_command, start_backend, create_pipeline_runner_config
import io
import sys

from PIL import Image

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.FATAL)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")

class ComfyUIBackend(Backend):
    def __init__(self):
        print("SYS.PATH:  ", sys.path)
        self.setup_pipelines()

    def _create_pipeline_env(self, pipeline):
        logger.info(f"Creating virtualenv for {pipeline}")
        run_command(f"pyenv virtualenv --system-site-packages {pipeline}")
        logger.info(f"Created virtualenv {pipeline}")
        logger.info(f"Installing pytorch and dependencies for {pipeline}")
        run_command(f"pyenv activate {pipeline} && pip install torch==2.7 torchvision torchaudio transformers diffusers numpy>=1.26.4 accelerate tqdm")
        logger.info(f"Installed torch and dependencies for {pipeline}")
        logger.info(f"Installing comfyui dependencies for {pipeline}")
        run_command(f"pyenv activate {pipeline} && pip install -r /app/workspace/requirements.txt")
        logger.info(f"Installed comfyui dependencies for {pipeline}")
        logger.info(f"Installing comfyui manager dependencies for {pipeline}")
        run_command(f"pyenv activate {pipeline} && pip install -r /app/workspace/custom_nodes/ComfyUI-Manager/requirements.txt")
        logger.info(f"Installed comfyui manager dependencies for {pipeline}")
    
    def _install_node(self, node, pipeline):
        if 'url' in node:
            custom_nodes_path = "/app/workspace/custom_nodes"
            node_url = node['url']
            node_name = node['name']
            node_path = os.path.join(custom_nodes_path, node_name)
            if not os.path.exists(node_path):
                logger.info(f"Installing node {node_name} from {node_url} to {node_path}")
                repo = Repo.clone_from(node_url, node_path)
                if "branch" in node:
                    repo.git.checkout(node["branch"])
                if os.path.exists(node_path+"/requirements.txt"):
                    output = run_command(f"pyenv activate {pipeline} && pip install -r {node_path}/requirements.txt")
                    logger.debug(output)
                logger.info(f"Node {node_name} installed at {node_path}")
            else:
                if "auto_update" in node and node["auto_update"]:
                    logger.info(f"Updating node {node_name} from {node_url} to {node_path}")
                    repo = Repo(node_path)
                    repo.git.reset('--hard')
                    for remote in repo.remotes:
                        remote.fetch()
                    if "branch" in node:
                        repo.git.checkout(node["branch"])
                    else:
                        repo.git.checkout("main")

                    if os.path.exists(node_path+"/requirements.txt"):
                        output = run_command(f"pyenv activate {pipeline} && pip install -r {node_path}/requirements.txt")
                        logger.debug(output)
                    logger.info(f"Node {node_name} updated at {node_path}")
                else:
                    logger.info(f"Node {node_name} already installed at {node_path} (auto_update not enabled)")
        if 'addl_requirements' in node:
            if node["addl_requirements"] != "":
                requirements_list = node['addl_requirements'].split(",")
                for req in requirements_list:
                    logger.info(f"Installing additional requirements {req} for node {node_name}")
                    run_command(f"pyenv activate {pipeline} && pip install {req}")
            
    def _download_model(self, model_url, model_path):
        file_path = "/app/workspace/"+model_path
        # Check if the model is already downloaded
        if os.path.exists(file_path):
            logger.info(f"File {file_path} already exists, skipping download.")
            return
        logger.info(f"Downloading {model_url} → {file_path}")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        #download the model
        resumable_download(model_url, file_path)
   
    def _update_prompt_fields(self, prompt: str, data: dict) -> str:
        # This function formats the prompt with the provided data.
        # You can implement your own logic to format the prompt here.
        return re.sub(r"\|([^|]+)\|", lambda m: str(data.get(m.group(1), m.group(0))), prompt)
    
    def _extract_seed_from_prompt(self, prompt: str) -> int:
        # Extract the seed from the prompt using regex
        match = re.search(r'("seed": )(\d+)', prompt)
        if match:
            return int(match.group(1))
        return None
    
    async def _download_result(self, url: str) -> bytes:
        # Download the result from the given URL
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code == 200:
                return response.content
            else:
                raise ValueError(f"Failed to download result: {response.status_code} {response.text}")
    
    def setup_pipelines(self):
        # This function is a placeholder for the actual pipeline setup logic.
        # You can implement the logic to set up pipelines here.
        logger.info("Setting up pipelines...")
        # Example: await self._setup_pipeline("example_pipeline")
        pipelines = {}
        pipelines_path = "/app/settings/pipelines"
        for filename in os.listdir(pipelines_path):
            if filename.endswith('.json') and filename.startswith("comfyui--"):
                pipeline = filename.replace("comfyui--", "").replace(".json", "")
                logger.info(f"found pipeline {pipeline}, setting up nodes and downloading models as needed")
                with open(os.path.join(pipelines_path, filename), 'r') as f:
                    try:
                        pipeline_settings = json.load(f)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to get pipeline settings, JSON is invalid {filename}: {e}")
                        
                    pipelines[pipeline] = pipeline_settings
                
        for pipeline in pipelines:
            pipeline_settings = pipelines[pipeline] 
            
            #------------------------------
            # install nodes for the pipeline
            #------------------------------ 
            if 'nodes' in pipeline_settings:
                #install the nodes in separate virtualenvs
                try:
                    #create the virtualenv if needed
                    virtualenv_root = os.getenv("PYENV_ROOT", "/root/.pyenv")
                    if not os.path.exists(f"{virtualenv_root}/versions/{pipeline}"):
                        self._create_pipeline_env(pipeline)
                except Exception as e:
                    logger.error(f"Failed to create virtualenv for {pipeline}: {e}")
                    raise ValueError(f"Failed to create virtualenv for {pipeline}.")
                #install the nodes and additional requirements
                for node in pipeline_settings['nodes']:
                    self._install_node(node, pipeline)

                if not os.path.exists(f"/etc/supervisor/conf.d/{pipeline}.conf"):
                    #create the pipeline runner config
                    create_pipeline_runner_config(pipeline)
            else:
                #no extra nodes or requirements to install we can use the core venv
                logger.info(f"no custom nodes found for {pipeline}, will use core comfyui environment")

            #------------------------------
            # download models
            #------------------------------       
            if 'models' in pipeline_settings:
                for model in pipeline_settings['models']:
                    model_path = model
                    model_url = pipeline_settings['models'][model]
                    self._download_model(model_url, model_path)

    async def get_pipelines(self):
        logger.info("Setting up pipelines...")
        # Example: await self._setup_pipeline("example_pipeline")
        pipelines = []
        pipelines_path = "/app/settings/pipelines"
        for filename in os.listdir(pipelines_path):
            if filename.endswith('.json') and filename.startswith("comfyui--"):
                pipeline = filename.replace("comfyui--", "").replace(".json", "")
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
    
    async def process(self, pipeline_name: str, model_id: str, params: Dict[str, any], files: Dict[str, any]):
        # This function is a placeholder for the actual ComfyUI workflow proxying logic.
        # You can implement the logic to handle ComfyUI-specific requests here.
        logger.info(f"ComfyUI workflow proxying for path: {pipeline_name}")
        pipeline_id = pipeline_name + "--" + model_id.replace("/","--")
        
        pipeline_settings_path = f"/app/settings/pipelines/comfyui--{pipeline_id}.json"
        if not os.path.exists(pipeline_settings_path):
            raise ValueError(f"Pipeline settings file not found: {pipeline_settings_path}")
        
        pipeline_settings = {}
        with open(pipeline_settings_path, "r") as f:
            pipeline_settings = json.load(f)
            if not "prompt" in pipeline_settings:
                raise ValueError(f"Prompt not found in pipeline settings: {pipeline_settings_path}")
        
        #startup comfyui
        if "nodes" in pipeline_settings:
            start_backend(pipeline_id)
        else:
            start_backend("comfy_ui") #no custom nodes needed, use default environment
        
        logger.info(f"Starting ComfyUI using custom node environment: {pipeline_id if 'nodes' in pipeline_settings else 'comfy_ui'}")
        

        #client to send data to backend
        client = httpx.AsyncClient()

        #wait for startup
        while True:
            await asyncio.sleep(1)
            try:
                resp = await client.get(f"{BACKEND_URL}/system_stats", timeout=2)
                if resp.status_code == 200:
                    break
                logger.info("waiting for comfyui to startup...")
            except Exception as e:
                logger.error(f"Error connecting to ComfyUI backend: {e}")
        


        #upload the files and add to the prompt
        if files:
            for file in files:
                filename, file_content, content_type = files[file]
                upload_data = {
                    "overwrite": "true",
                    "type": "input"
                }
                
                if content_type == "image/mask":
                    upload_files = {"image": (filename, file_content, "image/png")}
                    resp = await client.post(
                        url=f"{BACKEND_URL}/upload/mask",
                        data=upload_data,
                        files=upload_files,
                    )

                    if resp.status_code != 200:
                        raise ValueError(f"Failed to upload mask: {resp.text}")
                elif content_type == "image/png":
                    upload_files = {"image": (filename, file_content, "image/png")}
                    resp = await client.post(
                        url=f"{BACKEND_URL}/upload/image",
                        data=upload_data,
                        files=upload_files,
                    )

                    if resp.status_code != 200:
                        raise ValueError(f"Failed to upload image: {resp.text}")

                #update the prompt with the uploaded file path
                result = resp.json()
                params[file] = result["filename"]
        
        #update the prompt for processing
        prompt = json.dumps(pipeline_settings["prompt"])
        prompt_with_data = self._update_prompt_fields(prompt, params)
        logger.debug(f"Prompt with data: {prompt_with_data}")
        #queue the prompt
        resp = await client.post(
            url=f"{BACKEND_URL}/prompt",
            json={"prompt":json.loads(prompt_with_data)},
            timeout=None  # Optional: disable timeout for SSE
        )

        logger.info(f"Prompt queued")
        if resp.status_code != 200:
            raise ValueError(f"Failed to queue prompt: {resp.text}")

        prompt_id = resp.json()
        prompt_id = prompt_id["prompt_id"]
        logger.info(f"Prompt ID: {prompt_id}")
        status_json = {}
        while True:
            await asyncio.sleep(0.5)
            status = await client.get(
                url=f"{BACKEND_URL}/history/{prompt_id}",
                timeout=None  # Optional: disable timeout for SSE
            )

            if status.status_code != 200:
                break
            print(status_json)
            status_json = status.json()
            #no status available, continue
            if not prompt_id in status_json:
                continue
            prompt_result = status_json[prompt_id]

            if 'status' in prompt_result:
                prompt_result_status = prompt_result['status']
                if prompt_result_status['completed']:
                    if prompt_result_status['status_str'] == "success":
                        logger.info(f"Prompt processed successfully: {prompt_id}")
                    else:
                        logger.error(f"Prompt processing failed: {prompt_id} {prompt_result_status}")
                        raise ValueError(f"Prompt processing failed: {prompt_result_status}")
                
                break

            logger.info(f"Waiting for prompt to be processed: {prompt_id}")
            
        
        #download the output files and return
        combined_output = []
        outputs = prompt_result.get("outputs", {})
        seed = self._extract_seed_from_prompt(str(prompt_result.get("prompt", {})))
        
        for output_node in outputs:
            for output_type in outputs[output_node]:
                if output_type == "images" or output_type == "audio":
                    for result in outputs[output_node][output_type]:
                        result = await client.get(f"{BACKEND_URL}/view?filename={result['filename']}&subfolder={result['subfolder']}&type={result['type']}")
                        if result.status_code != 200:
                            raise ValueError(f"Failed to download result: {result.text}")
                        
                        result_bytes = io.BytesIO(result.content)
                        if output_type == "images":
                            pil_img = Image.open(result_bytes)
                            combined_output.append({"url": image_to_data_url(pil_img), "seed": seed, "nsfw": "unknown"})
                        elif output_type == "audio":
                            combined_output.append({"url": audio_to_data_url(result_bytes), "seed": seed, "nsfw": "unknown"})

        
        if pipeline_name == "text-to-image":
            return {"images": combined_output}
        else:
            return combined_output


    