import asyncio
import os
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

        BACKEND_TYPE = os.getenv("BACKEND_TYPE", "")
        self.backend = None
        if BACKEND_TYPE == "comfyui":
            self.backend = ComfyUIBackend()
    

    async def __call__(self, pipeline_name, model_id, params: Dict[str, any], files: Dict[str, any], **kwargs):
        result = await self.backend.process(pipeline_name, model_id, params, files, **kwargs)
        if result is None:
            raise ValueError("No result returned from backend.")
        
        return result

    async def get_pipelines(self):
        """
        Get the list of pipelines.
        """
        return await self.backend.get_pipelines()
            
    async def refresh_pipelines(self):
        """
        Refresh the list of pipelines.
        """
        if self.backend:
            await asyncio.to_thread(self.backend.setup_pipelines)
        else:
            raise ValueError("No backend available for refreshing pipelines.")