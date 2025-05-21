import logging
import os
import json
from typing import Union, Dict

from fastapi import APIRouter, Request, Response, Depends, File, Form, status
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.datastructures import UploadFile as FastAPIUploadFile
from starlette.datastructures import FormData
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer



from app.pipelines.base import Pipeline

from app.dependencies import get_pipeline
from app.routes.utils import (
    HTTPError,
    ImageResponse,
    handle_pipeline_exception,
    http_error,
    image_to_data_url,
)

router = APIRouter()

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/pipelines", response_model=None)
async def get_pipelines(pipeline: Pipeline = Depends(get_pipeline),
                        ) -> JSONResponse:
    """
    Get the list of pipelines.
    """
    try:
        pipelines = await pipeline.get_pipelines()
        if not pipelines:
            logger.info("No pipelines found.")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content=http_error("No pipelines found."),
            )
        
        logger.info(f"Found {len(pipelines)} pipelines.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=pipelines,
        )
    except Exception as e:
        logger.error(f"Error fetching pipelines: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=http_error("Failed to fetch pipelines."),
        )
    
@router.post("/pipelines/refresh", response_model=None)
async def refresh_pipelines(pipeline: Pipeline = Depends(get_pipeline),
                            ) -> JSONResponse:
    """
    Refresh the pipeline list.
    """
    try:
        # Assuming you have a function to refresh pipelines
        await pipeline.refresh_pipelines()
        
        logger.info("Pipelines refreshed successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "Pipelines refreshed successfully."},
        )
    except Exception as e:
        logger.error(f"Error refreshing pipelines: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=http_error(f"Failed to refresh pipelines. error={e}"),
        )

@router.post("/pipelines/stop", response_model=None)
async def stop_pipelines(pipeline: Pipeline = Depends(get_pipeline),
                        ) -> JSONResponse:
    """
    Stop the pipelines.
    """
    try:
        # Assuming you have a function to stop the pipeline
        await pipeline.stop_pipelines()
        
        logger.info("Pipelines stopped successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "Pipelines stopped successfully."},
        )
    except Exception as e:
        logger.error(f"Error stopping pipelines: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=http_error(f"Failed to stop pipeline. {e}"),
        )

@router.api_route("/{pipeline_name:path}", 
                  response_model=None,
                  methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(pipeline_name: str, 
                request: Request,
                pipeline: Pipeline = Depends(get_pipeline),
                token: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False))
     ) -> Union[JSONResponse, StreamingResponse]:
    
    auth_token = os.environ.get("AUTH_TOKEN")
    if auth_token:
        if not token or token.credentials != auth_token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
                content=http_error("Invalid bearer token."),
            )
        
    headers = dict(request.headers)
    headers.pop("host", None)  # Avoid host header conflicts

    content_type = request.headers.get("content-type", "")
    
    files = None
    params = dict(request.query_params)
    
    if "application/json" in content_type:
        params.update(await request.json())
        logger.info(f"Received JSON data: {params}")
    elif "multipart/form-data" in content_type:
        form: FormData = await request.form()
        files = {}

        for key, value in form.multi_items():
            if isinstance(value, FastAPIUploadFile):
                files[key] = (value.filename, await value.read(), value.content_type)
            elif value.content_type == "application/json":
                part_data = await value.read()
                params.update(json.loads(part_data))
            else:
                #data sent as form field in plain text
                params[key] = value

    else:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=http_error("Unsupported content type"),
        )
    
    model_id = params.pop("model_id", None)
    if model_id == None:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=http_error("model_id in request params is required"),
        )
    
    #process the request with the pipeline backend (e.g. comfyui, diffusers, transformers, etc)
    #try:
    result = await pipeline(pipeline_name, model_id, params, files)    
    #except Exception as e:
    #    logger.error(f"Pipeline error: {e}")
    #    return JSONResponse(
    #        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #        content=http_error(f"Pipeline processing error: {e}"),
    #    )

    if result is None:
        logger.error("No result returned from backend.")
        return JSONResponse(
            status_code=status.HTTP,
            content=http_error("No result returned from backend."),
        )
    if "stream" in params:
        if params["stream"]:
            return StreamingResponse(
                stream_generator(result),
                media_type="text/event-stream"
            )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result
        )
    
    
async def stream_generator(generator):
    try:
        async for chunk in generator:
            yield f"data: {chunk}\n\n"

    except Exception as e:
        logger.error(f"Streaming error: {str(e)}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

