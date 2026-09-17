import uuid
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime

class ActionType(str, Enum):
    ACCEPT = "accept"
    RETRY_TTS = "retry_tts"
    RETRY_STT = "retry_stt"
    SWITCH_PROVIDER = "switch_provider"
    ASK_REPEAT = "ask_repeat"
    SAFE_FALLBACK = "safe_fallback"

class AudioSignalPayload(BaseModel):
    duration_ms: float
    sample_rate: int = 16000
    pcm_base64: Optional[str] = None
    snr_db: Optional[float] = None
    clipping_ratio: Optional[float] = None
    silence_ratio: Optional[float] = None

class STTPayload(BaseModel):
    provider: str
    transcript: str
    confidence: float = Field(ge=0.0, le=1.0)
    latency_ms: float
    detected_language: str = "en"
    attempt_count: int = 1

class TTSPayload(BaseModel):
    provider: str
    input_text: str
    audio_duration_ms: float
    latency_ms: float
    status_code: int = 200
    attempt_count: int = 1

class VoiceTurnRequest(BaseModel):
    call_id: str
    turn_id: str
    bot_id: str
    audio: Optional[AudioSignalPayload] = None
    stt: Optional[STTPayload] = None
    tts: Optional[TTSPayload] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ComponentScore(BaseModel):
    score: float
    passed: bool
    reasons: List[str]

class EvaluationResponse(BaseModel):
    evaluation_id: uuid.UUID
    call_id: str
    turn_id: str
    bot_id: str
    action: ActionType
    overall_score: float
    audio_eval: Optional[ComponentScore]
    stt_eval: Optional[ComponentScore]
    tts_eval: Optional[ComponentScore]
    diagnostics: List[str]
    created_at: datetime

    class Config:
        from_attributes = True

class AggregateStatsResponse(BaseModel):
    total_evaluations: int
    average_quality_score: float
    failure_rate: float
    retry_rate: float
    action_breakdown: Dict[str, int]
    provider_latencies: Dict[str, Dict[str, float]]