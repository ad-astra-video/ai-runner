import httpx
import logging
import time

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] (batch_pipelines_refresh) %(message)s')

def start_refresh_loop():
    time.sleep(600) #let things startup
    
    last_refresh = 0
    first_run_success = False
    while True:
        time.sleep(60)  # Sleep for 10 minutes
        
        with httpx.Client() as client:
            try:
                resp = client.post("http://localhost:8000/pipelines/stop")
                if resp.status_code == 200:
                    #pipelines = resp.json()
                    logger.info("Pipelines stop completed")
                else:
                    logger.error(f"Failed to stop pipelines: {resp.status_code} - {resp.text}")
                #server has been up at least once
                first_run_success = True
            except httpx.RequestError as e:
                logger.error(f"Request error: {e}")
            except httpx.ConnectError as e:
                logger.error("server not available")
                
            #run pipeline refresh every 10 minutes
            if (last_refresh+600) < time.time():
                try:
                    resp = client.post("http://localhost:8000/pipelines/refresh")
                    if resp.status_code == 200:
                        pipelines = resp.json()
                        logger.info("Pipelines refresh completed")
                    else:
                        logger.error(f"Failed to refresh pipelines: {resp.status_code} - {resp.text}")
                except httpx.RequestError as e:
                    if first_run_success:
                        logger.error(f"Request error: {e}")
                except httpx.ConnectError as e:
                    logger.error("server not available")

        
if __name__ == "__main__":
    start_refresh_loop()
    pass
