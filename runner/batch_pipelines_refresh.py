import httpx
import logging
import time

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] (batch_pipelines_refresh) %(message)s')

while True:
    time.sleep(600)  # Sleep for 10 minutes
    with httpx.Client() as client:
        try:
            resp = client.get("http://localhost:8000/pipelines")
            if resp.status_code == 200:
                pipelines = resp.json()
                logger.info("Pipelines refresh completed")
            else:
                logger.error(f"Failed to refresh pipelines: {resp.status_code} - {resp.text}")
        except httpx.RequestError as e:
            logger.error(f"Request error: {e}")


        
        
