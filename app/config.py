import os
from pydantic_settings import BaseSettings
from typing import Dict, List

class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://postgres:postgrespassword@localhost:5432/voice_eval_db"
    )
    REDIS_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

    # Audio Signal Thresholds
    AUDIO_MIN_SNR_DB: float = 12.0
    AUDIO_MAX_CLIPPING_RATIO: float = 0.02
    AUDIO_MIN_RMS_ENERGY: float = 0.015
    AUDIO_MAX_SILENCE_RATIO: float = 0.70

    # STT Thresholds
    STT_MIN_CONFIDENCE: float = 0.72
    STT_MAX_REPETITION_COUNT: int = 3
    STT_MIN_CHARS_PER_SEC: float = 2.0
    STT_MAX_CHARS_PER_SEC: float = 35.0

    # TTS Thresholds
    TTS_MAX_LATENCY_MS: float = 1800.0
    TTS_MIN_CHARS_PER_SEC: float = 8.0
    TTS_MAX_CHARS_PER_SEC: float = 26.0

    # Turkish & English Hallucination / Loop Triggers
    HALLUCINATION_PATTERNS: Dict[str, List[str]] = {
        "en": ["thank you for watching", "subscribe to my channel", "subtitles by", "bye."],
        "tr": ["abone olmayı unutmayın", "altyazı", "izlediğiniz için teşekkürler", "görüşmek üzere."]
    }

    class Config:
        env_prefix = "VOICE_EVAL_"

settings = Settings()