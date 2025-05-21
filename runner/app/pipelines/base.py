from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

class HealthCheck(BaseModel):
    status: Literal["OK", "ERROR", "IDLE"] = Field(..., description="The health status of the pipeline")

class Version(BaseModel):
    pipeline: str
    model_id: str
    version: str = Field(..., description="The version of the Runner")

class Pipeline(ABC):
    @abstractmethod
    def __init__(self, model_id: str, model_dir: str):
        self.model_id: str # declare the field here so the type hint is available when using this abstract class
        raise NotImplementedError("Pipeline should implement an __init__ method")

    @abstractmethod
    def __call__(self, **kwargs) -> Any:
        raise NotImplementedError("Pipeline should implement a __call__ method")

    def get_health(self) -> HealthCheck:
        """
        Returns a health check object for the pipeline.
        """
        return HealthCheck(status="OK", version="undefined")
    
    def get_pipelines(self) -> list[dict]:
        """
        Get the list of pipelines available in the backend.
        """
        raise NotImplementedError("Pipeline should implement a get_pipelines method")
    def refresh_pipelines(self) -> bool:
        """
        Refresh the list of pipelines.
        """
        raise NotImplementedError("Pipeline should implement a refresh_pipelines method")
    def stop_pipelines(self):
        """
        Stop the pipeline.
        """
        raise NotImplementedError("Pipeline should implement a stop_pipeline method")

class Backend(ABC):
    @abstractmethod
    def __init__(self, **kwargs):
        raise NotImplementedError("Backend should implement an __init__ method")
    
    @abstractmethod
    def process(self, data: dict, files: dict, **kwargs) -> Any:
        """
        Process the input data and return the output.
        """
        raise NotImplementedError("Backend should implement a process method")

    @abstractmethod
    def setup_pipelines(self):
        """
        Setup the pipelines for the backend.
        """
        pass
    @abstractmethod
    def stop_pipelines(self):
        """
        Stop the pipelines as needed.
        """
        raise NotImplementedError("Backend should implement a stop_pipelines method")
    def get_health(self) -> HealthCheck:
        """
        Returns a health check object for the backend.
        """
        return HealthCheck(status="OK", version="undefined")
    