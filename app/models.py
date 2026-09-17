import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, JSON, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base

class EvaluationRecord(Base):
    __tablename__ = "evaluations"

    # Generic Uuid compiles to native UUID on PostgreSQL and CHAR(32) on SQLite
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id = Column(String(128), index=True, nullable=False)
    turn_id = Column(String(128), index=True, nullable=False)
    bot_id = Column(String(128), index=True, nullable=False)
    
    stt_provider = Column(String(64), index=True, nullable=True)
    tts_provider = Column(String(64), index=True, nullable=True)
    
    action = Column(String(32), index=True, nullable=False)
    overall_score = Column(Float, nullable=False)
    
    audio_processing_status = Column(String(32), default="pending", index=True)
    audio_score = Column(Float, nullable=True)
    stt_score = Column(Float, nullable=True)
    tts_score = Column(Float, nullable=True)
    
    stt_latency_ms = Column(Float, nullable=True)
    tts_latency_ms = Column(Float, nullable=True)
    
    # Uses native JSONB on PostgreSQL and standard JSON on SQLite
    diagnostics = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    deep_audio_metrics = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    raw_payload = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)