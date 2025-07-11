import asyncio
import logging
import os
import threading
from dotenv import load_dotenv
from nats.aio.msg import Msg
import yaml
import openai
import anthropic

from src.lib_py.middlewares.jetstream_event_subscriber import JetStreamEventSubscriber
from src.lib_py.middlewares.jetstream_publisher import JetStreamPublisher
from src.lib_py.middlewares.readiness_probe import ReadinessProbe
from src.lib_py.gen_types import raw_event_pb2, filtered_event_pb2 # filtered_event_pb2 needs to be created
from src.lib_py.logic.qdrant_logic import QdrantLogic
from src.lib_py.models.qdrant_models import EventPayload

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
# todo: explain in the documentation the flexibility of havinf filter yaml
with open('filter_config.yaml', 'r') as f:
    config = yaml.safe_load(f)


FILTERING_RULES = config['filtering_rules']

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_RECONNECT_TIME_WAIT = int(os.getenv("NATS_RECONNECT_TIME_WAIT", 10))
NATS_CONNECT_TIMEOUT = int(os.getenv("NATS_CONNECT_TIMEOUT", 10))
NATS_MAX_RECONNECT_ATTEMPTS = int(os.getenv("NATS_MAX_RECONNECT_ATTEMPTS", 60))
READINESS_TIME_OUT = int(os.getenv('FILTER_READINESS_TIME_OUT', 500))

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "news_events")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")



# NATS Stream configuration
RAW_EVENTS_STREAM_NAME = "raw-events-stream"
RAW_EVENTS_SUBJECT = "raw.events"
FILTERED_EVENTS_STREAM_NAME = "filtered-events-stream"
FILTERED_EVENTS_SUBJECT = "filtered.events"

# JetStream Publisher
filtered_events_publisher: JetStreamPublisher = None
qdrant_logic: QdrantLogic = None

class LLMClient:
    def __init__(self, provider: str, model_name: str, api_key: str):
        self.provider = provider
        self.model_name = model_name
        self.api_key = api_key
        if self.provider == "openai":
            openai.api_key = self.api_key
        elif self.provider == "anthropic":
            self.client = anthropic.Anthropic(api_key=self.api_key)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    async def get_completion(self, prompt: str) -> str:
        if self.provider == "openai":
            response = openai.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content
        elif self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        return ""

llm_client: LLMClient = None

async def raw_event_handler(msg: Msg):
    readiness_probe.update_last_seen()
    try:
        raw_event = raw_event_pb2.RawEvent()
        raw_event.ParseFromString(msg.data)
        logger.info(f"✉️ Received raw event: ID={raw_event.id}, Title='{raw_event.title}'")

        # 1. Apply relevance filter using LLM
        relevance_prompt = FILTERING_RULES['relevance_prompt'].format(article_content=raw_event.content)
        relevance_response = await llm_client.get_completion(relevance_prompt)
        logger.info(f"LLM Relevance for '{raw_event.id}': {relevance_response}")

        is_relevant = False
        if "RELEVANT" in relevance_response.upper():
            is_relevant = True
        elif "POTENTIALLY_RELEVANT" in relevance_response.upper():
            # Further logic for potentially relevant, for now treat as relevant
            is_relevant = True
        
        if not is_relevant:
            logger.info(f"🗑️ Event '{raw_event.id}' deemed irrelevant. Skipping.")
            await msg.ack()
            return

        # 2. Categorize using LLM
        category_prompt = FILTERING_RULES['category_prompt'].format(article_content=raw_event.content)
        category_response = await llm_client.get_completion(category_prompt)
        logger.info(f"LLM Categories for '{raw_event.id}': {category_response}")
        categories = [c.strip() for c in category_response.split(',') if c.strip()]

        # 3. Generate embeddings and persist to Qdrant
        event_payload_data = {
            "id": raw_event.id,
            "title": raw_event.title,
            "content": raw_event.content,
            "timestamp": raw_event.timestamp,
            "source": raw_event.source,
            "categories": categories, # Add LLM-derived categories
            "is_relevant": is_relevant # Add LLM-derived relevance
        }
        # Convert timestamp string to datetime object for Pydantic model validation if needed
        # For Qdrant, it's stored as part of payload, so string is fine.
        
        await qdrant_logic.upsert_event(event_payload_data)
        logger.info(f"🗄️ Event '{raw_event.id}' persisted to Qdrant.")

        # 4. Publish filtered event
        filtered_event = filtered_event_pb2.FilteredEvent(
            id=raw_event.id,
            title=raw_event.title,
            timestamp=raw_event.timestamp,
            source=raw_event.source,
            categories=categories, # Pass categories in filtered event
            is_relevant=is_relevant
        )
        await filtered_events_publisher.publish(filtered_event)
        logger.info(f"✉️ Published filtered event '{raw_event.id}' to filtered.events.")

        await msg.ack()
        logger.info(f"✅ Acknowledged raw event: {raw_event.id}")
    except Exception as e:
        logger.error(f"❌ Error processing raw event: {e}")
        await msg.nak() # Negative acknowledgment

async def main():
    logger.info("🛠️ Filter service starting...")

    # Start the readiness probe server in a separate thread
    readiness_probe = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    readiness_probe_thread = threading.Thread(target=readiness_probe.start_server, daemon=True)
    readiness_probe_thread.start()
    logger.info("✅ Readiness probe server started.")

    # Initialize LLM Client
    global llm_client
    provider = os.getenv("LLM_PROVIDER")
    model_name = os.getenv("LLM_MODEL_NAME")
    api_key = None
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
    elif provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        logger.error(f"❌ LLM API key not set for {provider}. Please set the appropriate API key in .env")
        return # Exit if API key is missing
    llm_client = LLMClient(provider, model_name, api_key)
    logger.info(f"✅ LLM Client initialized with provider: {provider} and model: {model_name}")

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

    # Initialize filtered events publisher
    global filtered_events_publisher
    filtered_events_publisher = JetStreamPublisher(
        subject=FILTERED_EVENTS_SUBJECT,
        stream_name=FILTERED_EVENTS_STREAM_NAME,
        nats_url=NATS_URL,
        nats_reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        nats_connect_timeout=NATS_CONNECT_TIMEOUT,
        nats_max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        message_type="FilteredEvent"
    )
    try:
        await filtered_events_publisher.connect()
        logger.info("✅ Filtered events publisher connected to NATS.")
    except Exception as e:
        logger.error(f"❌ Failed to connect filtered events publisher to NATS: {e}")
        return # Exit if NATS connection fails

    # Initialize raw.events subscriber
    raw_events_subscriber = JetStreamEventSubscriber(
        nats_url=NATS_URL,
        stream_name=RAW_EVENTS_STREAM_NAME,
        subject=RAW_EVENTS_SUBJECT,
        connect_timeout=NATS_CONNECT_TIMEOUT,
        reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        ack_wait=60, # seconds
        max_deliver=3,
        proto_message_type=raw_event_pb2.RawEvent
    )
    raw_events_subscriber.set_event_handler(raw_event_handler)

    # Connect and subscribe to NATS
    try:
        await raw_events_subscriber.connect_and_subscribe()
        logger.info(f"✅ Subscribed to {RAW_EVENTS_SUBJECT}")
    except Exception as e:
        logger.error(f"❌ Failed to connect or subscribe to NATS: {e}")
        return # Exit if NATS connection fails

    try:
        # Keep the main loop running indefinitely
        while True:
            readiness_probe.update_last_seen()
            await asyncio.sleep(10) # Update readiness every 10 seconds
    except asyncio.CancelledError:
        logger.info("🛑 Filter service received shutdown signal.")
    finally:
        await raw_events_subscriber.close()
        await filtered_events_publisher.close()
        logger.info("✅ NATS connections closed.")

if __name__ == "__main__":
    asyncio.run(main())
