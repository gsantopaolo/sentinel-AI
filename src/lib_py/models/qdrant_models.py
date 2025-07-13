from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class EventPayload(BaseModel):
    id: str
    title: str
    content: Optional[str] = None  # some legacy records may omit
    timestamp: datetime
    source: str
    categories: Optional[List[str]] = None
    is_relevant: Optional[bool] = None
    importance_score: Optional[float] = None
    recency_score: Optional[float] = None
    final_score: Optional[float] = None
    # Add other fields that might be stored in Qdrant payload
    # e.g., anomaly_flag: Optional[bool] = False

class RankedEvent(BaseModel):
    id: str
    title: str
    score: float
    # Add other relevant fields for ranked news display

class SearchResult(BaseModel):
    id: str
    score: float
    payload: EventPayload
