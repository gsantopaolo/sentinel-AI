import asyncio
import logging
import os
import threading
from typing import Dict, Any, Optional, List
import yaml
from dotenv import load_dotenv
from nats.aio.msg import Msg
import openai
import anthropic
from datetime import datetime

# Add type stubs for openai and anthropic if needed
try:
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
except ImportError:
    openai_client = None

try:
    from anthropic import Anthropic
    anthropic_client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
except ImportError:
    anthropic_client = None

from src.lib_py.middlewares.jetstream_event_subscriber import JetStreamEventSubscriber
from src.lib_py.middlewares.readiness_probe import ReadinessProbe
from src.lib_py.gen_types import filtered_event_pb2
from src.lib_py.logic.qdrant_logic import QdrantLogic

# Load environment variables
load_dotenv()

# Configure logging
log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
log_format = os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.basicConfig(level=log_level, format=log_format)
logger = logging.getLogger(__name__)

# Load configuration from YAML
with open('src/inspector/inspector_config.yaml', 'r') as f:
    config = yaml.safe_load(f)

ANOMALY_DETECTORS = config['anomaly_detectors']

# Environment variables
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_RECONNECT_TIME_WAIT = int(os.getenv("NATS_RECONNECT_TIME_WAIT", 10))
NATS_CONNECT_TIMEOUT = int(os.getenv("NATS_CONNECT_TIMEOUT", 10))
NATS_MAX_RECONNECT_ATTEMPTS = int(os.getenv("NATS_RECONNECT_ATTEMPTS", 60))
READINESS_TIME_OUT = int(os.getenv('INSPECTOR_READINESS_TIME_OUT', 500))

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "news_events")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

# NATS Stream configuration
FILTERED_EVENTS_STREAM_NAME = "filtered-events-stream"
FILTERED_EVENTS_SUBJECT = "filtered.events"

qdrant_logic: QdrantLogic = None
llm_client = None

class LLMClient:
    def __init__(self, provider: str, model_name: str, api_key: str):
        self.provider = provider
        self.model_name = model_name
        self.api_key = api_key
        self.client = None
        
        if not self.api_key:
            raise ValueError(f"API key is required for {provider}")
            
        if self.provider == "openai":
            if openai_client is None:
                raise ImportError("OpenAI client is not available. Install with: pip install openai")
            self.client = openai_client
        elif self.provider == "anthropic":
            if anthropic_client is None:
                raise ImportError("Anthropic client is not available. Install with: pip install anthropic")
            self.client = anthropic_client
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    async def get_completion(self, prompt: str) -> str:
        try:
            if self.provider == "openai":
                response = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content
            elif self.provider == "anthropic":
                response = await asyncio.to_thread(
                    self.client.messages.create,
                    model=self.model_name,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text
        except Exception as e:
            logger.error(f"Error getting completion from {self.provider}: {str(e)}")
            raise
            
        return ""

async def check_for_anomalies(event_data: dict) -> bool:
    """Applies anomaly detection rules to an event."""
    for detector in ANOMALY_DETECTORS:
        detector_type = detector.get('type')
        parameters = detector.get('parameters')

        if detector_type == 'keyword_match':
            for keyword in parameters.get('keywords', []):
                if keyword.lower() in event_data.get('content', '').lower():
                    logger.warning(f"Anomaly detected in event {event_data['id']}: Keyword '{keyword}' found.")
                    return True

        elif detector_type == 'content_length':
            content_len = len(event_data.get('content', ''))
            min_len = parameters.get('min_length', 0)
            max_len = parameters.get('max_length', float('inf'))
            if not min_len <= content_len <= max_len:
                logger.warning(f"Anomaly detected in event {event_data['id']}: Content length {content_len} is outside the range [{min_len}, {max_len}].")
                return True

        elif detector_type == 'missing_fields':
            for field in parameters.get('fields', []):
                if not event_data.get(field):
                    logger.warning(f"Anomaly detected in event {event_data['id']}: Missing required field '{field}'.")
                    return True

        elif detector_type == 'llm_anomaly_detector':
            if llm_client:
                prompt = parameters.get('prompt', '').format(article_content=event_data.get('content', ''))
                try:
                    llm_response = await llm_client.get_completion(prompt)
                    if "ANOMALY" in llm_response.upper():
                        logger.warning(f"Anomaly detected in event {event_data['id']}: LLM flagged as anomalous.")
                        return True
                except Exception as e:
                    logger.error(f"Error with LLM anomaly detection for event {event_data['id']}: {e}")
            else:
                logger.warning("LLM client not initialized for llm_anomaly_detector.")

    return False

async def filtered_event_handler(msg: Msg):
    readiness_probe.update_last_seen()
    try:
        filtered_event = filtered_event_pb2.FilteredEvent()
        filtered_event.ParseFromString(msg.data)
        logger.info(f"✉️ Received filtered event: ID={filtered_event.id}, Title='{filtered_event.title}'")

        event_data = await qdrant_logic.retrieve_event_by_id(filtered_event.id)
        if not event_data:
            logger.warning(f"⚠️ Event '{filtered_event.id}' not found in Qdrant. Cannot perform inspection.")
            await msg.ack()
            return

        is_anomaly = await check_for_anomalies(event_data)

        if is_anomaly:
            event_data['is_anomaly'] = True
            await qdrant_logic.upsert_event(event_data)
            logger.info(f"🚩 Event '{filtered_event.id}' flagged as an anomaly in Qdrant.")

        await msg.ack()
        logger.info(f"✅ Acknowledged filtered event: {filtered_event.id}")
    except Exception as e:
        logger.error(f"❌ Error processing filtered event: {e}")
        await msg.nak()  # Negative acknowledgment

async def main():
    logger.info("🛠️ Inspector service starting...")

    readiness_probe = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    readiness_probe_thread = threading.Thread(target=readiness_probe.start_server, daemon=True)
    readiness_probe_thread.start()
    logger.info("✅ Readiness probe server started.")

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
        return

    # Initialize LLM Client if an LLM detector is configured
    global llm_client
    for detector in ANOMALY_DETECTORS:
        if detector.get('type') == 'llm_anomaly_detector':
            params = detector.get('parameters', {})
            provider = os.getenv("LLM_PROVIDER")
            model_name = os.getenv("LLM_MODEL_NAME")
            
            # Determine which API key to use based on provider
            api_key = None
            if provider == "openai":
                api_key = os.getenv("OPENAI_API_KEY")
            elif provider == "anthropic":
                api_key = os.getenv("ANTHROPIC_API_KEY")
            
            if not api_key:
                logger.error(f"❌ LLM API key not set for {provider}. Please set the appropriate API key in .env")
                return # Exit if API key is missing
            llm_client = LLMClient(provider, model_name, api_key)
            logger.info(f"✅ LLM Client initialized for anomaly detection with provider: {provider} and model: {model_name}")
            break # Only one LLM client needed

    filtered_events_subscriber = JetStreamEventSubscriber(
        nats_url=NATS_URL,
        stream_name=FILTERED_EVENTS_STREAM_NAME,
        subject=FILTERED_EVENTS_SUBJECT,
        connect_timeout=NATS_CONNECT_TIMEOUT,
        reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        ack_wait=60,  # seconds
        max_deliver=3,
        proto_message_type=filtered_event_pb2.FilteredEvent
    )
    filtered_events_subscriber.set_event_handler(filtered_event_handler)

    try:
        await filtered_events_subscriber.connect_and_subscribe()
        logger.info(f"✅ Subscribed to {FILTERED_EVENTS_SUBJECT}")
    except Exception as e:
        logger.error(f"❌ Failed to connect or subscribe to NATS: {e}")
        return

    try:
        while True:
            readiness_probe.update_last_seen()
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        logger.info("🛑 Inspector service received shutdown signal.")
    finally:
        await filtered_events_subscriber.close()
        logger.info("✅ NATS connections closed.")

if __name__ == "__main__":
    asyncio.run(main())
