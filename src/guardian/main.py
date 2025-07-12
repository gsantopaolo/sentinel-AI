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

READINESS_TIME_OUT = int(os.getenv('GUARDIAN_READINESS_TIME_OUT', 500))
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_RECONNECT_TIME_WAIT = int(os.getenv("NATS_RECONNECT_TIME_WAIT", 2))
NATS_CONNECT_TIMEOUT = int(os.getenv("NATS_CONNECT_TIMEOUT", 10))
NATS_MAX_RECONNECT_ATTEMPTS = int(os.getenv("NATS_MAX_RECONNECT_ATTEMPTS", 5))

# Configure Alerters
ALERTER_TYPES = os.getenv("ALERTERS", "logging,fake_message").split(',')

# Global readiness probe
readiness_probe: ReadinessProbe = None

def get_alerters() -> List[Alerter]:
    """Initializes and returns a list of configured alerters."""
    alerters: List[Alerter] = []
    for alerter_type in ALERTER_TYPES:
        if alerter_type == "logging":
            alerters.append(LoggingAlerter())
            logger.info("📢 LoggingAlerter enabled.")
        elif alerter_type == "fake_message":
            alerters.append(FakeMessageAlerter())
            logger.info("📢 FakeMessageAlerter enabled.")
    return alerters

async def dlq_handler(msg: Msg, alerters: List[Alerter]):
    """
    Handles messages received from the dead-letter queue.

    Args:
        msg (Msg): The message from the DLQ.
        alerters (List[Alerter]): The list of alerters to use.
    """
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
        logger.error(f"Error in DLQ handler: {e}", exc_info=True)
        # We don't nack, to avoid an infinite loop in the DLQ handler itself.


async def main():
    logger.info("🛠️ Guardian service starting...")

    # Initialize alerters
    alerters = get_alerters()
    if not alerters:
        logger.warning("🚨 No alerters configured. DLQ messages will be handled but not reported.")

    # Start the readiness probe server
    global readiness_probe
    readiness_probe = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    readiness_probe_thread = threading.Thread(target=readiness_probe.start_server, daemon=True)
    readiness_probe_thread.start()
    logger.info("✅ Readiness probe server started.")

    # Setup NATS subscriber for the Dead-Letter Queue
    subscriber = JetStreamEventSubscriber(
        nats_url=NATS_URL,
        reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        connect_timeout=NATS_CONNECT_TIMEOUT,
        max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS
    )

    try:
        await subscriber.connect()
        logger.info("✅ Connected to NATS JetStream.")

        # Create a callback that includes the alerters
        handler_with_alerters = lambda msg: dlq_handler(msg, alerters)

        # Configure the consumer to be durable and process all messages
        consumer_config = ConsumerConfig(
            durable_name="guardian-dlq-monitor",
            deliver_policy=DeliverPolicy.ALL,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=60  # seconds
        )

        # Subscribe to all dead-letter subjects
        await subscriber.subscribe_with_queue_group_and_durable(
            subject="dlq.>",
            queue_group="guardian-dlq-group",
            handler=handler_with_alerters,
            consumer_config=consumer_config
        )
        logger.info("👂 Subscribed to Dead-Letter Queue subject 'dlq.>'")

        # Keep the main loop running for readiness updates
        while True:
            await asyncio.sleep(10)

    except asyncio.CancelledError:
        logger.info("🛑 Guardian service received shutdown signal.")
    except Exception as e:
        logger.critical(f"💥 Unhandled exception in main loop: {e}", exc_info=True)
    finally:
        if subscriber.is_connected:
            await subscriber.disconnect()
            logger.info("✅ Disconnected from NATS JetStream.")
        logger.info("✅ Guardian service shut down.")

if __name__ == "__main__":
    asyncio.run(main())
