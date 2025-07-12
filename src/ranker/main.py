import asyncio
import logging
import os
import threading
from typing import List

from dotenv import load_dotenv
from nats.aio.msg import Msg
import yaml
from datetime import datetime, timedelta

from src.lib_py.middlewares.jetstream_event_subscriber import JetStreamEventSubscriber
from src.lib_py.middlewares.jetstream_publisher import JetStreamPublisher
from src.lib_py.middlewares.readiness_probe import ReadinessProbe
from src.lib_py.gen_types import filtered_event_pb2, ranked_event_pb2
from src.lib_py.logic.qdrant_logic import QdrantLogic

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

# Load configuration from YAML
with open('src/ranker/ranker_config.yaml', 'r') as f:
    config = yaml.safe_load(f)

RANKING_PARAMETERS = config['ranking_parameters']
CATEGORY_IMPORTANCE_SCORES = config['category_importance_scores']
RECENCY_DECAY = config['recency_decay']

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_RECONNECT_TIME_WAIT = int(os.getenv("NATS_RECONNECT_TIME_WAIT", 10))
NATS_CONNECT_TIMEOUT = int(os.getenv("NATS_CONNECT_TIMEOUT", 10))
NATS_MAX_RECONNECT_ATTEMPTS = int(os.getenv("NATS_MAX_RECONNECT_ATTEMPTS", 60))
READINESS_TIME_OUT = int(os.getenv('RANKER_READINESS_TIME_OUT', 500))

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "news_events")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

# NATS Stream configuration
FILTERED_EVENTS_STREAM_NAME = "filtered-events-stream"
FILTERED_EVENTS_SUBJECT = "filtered.events"
RANKED_EVENTS_STREAM_NAME = "ranked-events-stream"
RANKED_EVENTS_SUBJECT = "ranked.events"

# JetStream Publisher and Qdrant Logic
ranked_events_publisher: JetStreamPublisher = None
qdrant_logic: QdrantLogic = None

def calculate_importance_score(categories: List[str]) -> float:
    score = 0.0
    for category in categories:
        score += CATEGORY_IMPORTANCE_SCORES.get(category, CATEGORY_IMPORTANCE_SCORES['Other'])
    return score

def calculate_recency_score(timestamp_str: str) -> float:
    try:
        event_time = datetime.fromisoformat(timestamp_str)
    except ValueError:
        logger.warning(f"⚠️ Invalid timestamp format: {timestamp_str}. Using current time for recency calculation.")
        event_time = datetime.utcnow()

    time_diff = datetime.utcnow() - event_time
    half_life_seconds = RECENCY_DECAY['half_life_hours'] * 3600
    
    # Exponential decay formula: score = max_score * (0.5 ^ (time_diff_seconds / half_life_seconds))
    decay_factor = 0.5 ** (time_diff.total_seconds() / half_life_seconds)
    score = RECENCY_DECAY['max_score'] * decay_factor
    return score

async def filtered_event_handler(msg: Msg):
    readiness_probe.update_last_seen()
    try:
        filtered_event = filtered_event_pb2.FilteredEvent()
        filtered_event.ParseFromString(msg.data)
        logger.info(f"✉️ Received filtered event: ID={filtered_event.id}, Title='{filtered_event.title}'")

        # 1. Calculate Importance Score
        importance_score = calculate_importance_score(filtered_event.categories)
        logger.info(f"Calculated importance score for '{filtered_event.id}': {importance_score:.2f}")

        # 2. Calculate Recency Score
        recency_score = calculate_recency_score(filtered_event.timestamp)
        logger.info(f"Calculated recency score for '{filtered_event.id}': {recency_score:.2f}")

        # 3. Calculate Final Score
        final_score = (
            RANKING_PARAMETERS['importance_weight'] * importance_score +
            RANKING_PARAMETERS['recency_weight'] * recency_score
        )
        logger.info(f"Calculated final score for '{filtered_event.id}': {final_score:.2f}")

        # 4. Update event in Qdrant with scores
        # Retrieve the full event payload from Qdrant first to update it
        event_data = await qdrant_logic.retrieve_event_by_id(filtered_event.id)
        if event_data:
            event_data['importance_score'] = importance_score
            event_data['recency_score'] = recency_score
            event_data['final_score'] = final_score
            await qdrant_logic.upsert_event(event_data) # Upsert updates existing record
            logger.info(f"🗄️ Event '{filtered_event.id}' scores updated in Qdrant.")
        else:
            logger.warning(f"⚠️ Event '{filtered_event.id}' not found in Qdrant for score update.")

        # 5. Publish ranked event
        ranked_event = ranked_event_pb2.RankedEvent(
            id=filtered_event.id,
            title=filtered_event.title,
            timestamp=filtered_event.timestamp,
            source=filtered_event.source,
            categories=filtered_event.categories,
            is_relevant=filtered_event.is_relevant,
            importance_score=importance_score,
            recency_score=recency_score,
            final_score=final_score
        )
        await ranked_events_publisher.publish(ranked_event)
        logger.info(f"✉️ Published ranked event '{filtered_event.id}' to ranked.events.")

        await msg.ack()
        logger.info(f"✅ Acknowledged filtered event: {filtered_event.id}")
    except Exception as e:
        logger.error(f"❌ Error processing filtered event: {e}")
        await msg.nak() # Negative acknowledgment

async def main():
    logger.info("🛠️ Ranker service starting...")

    # Start the readiness probe server in a separate thread
    global readiness_probe
    readiness_probe = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    readiness_probe_thread = threading.Thread(target=readiness_probe.start_server, daemon=True)
    readiness_probe_thread.start()
    logger.info("✅ Readiness probe server started.")

    # Initialize Qdrant Logic
    global qdrant_logic
    qdrant_logic = QdrantLogic(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        collection_name=QDRANT_COLLECTION_NAME,
        embedding_model_name=EMBEDDING_MODEL_NAME
    )
    try:
        qdrant_logic.ensure_collection_exists()
        logger.info("✅ Qdrant collection ensured to exist.")
    except Exception as e:
        logger.error(f"❌ Failed to ensure Qdrant collection: {e}")
        return # Exit if Qdrant setup fails

    # Initialize ranked events publisher
    global ranked_events_publisher
    ranked_events_publisher = JetStreamPublisher(
        subject=RANKED_EVENTS_SUBJECT,
        stream_name=RANKED_EVENTS_STREAM_NAME,
        nats_url=NATS_URL,
        nats_reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        nats_connect_timeout=NATS_CONNECT_TIMEOUT,
        nats_max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        message_type="RankedEvent"
    )
    try:
        await ranked_events_publisher.connect()
        logger.info("✅ Ranked events publisher connected to NATS.")
    except Exception as e:
        logger.error(f"❌ Failed to connect ranked events publisher to NATS: {e}")
        return # Exit if NATS connection fails

    # Initialize filtered.events subscriber
    filtered_events_subscriber = JetStreamEventSubscriber(
        nats_url=NATS_URL,
        stream_name=FILTERED_EVENTS_STREAM_NAME,
        subject=FILTERED_EVENTS_SUBJECT,
        connect_timeout=NATS_CONNECT_TIMEOUT,
        reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        ack_wait=60, # seconds
        max_deliver=3,
        proto_message_type=filtered_event_pb2.FilteredEvent
    )
    filtered_events_subscriber.set_event_handler(filtered_event_handler)

    # Connect and subscribe to NATS
    try:
        await filtered_events_subscriber.connect_and_subscribe()
        logger.info(f"✅ Subscribed to {FILTERED_EVENTS_SUBJECT}")
    except Exception as e:
        logger.error(f"❌ Failed to connect or subscribe to NATS: {e}")
        return # Exit if NATS connection fails

    try:
        # Keep the main loop running indefinitely
        while True:
            readiness_probe.update_last_seen()
            await asyncio.sleep(10) # Update readiness every 10 seconds
    except asyncio.CancelledError:
        logger.info("🛑 Ranker service received shutdown signal.")
    finally:
        await filtered_events_subscriber.close()
        await ranked_events_publisher.close()
        logger.info("✅ NATS connections closed.")

if __name__ == "__main__":
    asyncio.run(main())
