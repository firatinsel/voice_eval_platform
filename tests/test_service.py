import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from app.main import app
from app.database import Base, get_db
from app.services.adaptive_thresholds import AdaptiveThresholdService

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

TEST_DB_URL = "sqlite:///./test_voice_eval.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="session", autouse=True)
def init_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)

def override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_db
client = TestClient(app)

def test_nominal_turn_accepted():
    payload = {
        "call_id": "call_norm_101",
        "turn_id": "turn_01",
        "bot_id": "bot_assistant",
        "audio": {"duration_ms": 2000, "snr_db": 22.0, "clipping_ratio": 0.0, "silence_ratio": 0.1},
        "stt": {"provider": "deepgram", "transcript": "I need help with my reservation", "confidence": 0.96, "latency_ms": 240},
        "tts": {"provider": "elevenlabs", "input_text": "I can assist with that.", "audio_duration_ms": 1500, "latency_ms": 380, "status_code": 200}
    }
    res = client.post("/api/v1/evaluations/turn", json=payload)
    assert res.status_code == 201
    assert res.json()["action"] == "accept"

def test_stt_repetition_loop_detection():
    payload = {
        "call_id": "call_loop_102",
        "turn_id": "turn_01",
        "bot_id": "bot_support",
        "stt": {
            "provider": "whisper",
            "transcript": "please wait please wait please wait please wait",
            "confidence": 0.88,
            "latency_ms": 350,
            "attempt_count": 1
        }
    }
    res = client.post("/api/v1/evaluations/turn", json=payload)
    assert res.status_code == 201
    assert res.json()["action"] == "retry_stt"
    assert any("Repetitive token loop" in d for d in res.json()["diagnostics"])

def test_adaptive_threshold_learning_and_anomaly():
    adaptive = AdaptiveThresholdService()
    provider = "cartesia_stream"

    for key in adaptive.redis_client.keys(f"adaptive_metrics:tts:{provider}:*"):
        adaptive.redis_client.delete(key)

    for sample in [170, 185, 180, 190, 175] * 4:
        adaptive.record_metric("tts", provider, "latency_ms", sample)

    payload = {
        "call_id": "call_adapt_103",
        "turn_id": "turn_01",
        "bot_id": "bot_fast",
        "tts": {
            "provider": provider,
            "input_text": "Account updated.",
            "audio_duration_ms": 1200,
            "latency_ms": 650,
            "status_code": 200,
            "attempt_count": 1
        }
    }
    res = client.post("/api/v1/evaluations/turn", json=payload)
    assert res.status_code == 201
    assert res.json()["action"] == "retry_tts"
    assert any("adaptive threshold" in d for d in res.json()["diagnostics"])