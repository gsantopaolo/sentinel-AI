import asyncio
import logging
import os
import threading
from dotenv import load_dotenv

from src.lib_py.middlewares.readiness_probe import ReadinessProbe

# Load environment variables from .env file
load_dotenv()

# Get log level from env
log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)

# Get log format from env
log_format = os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Configure logging
logging.basicConfig(level=log_level, format=log_format)
logger = logging.getLogger(__name__)

READINESS_TIME_OUT = int(os.getenv('GUARDIAN_READINESS_TIME_OUT', 500))

async def main():
    logger.info("🛠️ Guardian service starting...")

    # Start the readiness probe server in a separate thread
    readiness_probe = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    readiness_probe_thread = threading.Thread(target=readiness_probe.start_server, daemon=True)
    readiness_probe_thread.start()
    logger.info("✅ Readiness probe server started.")

    try:
        # Keep the main loop running indefinitely
        while True:
            readiness_probe.update_last_seen()
            await asyncio.sleep(10) # Update readiness every 10 seconds
    except asyncio.CancelledError:
        logger.info("🛑 Guardian service received shutdown signal.")
    finally:
        logger.info("✅ Guardian service shut down.")

if __name__ == "__main__":
    asyncio.run(main())
