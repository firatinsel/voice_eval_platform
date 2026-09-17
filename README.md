```markdown
# Voice AI Quality Evaluation & Intelligent Recovery Microservice

A production-ready microservice designed to evaluate conversational Voice AI turns (Audio, STT, TTS) and trigger deterministic, explainable recovery actions (`accept`, `retry_stt`, `retry_tts`, `switch_provider`, `ask_repeat`, `safe_fallback`).

The platform implements a dual-path execution model: an ultra-low latency synchronous HTTP evaluation path alongside an asynchronous Celery and Redis worker for deep digital signal processing (DSP). It includes sliding-window adaptive baselines in Redis, Prometheus metrics, and a PostgreSQL database paired with a Django monitoring dashboard.

---

## System Architecture

```text
                             [ Telephony Gateway / Voice Client ]
                                               │
             ┌─────────────────────────────────┴─────────────────────────────────┐
             │ POST /turn (JSON / Base64)                                        │ POST /turn/upload-audio (Multipart)
             ▼                                                                   ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                         FastAPI Microservice                                           │
│                                                                                                        │
│  1. Audio Signal Check ─────────► 2. STT Evaluator ─────────► 3. TTS Evaluator                         │
│     - SNR, Clipping, Silence         - Adaptive Confidence       - Latency vs Adaptive Threshold       │
│                                      - Pacing Sanity             - Pacing (Truncation / Stretch)       │
│                                      - Repetition Loops          - Upstream 5xx Error Flags            │
│                                               │                                                        │
│                                               ▼                                                        │
│                                 ┌───────────────────────────┐                                          │
│                                 │   Recovery Policy Engine  │                                          │
│                                 └─────────────┬─────────────┘                                          │
│                                               │ Produces Action & Diagnostics                          │
│                                               ▼                                                        │
│                           [ Synchronous Response < 20ms Target ]                                       │
└───────────────────────┬───────────────────────┬──────────────────────────────┬─────────────────────────┘
                        │ Raw PCM Base64        │ Telemetry                    │ Read / Write
                        ▼                       ▼                              ▼
            ┌──────────────────────┐ ┌────────────────────┐       ┌──────────────────────────┐
            │    Celery Worker     │ │    Redis Cache     │       │   PostgreSQL Database    │
            │  - 20ms Frame RMS    │ │  - Sliding Windows │       │  - evaluations table     │
            │  - SNR Percentiles   │ │  - Celery Broker   │       │  - JSONB Diagnostics     │
            │  - DB Status Update  │ └────────────────────┘       │  - JSONB Metrics         │
            └──────────┬───────────┘                              └─────────────┬────────────┘
                       │                                                        │ Read Only
                       └──────────────── Updates Record ────────────────────────┘ (managed = False)
                                                                                ▼
                                                                  ┌──────────────────────────┐
                                                                  │     Django Dashboard     │
                                                                  │  - /report/ Quality View │
                                                                  │  - /admin/ Turn Auditor  │
                                                                  └──────────────────────────┘

```

### Dual-Path Execution Pipeline

* **Fast Synchronous Path (< 20ms):** Telephony gateways require sub-millisecond evaluation to preserve conversational cadence. The HTTP worker evaluates pre-computed acoustic metrics, STT confidence, TTS latency, and repetition loops, returning recovery directives immediately.
* **Deep Asynchronous Path (Celery + Redis):** When raw linear PCM audio bytes are ingested, the synchronous path issues a provisional action and offloads deep signal processing to Celery. Celery handles frame-based RMS energy calculations, percentile SNR estimations, and updates the PostgreSQL record asynchronously.

---

## Core Evaluators & DSP Logic

### 1. Audio Evaluator (`app/evaluators/audio.py`)

Parses and evaluates uncompressed audio waveforms using Python's standard `wave` module and NumPy (zero external binary dependencies):

* **Multi-Format Bit-Depth Parsing:** Reads 8-bit unsigned, 16-bit signed, 24-bit studio (converted via 32-bit zero-padding), and 32-bit signed linear PCM. Multi-channel audio is automatically downmixed to a normalized mono floating-point array in `[-1.0, 1.0]`.
* **Clipping Ratio:** Quantifies the proportion of samples reaching peak amplitude (>= 0.99). Ratios exceeding 2% flag microphone distortion or gain overdrive.
* **Windowed RMS & SNR:** Slices audio into 20ms sliding windows. Measures the 10th percentile energy floor (ambient noise) against the 90th percentile signal peak to compute the Signal-to-Noise Ratio:
```text
SNR_dB = 20 * log10((Signal_RMS + 1e-6) / (Noise_RMS + 1e-6))

```


Turns falling below 12 dB are penalized.
* **Dead-Air Silence:** Measures the percentage of frames falling below minimum speech threshold energy (< 0.015 RMS). Ratios exceeding 70% flag dead air or disconnected microphones.

### 2. Speech-to-Text (STT) Evaluator (`app/evaluators/stt.py`)

* **Dynamic Confidence Tracking:** Compares model confidence against real-time, provider-specific baselines stored in Redis.
* **Language-Agnostic Repetition Loops:** Uses token and bigram frequency distribution analysis (`Counter`) to flag decoding hallucinations where models loop identical phrases.
* **Speech Rate Plausibility:** Validates the character-per-second rate against the physical audio duration (> 35 chars/sec indicates hallucination or audio duration mismatch).

### 3. Text-to-Speech (TTS) Evaluator (`app/evaluators/tts.py`)

* **Upstream Outage Detection:** Intercepts non-200 HTTP status codes from downstream synthesis APIs (e.g., 500, 502, 503).
* **Adaptive Latency Anomaly:** Evaluates synthesis response times against dynamic sliding-window thresholds to flag degrading providers before total timeout.
* **Truncation & Stretching:** Calculates speech pacing against returned audio duration:
* `> 26.0 chars/sec`: Flags dropped clauses or prematurely cut audio.
* `< 8.0 chars/sec`: Flags unnatural speech stretching or network buffer stutter.



---

## Recovery Policy Engine (`app/engine/policy_engine.py`)

A deterministic, rule-based decision matrix mapping composite degradation into explainable recovery instructions:

| Priority | Failure Mode | Trigger Condition | Action | Operational Intent |
| --- | --- | --- | --- | --- |
| **1** | **Acoustic Failure** | Low SNR (< 12dB), clipping (> 2%), or silence (> 70%) | `ask_repeat` | Physical input corrupted. Retrying software models is futile; prompt the human caller to repeat. |
| **2** | **STT Failure** | Low confidence or token repetition loop | `retry_stt` *(Attempt 1)*<br>

<br>`switch_provider` *(Attempt 2)* | Re-run recognition on attempt 1. Escalate to secondary ASR provider on repeat failure. |
| **3** | **TTS 5xx Outage** | Provider returns HTTP 500, 502, 503, 504 | `switch_provider` | Downstream synthesis service is unavailable. Failover immediately. |
| **4** | **TTS Pacing/Latency** | Truncated speech, severe stretching, or latency spike | `retry_tts` *(Attempt 1)*<br>

<br>`switch_provider` *(Attempt 2)* | Retry synthesis once. Fall back to backup TTS provider if degradation persists. |
| **5** | **Compound Degradation** | Overall quality score < 0.65 across multiple signals | `safe_fallback` | Turn quality is severely compromised. Route to human representative or safe canned prompt. |
| **6** | **Nominal Turn** | All active components pass quality thresholds | `accept` | Signals verified healthy; proceed with standard conversation flow. |

---

## Adaptive Threshold Service (`app/services/adaptive_thresholds.py`)

Rather than relying strictly on brittle static thresholds, the service tracks provider performance dynamically using Redis lists:

* **Sliding Window:** Maintains an atomic rolling buffer of the last 100 turns in Redis (`LPUSH` / `LTRIM`) for each metric per provider.
* **Cold-Start Protection:** Defaults to conservative static thresholds for the first 15 requests while gathering baseline data.
* **Statistical Anomaly Bounds:** Dynamically calculates:
```text
Threshold_latency = min(Static_Max, mean + 2.5 * std_dev)
Threshold_confidence = max(Static_Min, mean - 2.0 * std_dev)

```


* This allows the engine to flag a normally fast provider (e.g., Cartesia averaging 180ms) when it spikes to 650ms, even though 650ms is well below the global fallback ceiling (1800ms).

---

## Data Layer & Django Integration

* **Primary Engine (FastAPI / SQLAlchemy):** Writes evaluation records with native `UUID` primary keys, numeric latencies, scores, and semi-structured `JSONB` columns (`diagnostics`, `deep_audio_metrics`, `raw_payload`).
* **Administrative & Reporting UI (Django):** Connects to the same PostgreSQL database with `managed = False` on models. Django leaves table creation and schema migrations to SQLAlchemy/Alembic while exposing:
* `/report/`: Real-time quality health dashboard displaying total turns, failure rates, retry distributions, and provider latency benchmarks.
* `/admin/`: Filterable record inspection view equipped with color-coded status badges, search bars, and full diagnostic logs.



---

## API Reference

### 1. Ingest Turn via JSON Payload

`POST /api/v1/evaluations/turn`

Evaluates telephony metadata and pre-computed signals, or offloads raw Base64 PCM audio to Celery.

```bash
curl -X POST http://localhost:8000/api/v1/evaluations/turn \
  -H "Content-Type: application/json" \
  -d '{
    "call_id": "call_98124",
    "turn_id": "turn_001",
    "bot_id": "customer_service",
    "audio": {
      "duration_ms": 2200,
      "snr_db": 21.4,
      "clipping_ratio": 0.001,
      "silence_ratio": 0.12
    },
    "stt": {
      "provider": "deepgram",
      "transcript": "I would like to modify my flight booking.",
      "confidence": 0.96,
      "latency_ms": 210,
      "attempt_count": 1
    },
    "tts": {
      "provider": "elevenlabs",
      "input_text": "Please provide your confirmation code.",
      "audio_duration_ms": 2100,
      "latency_ms": 340,
      "status_code": 200,
      "attempt_count": 1
    }
  }'

```

---

### 2. Ingest Turn with Audio File Upload & Form Fields

`POST /api/v1/evaluations/turn/upload-audio`

Accepts physical `.wav` files alongside discrete form parameters (rendered as individual fields in Swagger UI).

```bash
curl -X POST http://localhost:8000/api/v1/evaluations/turn/upload-audio \
  -F "audio_file=@fixtures/clean_tone.wav" \
  -F "call_id=call_demo_01" \
  -F "turn_id=turn_01" \
  -F "bot_id=banking_assistant" \
  -F "stt_provider=deepgram" \
  -F "stt_transcript=Hello" \
  -F "stt_confidence=0.95" \
  -F "stt_latency_ms=210"

```

---

### 3. Query Single Evaluation by ID

`GET /api/v1/evaluations/{evaluation_id}`

Returns complete evaluation records including sub-scores, full diagnostics trace, and raw payload data.

---

### 4. Filter Historical Evaluation Records

`GET /api/v1/evaluations`

Supported Query Filters: `call_id`, `bot_id`, `provider`, `action`, `from_date`, `to_date`, `limit` (max 200).

---

### 5. Platform Quality Analytics

`GET /api/v1/analytics/stats`

Aggregates failure rates, retry rates, quality distributions, and provider-specific average latencies directly in PostgreSQL:

```json
{
  "total_evaluations": 142,
  "average_quality_score": 0.892,
  "failure_rate": 0.042,
  "retry_rate": 0.070,
  "action_breakdown": {
    "accept": 126,
    "retry_stt": 6,
    "retry_tts": 4,
    "ask_repeat": 4,
    "switch_provider": 2
  },
  "provider_latencies": {
    "deepgram": { "stt_avg_latency_ms": 218.3 },
    "elevenlabs": { "tts_avg_latency_ms": 362.1 }
  }
}

```

---

## Project Structure

```text
voice_eval_platform/
├── app/
│   ├── config.py                 # Pydantic settings & threshold limits
│   ├── database.py               # SQLAlchemy connection engine & sessions
│   ├── models.py                 # PostgreSQL-compatible ORM models (UUID, JSONB)
│   ├── schemas.py                # Pydantic validation contracts
│   ├── celery_app.py             # Celery distributed worker config
│   ├── tasks.py                  # Background DSP audio processing task
│   ├── main.py                   # FastAPI application routes
│   ├── services/
│   │   └── adaptive_thresholds.py# Redis sliding-window metric baseline service
│   ├── evaluators/
│   │   ├── audio.py              # WAV parsing, SNR, clipping, RMS framing
│   │   ├── stt.py                # STT confidence, pacing, and repetition loop checks
│   │   └── tts.py                # Pacing sanity, latency limits, truncation detection
│   └── engine/
│       └── policy_engine.py      # Rule-based recovery arbitration engine
├── dashboard_app/
│   ├── manage.py                 # Django management CLI
│   ├── dashboard_project/        # Django project settings and routing
│   └── reports/                  # Unmanaged models, admin, and report views
├── fixtures/                     # Synthetic test audio files
├── scripts/
│   └── generate_fixtures.py      # Synthetic test audio fixture generator
├── tests/
│   └── test_service.py           # Automated test suite (Pytest)
├── Dockerfile                    # Container build configuration
├── docker-compose.yml            # Multi-container orchestration
└── requirements.txt              # Production dependencies

```

---

## Deployment & Setup

### 1. Launch Services

```bash
docker compose up --build

```

Container Port Mappings:

* **FastAPI Microservice:** `http://localhost:8000` (Swagger UI at `/docs`)
* **Django Quality Dashboard:** `http://localhost:8001/report/`
* **Django Admin Panel:** `http://localhost:8001/admin/`
* **Prometheus Metrics:** `http://localhost:8000/metrics`
* **PostgreSQL:** `localhost:5432`
* **Redis:** `localhost:6379`

### 2. Create Django Admin Superuser

```bash
docker compose exec dashboard python dashboard_app/manage.py createsuperuser

```

### 3. Generate Audio Test Fixtures

Creates synthetic test WAV files simulating nominal audio, clipping overdrive, and dead air:

```bash
docker compose exec api python scripts/generate_fixtures.py

```

---

## Automated Testing

Execute the test suite inside the API container:

```bash
docker compose exec api python -m pytest tests/ -v

```

Verified Test Scenarios:

* `test_nominal_turn_accepted`: Validates clean turns receiving `accept` with a 1.0 quality score.
* `test_stt_repetition_loop_detection`: Validates language-agnostic detection of repetitive ASR hallucination loops triggering `retry_stt`.
* `test_adaptive_threshold_learning_and_anomaly`: Verifies Redis-backed sliding window baseline training and dynamic anomaly penalties.

