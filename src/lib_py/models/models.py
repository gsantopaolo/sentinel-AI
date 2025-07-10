from pydantic import BaseModel, PositiveFloat
from typing import Tuple
from sqlalchemy import create_engine, Column, Integer, String, JSON, DateTime, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base, Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime

# Base class for declarative models
Base = declarative_base()

class Item(BaseModel):
    project_id: int
    tile_id: str
    image_url: str
    target_coordinates: Tuple[float, float]  # Tuple for x and y as integers
    scale: PositiveFloat  # Ensures scale is a positive float
    signalr_connection_id: str

class Source(Base):
    __tablename__ = 'sources'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True) # Use JSON for PostgreSQL JSONB type
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<Source(id={self.id}, name='{self.name}', type='{self.type}')>"