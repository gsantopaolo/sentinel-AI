import asyncio
import logging
import os
import threading
from dotenv import load_dotenv
from nats.aio.msg import Msg
from nats.js.api import ConsumerConfig, DeliverPolicy, AckPolicy
from typing import List, Dict, Any

from src.lib_py.middlewares.readiness_probe import ReadinessProbe
from src.lib_py.middlewares.jetstream_event_subscriber import JetStreamEventSubscriber
from src.lib_py.alerters import Alerter, LoggingAlerter, FakeMessageAlerter

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

# Environment variables
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_RECONNECT_TIME_WAIT = int(os.getenv("NATS_RECONNECT_TIME_WAIT", 10))
NATS_CONNECT_TIMEOUT = int(os.getenv("NATS_CONNECT_TIMEOUT", 10))
NATS_MAX_RECONNECT_ATTEMPTS = int(os.getenv("NATS_MAX_RECONNECT_ATTEMPTS", 60))
READINESS_TIME_OUT = int(os.getenv('GUARDIAN_READINESS_TIME_OUT', 500))
ALERTS = [alerter.strip() for alerter in os.getenv('ALERTERS', 'logging').split(',')]

# NATS Stream configuration for Dead-Letter Queue
DLQ_STREAM_NAME = "sentinel-dlq"
DLQ_SUBJECT = "dlq.>"

alerters: List[Alerter] = []
readiness_probe: ReadinessProbe = None

async def dlq_event_handler(msg: Msg):
    """
    Handles messages received from the dead-letter queue.

    Args:
        msg (Msg): The message from the DLQ.
    """
    readiness_probe.update_last_seen()
    try:
        failure_details = {
            "failed_subject": msg.headers.get('Nats-Msg-Subject'),
            "failed_sequence": msg.headers.get('Nats-Sequence'),
            "delivery_count": msg.headers.get('Nats-Delivery-Count'),
            "reason": msg.headers.get('Nats-Rollup'),
            "payload": msg.data.decode('utf-8', errors='ignore')
        }

        alert_subject = f"Message Failure in subject: {failure_details['failed_subject']}"
        alert_message = "A message could not be processed after multiple retries and was sent to the Dead-Letter Queue."

        for alerter in alerters:
            await alerter.send_alert(alert_subject, alert_message, failure_details)

        await msg.ack()
        logger.info(f"Acknowledged DLQ message for subject: {failure_details['failed_subject']}")

    except Exception as e:
        logger.error(f"Error processing DLQ message: {e}")

async def main():
    logger.info("🛠️ Guardian service starting...")

    # Initialize Alerters
    for alerter_name in ALERTS:
        if alerter_name == 'logging':
            alerters.append(LoggingAlerter())
            logger.info("📢 LoggingAlerter enabled.")
        elif alerter_name == 'fake_message':
            alerters.append(FakeMessageAlerter())
            logger.info("📢 FakeMessageAlerter enabled.")
        else:
            logger.warning(f"Unknown alerter '{alerter_name}' specified.")

    global readiness_probe
    readiness_probe = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    readiness_probe_thread = threading.Thread(target=readiness_probe.start_server, daemon=True)
    readiness_probe_thread.start()
    logger.info("✅ Readiness probe server started.")

    subscriber = JetStreamEventSubscriber(
        nats_url=NATS_URL,
        stream_name=DLQ_STREAM_NAME,
        subject=DLQ_SUBJECT,
        connect_timeout=NATS_CONNECT_TIMEOUT,
        reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        ack_wait=60,  # seconds
        max_deliver=3,
        proto_message_type=None  # DLQ messages are raw, no specific protobuf type
    )
    subscriber.set_event_handler(dlq_event_handler)

    try:
        await subscriber.connect_and_subscribe()
        logger.info(f"✅ Subscribed to DLQ subject '{DLQ_SUBJECT}'")
    except Exception as e:
        logger.error(f"❌ Failed to connect or subscribe to NATS for DLQ: {e}")
        return

    try:
        while True:
            readiness_probe.update_last_seen()
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        logger.info("🛑 Guardian service received shutdown signal.")
    finally:
        await subscriber.close()
        logger.info("✅ NATS connections closed.")

if __name__ == "__main__":
    asyncio.run(main())
