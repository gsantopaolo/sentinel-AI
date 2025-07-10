import asyncio
import logging
import os
import threading
from dotenv import load_dotenv
from nats.aio.msg import Msg
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.lib_py.middlewares.jetstream_event_subscriber import JetStreamEventSubscriber
from src.lib_py.gen_types import new_source_pb2, removed_source_pb2, poll_source_pb2
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

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_RECONNECT_TIME_WAIT = int(os.getenv("NATS_RECONNECT_TIME_WAIT", 10))
NATS_CONNECT_TIMEOUT = int(os.getenv("NATS_CONNECT_TIMEOUT", 10))
NATS_MAX_RECONNECT_ATTEMPTS = int(os.getenv("NATS_MAX_RECONNECT_ATTEMPTS", 60))


# NATS Stream configuration for new.source and removed.source
NEW_SOURCE_STREAM_NAME = "new-source-stream"
NEW_SOURCE_SUBJECT = "new.source"
REMOVED_SOURCE_STREAM_NAME = "removed-source-stream"
REMOVED_SOURCE_SUBJECT = "removed.source"

READINESS_TIME_OUT = int(os.getenv('SCHEDULER_READINESS_TIME_OUT', 500))

# APScheduler setup
scheduler = AsyncIOScheduler()

async def new_source_event_handler(msg: Msg):
    try:
        new_source = new_source_pb2.NewSource()
        new_source.ParseFromString(msg.data)
        logger.info(f"✉️ Received new source event: ID={new_source.id}, Name={new_source.name}, Type={new_source.type}")
        # Here, you would add logic to schedule polling for this new source
        # For now, just acknowledge the message
        await msg.ack()
        logger.info(f"✅ Acknowledged new source event: {new_source.id}")
    except Exception as e:
        logger.error(f"❌ Error processing new source event: {e}")
        await msg.nak() # Negative acknowledgment

async def removed_source_event_handler(msg: Msg):
    try:
        removed_source = removed_source_pb2.RemovedSource()
        removed_source.ParseFromString(msg.data)
        logger.info(f"✉️ Received removed source event: ID={removed_source.id}")
        # Here, you would add logic to remove polling jobs for this source
        # For now, just acknowledge the message
        await msg.ack()
        logger.info(f"✅ Acknowledged removed source event: {removed_source.id}")
    except Exception as e:
        logger.error(f"❌ Error processing removed source event: {e}")
        await msg.nak() # Negative acknowledgment

async def main():
    logger.info("🛠️ Scheduler service starting...")

    # Start the readiness probe server in a separate thread
    readiness_probe = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    readiness_probe_thread = threading.Thread(target=readiness_probe.start_server, daemon=True)
    readiness_probe_thread.start()
    logger.info("✅ Readiness probe server started.")

    # Initialize subscribers
    new_source_subscriber = JetStreamEventSubscriber(
        nats_url=NATS_URL,
        stream_name=NEW_SOURCE_STREAM_NAME,
        subject=NEW_SOURCE_SUBJECT,
        connect_timeout=NATS_CONNECT_TIMEOUT,
        reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        ack_wait=60, # seconds
        max_deliver=3,
        proto_message_type=new_source_pb2.NewSource
    )
    new_source_subscriber.set_event_handler(new_source_event_handler)

    removed_source_subscriber = JetStreamEventSubscriber(
        nats_url=NATS_URL,
        stream_name=REMOVED_SOURCE_STREAM_NAME,
        subject=REMOVED_SOURCE_SUBJECT,
        connect_timeout=NATS_CONNECT_TIMEOUT,
        reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        ack_wait=60, # seconds
        max_deliver=3,
        proto_message_type=removed_source_pb2.RemovedSource
    )
    removed_source_subscriber.set_event_handler(removed_source_event_handler)

    # Placeholder for emitting poll.source events
    # In a real scenario, this would be triggered by APScheduler based on source configurations
    # For demonstration, let's just emit a dummy poll.source event
    # dummy_poll_source = poll_source_pb2.PollSource(
    #     id=1,
    #     name="Dummy Source",
    #     type="RSS",
    #     config_json="{}",
    #     is_active=True
    # )
    # poll_source_publisher = JetStreamPublisher(
    #     subject=POLL_SOURCE_SUBJECT,
    #     stream_name=POLL_SOURCE_STREAM_NAME,
    #     nats_url=NATS_URL,
    #     nats_reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
    #     nats_connect_timeout=NATS_CONNECT_TIMEOUT,
    #     nats_max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
    #     message_type="PollSource"
    # )
    # await poll_source_publisher.connect()
    # await poll_source_publisher.publish(dummy_poll_source)
    # logger.info(f"✉️ Emitted dummy poll.source event for {dummy_poll_source.name}")

    # Connect and subscribe to NATS
    try:
        await new_source_subscriber.connect_and_subscribe()
        logger.info(f"✅ Subscribed to {NEW_SOURCE_SUBJECT}")
        await removed_source_subscriber.connect_and_subscribe()
        logger.info(f"✅ Subscribed to {REMOVED_SOURCE_SUBJECT}")
    except Exception as e:
        logger.error(f"❌ Failed to connect or subscribe to NATS: {e}")
        return # Exit if NATS connection fails

    # Start APScheduler
    scheduler.start()
    logger.info("✅ APScheduler started.")

    try:
        # Keep the main loop running indefinitely
        while True:
            readiness_probe.update_last_seen()
            await asyncio.sleep(10) # Update readiness every 10 seconds
    except asyncio.CancelledError:
        logger.info("🛑 Scheduler service received shutdown signal.")
    finally:
        scheduler.shutdown()
        logger.info("✅ APScheduler shut down.")
        await new_source_subscriber.close()
        await removed_source_subscriber.close()
        logger.info("✅ NATS subscribers closed.")

if __name__ == "__main__":
    asyncio.run(main())
