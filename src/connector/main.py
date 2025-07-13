import asyncio
import logging
import os
import threading
from dotenv import load_dotenv
from nats.aio.msg import Msg
from datetime import datetime
import uuid
import json
from typing import Optional, List

from playwright.async_api import async_playwright
from sqlalchemy import create_engine, Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import sessionmaker

from src.lib_py.middlewares.jetstream_event_subscriber import JetStreamEventSubscriber
from src.lib_py.middlewares.jetstream_publisher import JetStreamPublisher
from src.lib_py.gen_types import raw_event_pb2, poll_source_pb2
from src.lib_py.middlewares.readiness_probe import ReadinessProbe
from src.lib_py.models.models import Base

# Load environment variables from .env file
load_dotenv()

# Get log level from env
log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)

# Get log format from env
log_format = os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Configure logging
logging.basicConfig(level=log_level, format=log_format)
logger = logging.getLogger("sentinel-connector")

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
raw_events_publisher: Optional[JetStreamPublisher] = None

# DB for deduplication
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL) if DATABASE_URL else None
SessionFactory: Optional[sessionmaker] = sessionmaker(bind=engine) if engine else None

class ProcessedItem(Base):
    __tablename__ = "processed_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, nullable=False)
    item_url = Column(String, nullable=False)

    __table_args__ = (UniqueConstraint("source_id", "item_url", name="uix_source_item"),)

if engine:
    Base.metadata.create_all(engine)

PAGE_TIMEOUT = 15000  # ms

async def _scrape_links(url: str) -> List[tuple[str, str]]:
    """Return list of (title, href) tuples from first page using Playwright only."""
    links: List[tuple[str, str]] = []
    logger.info("🕸️  Launch headless browser for %s", url)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, timeout=PAGE_TIMEOUT)
        logger.info("📄  Page loaded, querying anchor tags…")
        anchors = await page.query_selector_all("a[href]")
        for a in anchors:
            href = await a.get_attribute("href")
            text = (await a.inner_text()).strip()
            if href and text and len(text) > 25 and href.startswith("http"):
                links.append((text, href))
        await browser.close()
    return links

async def poll_source_event_handler(msg: Msg):
    readiness_probe.update_last_seen()
    try:
        poll_source = poll_source_pb2.PollSource()
        poll_source.ParseFromString(msg.data)
        logger.info("📥 poll.source received: ID=%s name=%s", poll_source.id, poll_source.name)

        # Determine URL
        src_url: Optional[str] = None
        try:
            cfg = json.loads(poll_source.config_json)
            src_url = cfg.get("url")
        except Exception:
            pass
        if not src_url:
            src_url = poll_source.name  # fallback

        if not src_url.startswith("http"):
            logger.warning("⚠️  Source %s has invalid URL %s", poll_source.id, src_url)
            await msg.ack()
            return

        links = await _scrape_links(src_url)
        logger.info("🔍 Scraped %s candidate links from %s", len(links), src_url)

        if not (raw_events_publisher and SessionFactory):
            logger.error("❌ Publisher or DB not initialised")
            await msg.nak()
            return

        new_count = 0
        with SessionFactory() as db:
            for title, href in links:
                exists = db.query(ProcessedItem).filter_by(source_id=poll_source.id, item_url=href).first()
                if exists:
                    continue
                # Insert processed marker
                db.add(ProcessedItem(source_id=poll_source.id, item_url=href))
            # commit once after batch insert
            db.commit()

            for title, href in [l for l in links if not db.query(ProcessedItem).filter_by(source_id=poll_source.id, item_url=l[1]).first()]:
                event = raw_event_pb2.RawEvent(
                    id=str(uuid.uuid4()),
                    title=title[:200],
                    content=title,
                    timestamp=datetime.utcnow().isoformat(),
                    source=poll_source.name,
                )
                await raw_events_publisher.publish(event)
                new_count += 1

        logger.info("📤 Published %s new raw events for source %s", new_count, poll_source.id)
        await msg.ack()
        logger.info("✅ Acknowledged poll.source event %s", poll_source.id)
    except Exception as e:
        logger.exception("❌ Error processing poll.source event: %s", e)
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
