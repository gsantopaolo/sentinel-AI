# Sentinel-AI Scheduler Service
# -----------------------------------------------
# Bootstraps polling jobs for existing sources and
# reacts to new.source / removed.source JetStream
# events. Emits poll.source events on schedule.
# -----------------------------------------------

import asyncio
import json
import logging
import os
import threading
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from nats.aio.msg import Msg
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.orm.session import sessionmaker

from src.lib_py.gen_types import new_source_pb2, poll_source_pb2, removed_source_pb2
from src.lib_py.logic.source_logic import SourceLogic
from src.lib_py.models.models import Source as SourceModel
from src.lib_py.middlewares.jetstream_event_subscriber import JetStreamEventSubscriber
from src.lib_py.middlewares.jetstream_publisher import JetStreamPublisher
from src.lib_py.middlewares.readiness_probe import ReadinessProbe

# ────── ENV & LOGGING ──────────────────────────
load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
)
logger = logging.getLogger("sentinel-scheduler")

# Readiness probe timeout
READINESS_TIME_OUT = int(os.getenv("SCHEDULER_READINESS_TIME_OUT", 500))

# NATS connection
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_RECONNECT_TIME_WAIT = int(os.getenv("NATS_RECONNECT_TIME_WAIT", 5))
NATS_CONNECT_TIMEOUT = int(os.getenv("NATS_CONNECT_TIMEOUT", 10))
NATS_MAX_RECONNECT_ATTEMPTS = int(os.getenv("NATS_MAX_RECONNECT_ATTEMPTS", 60))

# Global default poll interval (seconds)
DEFAULT_POLL_INTERVAL_SECONDS = int(os.getenv("SCHEDULER_DEFAULT_POLL_INTERVAL", 300))

# Stream / subject names
NEW_SOURCE_STREAM_NAME = "new-source-stream"
NEW_SOURCE_SUBJECT = "new.source"
REMOVED_SOURCE_STREAM_NAME = "removed-source-stream"
REMOVED_SOURCE_SUBJECT = "removed.source"
POLL_SOURCE_STREAM_NAME = "poll-source-stream"
POLL_SOURCE_SUBJECT = "poll.source"

# ────── GLOBALS ────────────────────────────────
scheduler = AsyncIOScheduler()
_poll_pub: Optional[JetStreamPublisher] = None
_SessionFactory: Optional[sessionmaker] = None

# ────── HELPER FUNCTIONS ───────────────────────
async def _publish_poll_event(source_id: int) -> None:
    """Fetch fresh source from DB and publish poll.source."""
    if not (_poll_pub and _SessionFactory):
        logger.error("Publisher or DB session factory not initialised")
        return

    try:
        with _SessionFactory() as db:
            src: SourceModel | None = db.query(SourceModel).filter(SourceModel.id == source_id).first()
            if not src:
                logger.warning("Source %s not found, skipping poll", source_id)
                return

            cfg_json = json.dumps(src.config) if isinstance(src.config, (dict, list)) else (src.config or "{}")

            msg = poll_source_pb2.PollSource(
                id=src.id,
                name=src.name,
                type=src.type,
                config_json=cfg_json,
                is_active=src.is_active,
            )
            await _poll_pub.publish(msg)
            logger.info("poll.source emitted for source %s", src.id)
    except Exception as exc:
        logger.exception("Failed to publish poll.source for %s: %s", source_id, exc)


async def _schedule_poll_job(sid: int, name: str, stype: str, cfg_json: Optional[str], active: bool) -> None:
    """Create/replace APScheduler job for a source."""
    if not active:
        logger.info("Source %s is inactive; skipping", sid)
        return

    interval = DEFAULT_POLL_INTERVAL_SECONDS
    try:
        if cfg_json:
            cfg = json.loads(cfg_json)
            interval = int(cfg.get("poll_interval_seconds", interval))
    except Exception:
        logger.warning("Could not parse interval for source %s", sid)

    job_id = f"poll_source_{sid}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        _publish_poll_event,
        "interval",
        seconds=interval,
        args=[sid],
        id=job_id,
        replace_existing=True,
    )
    logger.info(f"⏱️Scheduled interval {interval} polling for source %{sid}")


# ────── EVENT HANDLERS ─────────────────────────
async def _handle_new_source(msg: Msg) -> None:
    try:
        ev = new_source_pb2.NewSource()
        ev.ParseFromString(msg.data)
        logger.info("new.source received: %s", ev.id)
        await _schedule_poll_job(ev.id, ev.name, ev.type, ev.config_json, ev.is_active)
        await msg.ack()
    except Exception as exc:
        logger.exception("Error processing new.source: %s", exc)
        await msg.nak()


async def _handle_removed_source(msg: Msg) -> None:
    try:
        ev = removed_source_pb2.RemovedSource()
        ev.ParseFromString(msg.data)
        logger.info("removed.source received: %s", ev.id)
        job_id = f"poll_source_{ev.id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            logger.info("Removed job %s", job_id)
        await msg.ack()
    except Exception as exc:
        logger.exception("Error processing removed.source: %s", exc)
        await msg.nak()


# ────── MAIN ───────────────────────────────────
async def _bootstrap_db_sources() -> None:
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL not set")
        engine = create_engine(db_url)
        global _SessionFactory
        _SessionFactory = sessionmaker(bind=engine)

        with _SessionFactory() as db:
            sources = SourceLogic(db).get_all_sources()
            logger.info("Bootstrapping %s sources", len(sources))
            for s in sources:
                await _schedule_poll_job(s.id, s.name, s.type, json.dumps(s.config) if s.config else None, s.is_active)
    except Exception as exc:
        logger.exception("Bootstrap failed: %s", exc)


async def main() -> None:
    logger.info("Scheduler starting …")

    # readiness probe
    rp = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    threading.Thread(target=rp.start_server, daemon=True).start()

    # publisher
    global _poll_pub
    _poll_pub = JetStreamPublisher(
        subject=POLL_SOURCE_SUBJECT,
        stream_name=POLL_SOURCE_STREAM_NAME,
        nats_url=NATS_URL,
        nats_reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        nats_connect_timeout=NATS_CONNECT_TIMEOUT,
        nats_max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        message_type="PollSource",
    )
    await _poll_pub.connect()

    # subscribers
    new_sub = JetStreamEventSubscriber(
        nats_url=NATS_URL,
        stream_name=NEW_SOURCE_STREAM_NAME,
        subject=NEW_SOURCE_SUBJECT,
        connect_timeout=NATS_CONNECT_TIMEOUT,
        reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        ack_wait=30,
        max_deliver=5,
        proto_message_type=new_source_pb2.NewSource,
    )
    new_sub.set_event_handler(_handle_new_source)

    rem_sub = JetStreamEventSubscriber(
        nats_url=NATS_URL,
        stream_name=REMOVED_SOURCE_STREAM_NAME,
        subject=REMOVED_SOURCE_SUBJECT,
        connect_timeout=NATS_CONNECT_TIMEOUT,
        reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        ack_wait=30,
        max_deliver=5,
        proto_message_type=removed_source_pb2.RemovedSource,
    )
    rem_sub.set_event_handler(_handle_removed_source)

    # start scheduler & bootstrap
    scheduler.start()
    await _bootstrap_db_sources()
    logger.info("APScheduler started")

    # await subscribers forever
    await asyncio.gather(
        new_sub.connect_and_subscribe(),
        rem_sub.connect_and_subscribe(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scheduler shutdown requested")
    finally:
        scheduler.shutdown(wait=False)
        if _poll_pub:
            asyncio.run(_poll_pub.close())
        logger.info("Scheduler stopped")
