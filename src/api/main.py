import os
import json
import logging
import threading
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Response, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from dotenv import load_dotenv
from src.lib_py.models.models import Base as ModelsBase, Source as SourceModel
from src.lib_py.middlewares.jetstream_publisher import JetStreamPublisher
from src.lib_py.middlewares.readiness_probe import ReadinessProbe
from src.lib_py.gen_types import raw_event_pb2, new_source_pb2, removed_source_pb2
from src.lib_py.logic.source_logic import SourceLogic
from src.lib_py.logic.qdrant_logic import QdrantLogic

# ————— Environment & Logging —————
load_dotenv()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger = logging.getLogger("sentinel-api")

# ————— Database Setup —————
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.critical("❌ DATABASE_URL must be set, exiting.")
    raise RuntimeError("DATABASE_URL not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
ModelsBase.metadata.create_all(bind=engine)
logger.info("✅ Database tables checked/created.")

# ————— FastAPI & Dependency —————
app = FastAPI()

def get_db() -> Session:
    db = SessionLocal()
    try:
        logger.debug("🐛 Opened DB session")
        yield db
    finally:
        db.close()
        logger.debug("🐛 Closed DB session")

# ————— NATS JetStream Setup —————
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_OPTIONS = dict(
    nats_url=NATS_URL,
    nats_reconnect_time_wait=int(os.getenv("NATS_RECONNECT_TIME_WAIT", 10)),
    nats_connect_timeout=int(os.getenv("NATS_CONNECT_TIMEOUT", 10)),
    nats_max_reconnect_attempts=int(os.getenv("NATS_MAX_RECONNECT_ATTEMPTS", 60)),
)

raw_events_publisher: JetStreamPublisher
new_source_publisher: JetStreamPublisher
removed_source_publisher: JetStreamPublisher
qdrant_logic: QdrantLogic

@app.on_event("startup")
async def startup_event():
    logger.info("🛠️ API starting…")

    # readiness probe
    probe = ReadinessProbe(readiness_time_out=int(os.getenv("API_READINESS_TIME_OUT", 500)))
    threading.Thread(target=probe.start_server, daemon=True).start()
    logger.info("✅ Readiness probe started.")

    # Initialize Qdrant Logic
    global qdrant_logic
    QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
    QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "news_events")
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

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
        # Depending on criticality, you might want to raise the exception or handle it gracefully

    # JetStream publishers
    global raw_events_publisher, new_source_publisher, removed_source_publisher
    raw_events_publisher = JetStreamPublisher(
        subject="raw.events",
        stream_name="raw-events-stream",
        **NATS_OPTIONS,
        message_type="RawEvent"
    )
    new_source_publisher = JetStreamPublisher(
        subject="new.source",
        stream_name="new-source-stream",
        **NATS_OPTIONS,
        message_type="NewSource"
    )
    removed_source_publisher = JetStreamPublisher(
        subject="removed.source",
        stream_name="removed-source-stream",
        **NATS_OPTIONS,
        message_type="RemovedSource"
    )

    for pub in (raw_events_publisher, new_source_publisher, removed_source_publisher):
        try:
            await pub.connect()
        except Exception as e:
            logger.error(f"❌ Publisher connect error {pub.subject}: {e}")
    logger.info("✅ NATS JetStream publishers ready.")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 API shutting down…")
    for pub in (raw_events_publisher, new_source_publisher, removed_source_publisher):
        try:
            await pub.close()
            logger.info(f"✅ Closed publisher {pub.subject}")
        except Exception as e:
            logger.error(f"❌ Error closing {pub.subject}: {e}")

# ————— Pydantic Schemas —————
class Event(BaseModel):
    id: str
    source: str
    title: str
    body: Optional[str] = None
    published_at: datetime

class SourceBase(BaseModel):
    name: str
    url: HttpUrl
    title: str
    body: Optional[str] = None
    published_at: datetime

class SourceCreate(SourceBase):
    pass

class SourceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[HttpUrl] = None
    title: Optional[str] = None
    body: Optional[str] = None
    published_at: Optional[datetime] = None
    is_active: Optional[bool] = None

class SourceRead(BaseModel):
    id: int
    name: str
    url: Optional[HttpUrl] = None
    title: Optional[str] = None
    body: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    is_active: bool

    class Config:
        orm_mode = True

# ————— Ingest Endpoint —————
@app.post("/ingest", status_code=status.HTTP_200_OK)
async def ingest_data(events: List[Event]):
    logger.info(f"📱 Received ingest batch of {len(events)} events")
    for ev in events:
        try:
            # Basic validation
            if not all(k in ev for k in ['id', 'source', 'title', 'published_at']):
                logger.warning(f"Skipping event due to missing required fields: {ev.get('id', 'N/A')}")
                continue

            logger.info(f"Processing event: {ev['id']}")

            # Publish to NATS for further processing by the 'filter' service
            raw = raw_event_pb2.RawEvent(
                id=ev['id'],
                source=ev['source'],
                title=ev['title'],
                content=ev.get('content', ev.get('body', '')), # Handle both 'content' and 'body'
                timestamp=ev['published_at']
            )
            
            # The publisher is now responsible for sending the message
            await raw_events_publisher.publish(raw)
            logger.info(f"✉️ Published raw event: {ev['id']}")

        except Exception as e:
            logger.error(f"❌ Error processing event {ev.get('id', 'N/A')}: {e}")
            # Continue with next event even if one fails
            continue

    return {"message": f"Successfully processed and published {len(events)} events."}

# ————— Helper for Model Conversion —————
def source_to_read_model(source: SourceModel) -> dict:
    config = source.config or {}
    published_at_str = config.get("published_at")
    published_at_dt = datetime.fromisoformat(published_at_str) if published_at_str else None
    
    url_str = config.get("url")
    
    return {
        "id": source.id,
        "name": source.name,
        "url": url_str,
        "title": config.get("title"),
        "body": config.get("body"),
        "published_at": published_at_dt,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "is_active": source.is_active,
    }

# ————— Sources CRUD —————
@app.get("/sources", response_model=List[SourceRead])
def list_sources(db: Session = Depends(get_db)):
    logger.info("📱 GET /sources")
    sources = SourceLogic(db).get_all_sources()
    logger.info(f"🗄️ Returning {len(sources)} sources")
    return [source_to_read_model(s) for s in sources]

@app.get("/sources/{source_id}", response_model=SourceRead)
def read_source(source_id: int, db: Session = Depends(get_db)):
    logger.info(f"📱 GET /sources/{source_id}")
    src = SourceLogic(db).get_source(source_id)
    if not src:
        logger.warning(f"⚠️ Source {source_id} not found")
        raise HTTPException(status_code=404, detail="Source not found")
    logger.info(f"🗄️ Found source id={src.id}")
    return source_to_read_model(src)

@app.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    logger.info(f"📱 Creating source {payload.name}")
    config = {
        "url": str(payload.url),
        "title": payload.title,
        "body": payload.body,
        "published_at": payload.published_at.isoformat() if payload.published_at else None
    }
    src = SourceLogic(db).create_source(
        name=payload.name,
        type="feed",  # Assuming a default type as it's not in payload
        config=config
    )
    logger.info(f"🗄️ Created source id={src.id}")
    msg = new_source_pb2.NewSource(
        id=src.id,
        name=src.name,
        type=src.type,
        config_json=json.dumps(src.config) if src.config else "{}",
        is_active=src.is_active,
    )
    try:
        await new_source_publisher.publish(msg)
        logger.info(f"✉️ Published new.source event id={src.id}")
    except Exception as e:
        logger.error(f"❌ Publishing new.source id={src.id} failed: {e}")
    return source_to_read_model(src)

@app.put("/sources/{source_id}", response_model=SourceRead)
def update_source(source_id: int, payload: SourceUpdate, db: Session = Depends(get_db)):
    logger.info(f"📱 PUT /sources/{source_id}")
    existing = SourceLogic(db).get_source(source_id)
    if not existing:
        logger.warning(f"⚠️ Source {source_id} not found for update")
        raise HTTPException(status_code=404, detail="Source not found")

    update_data = payload.dict(exclude_unset=True)
    config = existing.config or {}

    if 'url' in update_data:
        config['url'] = str(update_data['url'])
    if 'title' in update_data:
        config['title'] = update_data['title']
    if 'body' in update_data:
        config['body'] = update_data['body']
    if 'published_at' in update_data:
        config['published_at'] = update_data['published_at'].isoformat() if update_data['published_at'] else None

    updated = SourceLogic(db).update_source(
        source_id=source_id,
        name=payload.name or existing.name,
        config=config,
        is_active=payload.is_active if payload.is_active is not None else existing.is_active,
    )
    logger.info(f"🗄️ Updated source id={updated.id}")
    return source_to_read_model(updated)

@app.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: int, db: Session = Depends(get_db)):
    logger.info(f"📱 DELETE /sources/{source_id}")
    if not SourceLogic(db).delete_source(source_id):
        logger.warning(f"⚠️ Source {source_id} not found for deletion")
        raise HTTPException(status_code=404, detail="Source not found")
    logger.info(f"🗄️ Deleted source id={source_id}")
    msg = removed_source_pb2.RemovedSource(id=source_id)
    try:
        await removed_source_publisher.publish(msg)
        logger.info(f"✉️ Published removed.source event id={source_id}")
    except Exception as e:
        logger.error(f"❌ Publishing removed.source id={source_id} failed: {e}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/retrieve", status_code=status.HTTP_200_OK)
async def retrieve_data(batch_id: str):
    logger.info(f"📱 Received retrieve request for batch_id: {batch_id}")
    event_data = await qdrant_logic.retrieve_event_by_id(batch_id)
    if not event_data:
        raise HTTPException(status_code=404, detail="Event not found in Qdrant")
    return event_data
