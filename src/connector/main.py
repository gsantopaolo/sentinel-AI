import asyncio
import logging
import os
import threading
from dotenv import load_dotenv
from nats.aio.msg import Msg
from datetime import datetime
import uuid

from src.lib_py.middlewares.jetstream_event_subscriber import JetStreamEventSubscriber
from src.lib_py.middlewares.jetstream_publisher import JetStreamPublisher
from src.lib_py.gen_types import raw_event_pb2, new_source_pb2, poll_source_pb2
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

READINESS_TIME_OUT = int(os.getenv('CONNECTOR_READINESS_TIME_OUT', 500))

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_RECONNECT_TIME_WAIT = int(os.getenv("NATS_RECONNECT_TIME_WAIT", 10))
NATS_CONNECT_TIMEOUT = int(os.getenv("NATS_CONNECT_TIMEOUT", 10))
NATS_MAX_RECONNECT_ATTEMPTS = int(os.getenv("NATS_MAX_RECONNECT_ATTEMPTS", 60))

# NATS Stream configuration
POLL_SOURCE_STREAM_NAME = "poll-source-stream"
POLL_SOURCE_SUBJECT = "poll.source"
RAW_EVENTS_STREAM_NAME = "raw-events-stream"
RAW_EVENTS_SUBJECT = "raw.events"

# JetStream Publisher
raw_events_publisher: JetStreamPublisher = None

async def generate_fake_news(source_name: str) -> raw_event_pb2.RawEvent:
    """Generates a fake news event."""
    event_id = str(uuid.uuid4())
    title = f"Fake News from {source_name} - {datetime.utcnow().isoformat()}"
    content = f"This is a fake news article generated for testing purposes from {source_name}. It contains some interesting but entirely fabricated information."
    timestamp = datetime.utcnow().isoformat()
    
    return raw_event_pb2.RawEvent(
        id=event_id,
        title=title,
        content=content,
        timestamp=timestamp,
        source=source_name
    )

async def poll_source_event_handler(msg: Msg):
    readiness_probe.update_last_seen()
    try:
        poll_source = poll_source_pb2.PollSource()
        poll_source.ParseFromString(msg.data)
        logger.info(f"✉️ Received poll.source event for source: {poll_source.name} (ID: {poll_source.id})")
        
        # Simulate scraping and generating a raw event
        # todo: make the real implementation to scrape the source
        # before scraping the source we need to understand if the source has
        # been already scraped or not, if already scraped we need to check if
        # it was updated since we scraped.
        # also, we need to verify if this logic shall go here or in the scheduler...
        fake_news = await generate_fake_news(poll_source.name)
        await raw_events_publisher.publish(fake_news)
        logger.info(f"✉️ Published fake news event '{fake_news.id}' from source '{poll_source.name}' to raw.events.")

        await msg.ack()
        logger.info(f"✅ Acknowledged poll.source event for {poll_source.name}")
    except Exception as e:
        logger.error(f"❌ Error processing poll.source event: {e}")
        await msg.nak() # Negative acknowledgment

async def main():
    logger.info("🛠️ Connector service starting...")

    # Start the readiness probe server in a separate thread
    global readiness_probe
    readiness_probe = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    readiness_probe_thread = threading.Thread(target=readiness_probe.start_server, daemon=True)
    readiness_probe_thread.start()
    logger.info("✅ Readiness probe server started.")

    # Initialize raw events publisher
    global raw_events_publisher
    raw_events_publisher = JetStreamPublisher(
        subject=RAW_EVENTS_SUBJECT,
        stream_name=RAW_EVENTS_STREAM_NAME,
        nats_url=NATS_URL,
        nats_reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        nats_connect_timeout=NATS_CONNECT_TIMEOUT,
        nats_max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        message_type="RawEvent"
    )
    try:
        await raw_events_publisher.connect()
        logger.info("✅ Raw events publisher connected to NATS.")
    except Exception as e:
        logger.error(f"❌ Failed to connect raw events publisher to NATS: {e}")
        return # Exit if NATS connection fails

    # Initialize poll.source subscriber
    poll_source_subscriber = JetStreamEventSubscriber(
        nats_url=NATS_URL,
        stream_name=POLL_SOURCE_STREAM_NAME,
        subject=POLL_SOURCE_SUBJECT,
        connect_timeout=NATS_CONNECT_TIMEOUT,
        reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        ack_wait=60, # seconds
        max_deliver=3,
        proto_message_type=poll_source_pb2.PollSource
    )
    poll_source_subscriber.set_event_handler(poll_source_event_handler)

    # Connect and subscribe to NATS
    try:
        await poll_source_subscriber.connect_and_subscribe()
        logger.info(f"✅ Subscribed to {POLL_SOURCE_SUBJECT}")
    except Exception as e:
        logger.error(f"❌ Failed to connect or subscribe to NATS: {e}")
        return # Exit if NATS connection fails

    try:
        # Keep the main loop running indefinitely
        while True:
            readiness_probe.update_last_seen()
            await asyncio.sleep(10) # Update readiness every 10 seconds
    except asyncio.CancelledError:
        logger.info("🛑 Connector service received shutdown signal.")
    finally:
        await poll_source_subscriber.close()
        await raw_events_publisher.close()
        logger.info("✅ NATS connections closed.")

if __name__ == "__main__":
    asyncio.run(main())
