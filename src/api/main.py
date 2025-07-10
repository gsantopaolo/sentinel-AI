import logging
from fastapi import FastAPI, Response, status, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
import json
from datetime import datetime

from src.lib_py.models.models import Base, Source
from src.lib_py.logic.source_logic import SourceLogic
from src.lib_py.middlewares.jetstream_publisher import JetStreamPublisher
from src.lib_py.gen_types import raw_event_pb2, new_source_pb2, removed_source_pb2
from src.lib_py.middlewares.readiness_probe import ReadinessProbe
import threading
import asyncio

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

app = FastAPI()

READINESS_TIME_OUT = int(os.getenv('API_READINESS_TIME_OUT', 500))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("❌ DATABASE_URL environment variable not set.")
    raise ValueError("DATABASE_URL environment variable not set.")

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_RECONNECT_TIME_WAIT = int(os.getenv("NATS_RECONNECT_TIME_WAIT", 10))
NATS_CONNECT_TIMEOUT = int(os.getenv("NATS_CONNECT_TIMEOUT", 10))
NATS_MAX_RECONNECT_ATTEMPTS = int(os.getenv("NATS_MAX_RECONNECT_ATTEMPTS", 60))
READINESS_TIME_OUT = int(os.getenv('API_READINESS_TIME_OUT', 500))

logger.info(f"🛠️ Starting FastAPI application with LOG_LEVEL: {log_level_str}")
logger.info(f"🗄️ Connecting to database: {DATABASE_URL.split('@')[-1]}") # Mask password
logger.info(f"✉️ Connecting to NATS: {NATS_URL}")

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create database tables (if they don't exist)
Base.metadata.create_all(bind=engine)
logger.info("✅ Database tables checked/created.")

# JetStream Publishers
raw_events_publisher: JetStreamPublisher = None
new_source_publisher: JetStreamPublisher = None
removed_source_publisher: JetStreamPublisher = None

@app.on_event("startup")
async def startup_event():
    logger.info("🔥 Application startup event triggered.")
    # Start the readiness probe server in a separate thread
    readiness_probe = ReadinessProbe(readiness_time_out=READINESS_TIME_OUT)
    readiness_probe_thread = threading.Thread(target=readiness_probe.start_server, daemon=True)
    readiness_probe_thread.start()
    logger.info("✅ Readiness probe server started.")

    global raw_events_publisher, new_source_publisher, removed_source_publisher
    raw_events_publisher = JetStreamPublisher(
        subject="raw.events",
        stream_name="raw-events-stream",
        nats_url=NATS_URL,
        nats_reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        nats_connect_timeout=NATS_CONNECT_TIMEOUT,
        nats_max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        message_type="RawEvent"
    )
    new_source_publisher = JetStreamPublisher(
        subject="new.source",
        stream_name="new-source-stream",
        nats_url=NATS_URL,
        nats_reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        nats_connect_timeout=NATS_CONNECT_TIMEOUT,
        nats_max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        message_type="NewSource"
    )
    removed_source_publisher = JetStreamPublisher(
        subject="removed.source",
        stream_name="removed-source-stream",
        nats_url=NATS_URL,
        nats_reconnect_time_wait=NATS_RECONNECT_TIME_WAIT,
        nats_connect_timeout=NATS_CONNECT_TIMEOUT,
        nats_max_reconnect_attempts=NATS_MAX_RECONNECT_ATTEMPTS,
        message_type="RemovedSource"
    )
    try:
        await raw_events_publisher.connect()
        await new_source_publisher.connect()
        await removed_source_publisher.connect()
        logger.info("✅ Connected to NATS JetStream publishers.")
    except Exception as e:
        logger.error(f"❌ Failed to connect to NATS JetStream: {e}")
        # Depending on criticality, you might want to raise the exception or handle it gracefully


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Application shutdown event triggered.")
    try:
        await raw_events_publisher.close()
        await new_source_publisher.close()
        await removed_source_publisher.close()
        logger.info("✅ Closed NATS JetStream publishers.")
    except Exception as e:
        logger.error(f"❌ Error closing NATS JetStream publishers: {e}")

# Dependency to get a database session
def get_db():
    db = SessionLocal()
    try:
        logger.debug("🐛 Database session opened.")
        yield db
    finally:
        db.close()
        logger.debug("🐛 Database session closed.")

@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_data(payload: dict):
    logger.info(f"📱 Received ingest request: {payload.get('id', 'N/A')}")
    # Assuming payload contains 'id', 'title', 'content', 'timestamp', 'source'
    raw_event = raw_event_pb2.RawEvent(
        id=payload.get("id", ""),
        title=payload.get("title", ""),
        content=payload.get("content", ""),
        timestamp=payload.get("timestamp", datetime.utcnow().isoformat()),
        source=payload.get("source", "api")
    )
    try:
        await raw_events_publisher.publish(raw_event)
        logger.info(f"✉️ Published raw event to NATS: {raw_event.id}")
    except Exception as e:
        logger.error(f"❌ Failed to publish raw event {raw_event.id} to NATS: {e}")
        raise HTTPException(status_code=500, detail="Failed to publish event to NATS")
    return {"message": "Data ingestion accepted and queued for processing"}

@app.get("/retrieve", status_code=status.HTTP_200_OK)
def retrieve_data(batch_id: str):
    logger.info(f"📱 Received retrieve request for batch_id: {batch_id}")
    return {"batch_id": batch_id, "data": "some retrieved data"}

@app.get("/news", status_code=status.HTTP_200_OK)
def get_news():
    logger.info("📱 Received request for all news.")
    return [{"id": 1, "title": "News 1"}, {"id": 2, "title": "News 2"}]

@app.get("/news/filtered", status_code=status.HTTP_200_OK)
def get_filtered_news():
    logger.info("📱 Received request for filtered news.")
    return [{"id": 1, "title": "Filtered News 1"}]

@app.get("/news/ranked", status_code=status.HTTP_200_OK)
def get_ranked_news():
    logger.info("📱 Received request for ranked news.")
    return [{"id": 1, "title": "Ranked News 1", "score": 100}]

@app.post("/news/rerank", status_code=status.HTTP_200_OK)
def rerank_news():
    logger.info("📱 Received request to rerank news.")
    return {"message": "News reranked successfully"}

@app.get("/sources", status_code=status.HTTP_200_OK)
def get_sources(db: Session = Depends(get_db)):
    logger.info("📱 Received request for all sources.")
    source_logic = SourceLogic(db)
    sources = source_logic.get_all_sources()
    logger.info(f"🗄️ Retrieved {len(sources)} sources.")
    return sources

@app.post("/sources", status_code=status.HTTP_201_CREATED)
async def create_source(name: str, type: str, config: dict = None, db: Session = Depends(get_db)):
    logger.info(f"📱 Received request to create source: {name} ({type})")
    source_logic = SourceLogic(db)
    try:
        new_source_db = source_logic.create_source(name=name, type=type, config=config)
        logger.info(f"🗄️ Source created in DB: {new_source_db.id}")
    except Exception as e:
        logger.error(f"❌ Failed to create source in DB: {e}")
        raise HTTPException(status_code=500, detail="Failed to create source in database")
    
    new_source_pb = new_source_pb2.NewSource(
        id=new_source_db.id,
        name=new_source_db.name,
        type=new_source_db.type,
        config_json=json.dumps(new_source_db.config) if new_source_db.config else "{}",
        is_active=new_source_db.is_active
    )
    try:
        await new_source_publisher.publish(new_source_pb)
        logger.info(f"✉️ Published new source event to NATS: {new_source_db.id}")
    except Exception as e:
        logger.error(f"❌ Failed to publish new source event {new_source_db.id} to NATS: {e}")
        # This is a critical error, but we might still return the DB success

    return new_source_db

@app.get("/sources/{source_id}", status_code=status.HTTP_200_OK)
def get_source_by_id(source_id: int, db: Session = Depends(get_db)):
    logger.info(f"📱 Received request for source_id: {source_id}")
    source_logic = SourceLogic(db)
    source = source_logic.get_source(source_id)
    if not source:
        logger.warning(f"⚠️ Source {source_id} not found.")
        raise HTTPException(status_code=404, detail="Source not found")
    logger.info(f"🗄️ Retrieved source: {source.name}")
    return source

@app.put("/sources/{source_id}", status_code=status.HTTP_200_OK)
def update_source(source_id: int, name: str = None, type: str = None, config: dict = None, is_active: bool = None, db: Session = Depends(get_db)):
    logger.info(f"📱 Received request to update source_id: {source_id}")
    source_logic = SourceLogic(db)
    updated_source = source_logic.update_source(source_id=source_id, name=name, type=type, config=config, is_active=is_active)
    if not updated_source:
        logger.warning(f"⚠️ Source {source_id} not found for update.")
        raise HTTPException(status_code=404, detail="Source not found")
    logger.info(f"🗄️ Source {source_id} updated in DB.")
    return updated_source

@app.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: int, db: Session = Depends(get_db)):
    logger.info(f"📱 Received request to delete source_id: {source_id}")
    source_logic = SourceLogic(db)
    if not source_logic.delete_source(source_id):
        logger.warning(f"⚠️ Source {source_id} not found for deletion.")
        raise HTTPException(status_code=404, detail="Source not found")
    logger.info(f"🗄️ Source {source_id} deleted from DB.")
    
    removed_source_pb = removed_source_pb2.RemovedSource(id=source_id)
    try:
        await removed_source_publisher.publish(removed_source_pb)
        logger.info(f"✉️ Published removed source event to NATS: {source_id}")
    except Exception as e:
        logger.error(f"❌ Failed to publish removed source event {source_id} to NATS: {e}")
        # This is a critical error, but we might still return the DB success

    return Response(status_code=status.HTTP_204_NO_CONTENT)
