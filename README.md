# Voice Quality Evaluation and Intelligent Recovery Service

A standalone, production-ready AI backend service that evaluates conversational voice interaction turns (Audio, STT, and TTS) and executes deterministic, explainable recovery actions (`accept`, `retry_stt`, `retry_tts`, `switch_provider`, `ask_repeat`, `safe_fallback`).

The platform integrates dual-path execution: an ultra-low latency synchronous HTTP evaluation path alongside an asynchronous Celery/Redis background worker for intensive digital signal processing (DSP). It also features provider-specific adaptive threshold tracking in Redis, bilingual linguistic heuristics (English & Turkish), Prometheus telemetry, and a reporting dashboard built in Django.

---

## Key Features

* **Voice-Turn Evaluation API:** REST API accepting audio payloads, transcripts, and synthesis metrics without requiring live telephony connections.


* **Acoustic Signal Processing (Audio):** Zero-dependency wave extraction supporting 8, 16, 24, and 32-bit PCM audio; analyzes Signal-to-Noise Ratio (SNR), frame-based RMS energy, clipping distortion, and dead-air silence.


* **Comprehension Quality Engine (STT):** Evaluates recognition confidence, character pacing, repetitive token loops, and hallucination phrases tailored to English and Turkish voice models.


* **Synthesis Health Engine (TTS):** Detects dropped/truncated sentences, unnatural speech stretching, high synthesis latency, and upstream provider 5xx outages.


* **Deterministic Policy Engine:** An explainable, rule-based arbitration engine mapping degraded component signals into clear recovery actions.


* **Provider-Adaptive Thresholds:** Dynamic baselines calculated via Redis sliding windows ($\mu \pm 2.5\sigma$), catching provider-specific anomalies before they breach static global limits.


* **Persistence & Observability:** PostgreSQL persistence via SQLAlchemy, Prometheus `/metrics` scraping, and a reporting UI and management interface in Django.



---

## System Architecture

```text
                           [ Voice Gateway / Client ]
                                        │
             ┌──────────────────────────┴──────────────────────────┐
             │ POST /turn (JSON / Base64)                          │ POST /upload-audio (WAV)
             ▼                                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FastAPI Engine                                 │
│                                                                             │
│  1. Fast Audio Check ────► 2. STT Evaluator ────► 3. TTS Evaluator          │
│     (SNR/Clipping metadata)   (Confidence / Loops)   (Pacing / Truncation)  │
│                                        │                                    │
│                                        ▼                                    │
│                          ┌───────────────────────────┐                      │
│                          │  Recovery Policy Engine   │                      │
│                          └─────────────┬─────────────┘                      │
│                                        │ Generates Action                   │
│                                        ▼                                    │
│                        [ Synchronous Response <20ms ]                       │
└──────────────┬─────────────────────────┬────────────────────────────┬───────┘
               │ Dispatch Raw PCM        │ Telemetry Feedback         │ Read/Write
               ▼                         ▼                            ▼
   ┌───────────────────────┐ ┌───────────────────────┐ ┌──────────────────────┐
   │     Celery Worker     │ │      Redis Cache      │ │ PostgreSQL Database  │
   │  - Deep RMS Framing   │ │  - Adaptive Latencies │ │  - Turn Records      │
   │  - SNR Percentiles    │ │  - Confidence Windows │ │  - JSONB Diagnostics │
   │  - Clipping Profiling │ │  - Celery Broker      │ │  - Analytics Stats   │
   └───────────┬───────────┘ └───────────────────────┘ └──────────┬───────────┘
               │                                                  │
               └─────────────── Updates Record ───────────────────┘
                                                                  │
                                                                  ▼
                                                      ┌──────────────────────┐
                                                      │   Django Dashboard   │
                                                      │  - Quality Reports   │
                                                      │  - Admin Inspection  │
                                                      └──────────────────────┘

```

### Recovery Action Precedence

The policy engine enforces a deterministic failure hierarchy:

1. **Physical Layer (`ask_repeat`):** Severe acoustic corruption (low SNR, clipping, excessive silence) cannot be fixed by switching or retrying software models. The user must be asked to repeat.


2. **Comprehension Layer (`retry_stt` / `switch_provider`):** Low confidence or hallucination loops trigger a retry on attempt 1, and escalate to a secondary provider on attempt 2.


3. **Synthesis Layer (`retry_tts` / `switch_provider`):** Latency spikes or audio truncation trigger a retry on attempt 1, while provider 5xx errors trigger an immediate provider switch.


4. **Degradation Fallback (`safe_fallback`):** Repeated failures across components route the interaction to safe fallback or human transfer.


5. **Nominal (`accept`):** All components operate within quality parameters.



---

## Project Structure

```text
voice_eval_platform/
├── app/
│   ├── config.py                 # Pydantic settings & static thresholds
│   ├── database.py               # SQLAlchemy database engine and connection pool
│   ├── models.py                 # PostgreSQL-compatible ORM models (UUID, JSONB)
│   ├── schemas.py                # Pydantic v2 validation contracts
│   ├── celery_app.py             # Celery worker configuration
│   ├── tasks.py                  # Background audio signal processing task
│   ├── main.py                   # FastAPI application routes
│   ├── services/
│   │   └── adaptive_thresholds.py# Dynamic Redis sliding-window metric service
│   ├── evaluators/
│   │   ├── audio.py              # WAV parsing, SNR, clipping, and RMS framing
│   │   ├── stt.py                # STT confidence, loops, and TR/EN hallucination filters
│   │   └── tts.py                # Speech pacing, latency limits, and truncation detection
│   └── engine/
│       └── policy_engine.py      # Explainable recovery arbitration engine
├── dashboard_app/
│   ├── manage.py                 # Django management CLI
│   ├── dashboard_project/        # Django project settings and routing
│   └── reports/                  # Unmanaged model definitions, admin, and report views
├── fixtures/                     # Test WAV audio files generated by script
├── scripts/
│   └── generate_fixtures.py      # Synthetic test audio fixture generator
├── tests/
│   └── test_service.py           # Pytest unit and integration test suite
├── Dockerfile                    # Container definition
├── docker-compose.yml            # Multi-service composition file
└── requirements.txt              # Production and testing dependencies

```

---

## Quickstart & Installation

### Prerequisites

* Docker and Docker Compose (V2)


* Python 3.11+ (if running outside Docker)

### 1. Launch via Docker Compose

Clone the repository and build the container stack:

```bash
docker compose up --build

```

The stack provisions the following services:

| Service | Internal Port | External Host Port | Description |
| --- | --- | --- | --- |
| **FastAPI API** | `8000` | `http://localhost:8000` | Turn evaluation engine and docs

 |
| **Django Dashboard** | `8001` | `http://localhost:8001` | Admin and analytics reporting

 |
| **PostgreSQL** | `5432` | `localhost:5432` | Persistent relational storage

 |
| **Redis** | `6379` | `localhost:6379` | Queue broker and adaptive sliding windows

 |
| **Celery Worker** | — | — | Background DSP audio worker

 |

### 2. Create Django Admin User

To access the Django admin console:

```bash
docker compose exec dashboard python dashboard_app/manage.py createsuperuser

```

### 3. Generate Audio Test Fixtures

To generate synthetic `.wav` test files (`clean_tone.wav`, `clipped_distortion.wav`, `silent_dead_air.wav`) in the `fixtures/` directory:

```bash
docker compose exec api python scripts/generate_fixtures.py

```

---

## API Endpoints & Usage

### 1. Evaluate Turn via JSON Payload

`POST /api/v1/evaluations/turn`

Evaluates turn metadata directly. If `audio.pcm_base64` is provided, deep DSP runs asynchronously via Celery.

```bash
curl -X POST http://localhost:8000/api/v1/evaluations/turn \
  -H "Content-Type: application/json" \
  -d '{
    "call_id": "call_101",
    "turn_id": "turn_01",
    "bot_id": "support_bot",
    "audio": {
      "duration_ms": 2500,
      "snr_db": 22.5,
      "clipping_ratio": 0.001,
      "silence_ratio": 0.10
    },
    "stt": {
      "provider": "deepgram",
      "transcript": "I need to check my flight status.",
      "confidence": 0.95,
      "latency_ms": 210,
      "detected_language": "en"
    },
    "tts": {
      "provider": "elevenlabs",
      "input_text": "Your flight is on schedule for departure.",
      "audio_duration_ms": 2400,
      "latency_ms": 340,
      "status_code": 200
    }
  }'

```

**Response (`201 Created`):**

```json
{
  "evaluation_id": "c71109a9-7e3e-462f-a9ce-c5b6b15822f3",
  "call_id": "call_101",
  "turn_id": "turn_01",
  "bot_id": "support_bot",
  "action": "accept",
  "overall_score": 1.0,
  "audio_eval": { "score": 1.0, "passed": true, "reasons": [] },
  "stt_eval": { "score": 1.0, "passed": true, "reasons": [] },
  "tts_eval": { "score": 1.0, "passed": true, "reasons": [] },
  "diagnostics": [
    "Decision: All turn signals verified within acceptable bounds. Action: accept"
  ],
  "created_at": "2026-09-17T00:00:00Z"
}

```

---

### 2. Direct WAV Audio File Upload

`POST /api/v1/evaluations/turn/upload-audio`

Accepts physical `.wav` files via `multipart/form-data` and calculates SNR, clipping, and RMS metrics directly.

```bash
curl -X POST http://localhost:8000/api/v1/evaluations/turn/upload-audio \
  -F "audio_file=@fixtures/clipped_distortion.wav" \
  -F 'turn_data={
    "call_id": "call_102",
    "turn_id": "turn_01",
    "bot_id": "support_bot",
    "stt": {
      "provider": "deepgram",
      "transcript": "Hello",
      "confidence": 0.85,
      "latency_ms": 200
    }
  }'

```

**Response (`201 Created`):**

```json
{
  "evaluation_id": "f5f19cc4-7e8e-49b0-96f8-4b77d6ba47ea",
  "call_id": "call_102",
  "turn_id": "turn_01",
  "bot_id": "support_bot",
  "action": "ask_repeat",
  "overall_score": 0.60,
  "audio_eval": {
    "score": 0.60,
    "passed": false,
    "reasons": ["Clipping: 28.4%"]
  },
  "stt_eval": { "score": 1.0, "passed": true, "reasons": [] },
  "tts_eval": null,
  "diagnostics": [
    "[Audio] Clipping: 28.4%",
    "Decision: Severe audio corruption or silence. Action: ask_repeat"
  ],
  "created_at": "2026-09-17T00:01:00Z"
}

```

---

### 3. Retrieve Single Evaluation by ID

`GET /api/v1/evaluations/{evaluation_id}`

Retrieves complete turn diagnostics, raw inputs, and sub-component evaluations.

---

### 4. Filter Historical Evaluations

`GET /api/v1/evaluations`

Query parameters:

* `call_id`: Filter by call session


* `bot_id`: Filter by bot agent


* `provider`: Filter by STT/TTS provider


* `action`: Filter by action (`accept`, `retry_stt`, `retry_tts`, `switch_provider`, `ask_repeat`, `safe_fallback`)


* `from_date` / `to_date`: Time window filter


* `limit`: Page size constraint



---

### 5. Aggregate Quality Statistics

`GET /api/v1/analytics/stats`

Returns platform-wide or bot-specific failure rates, retry rates, average quality scores, and per-provider latency averages.

```json
{
  "total_evaluations": 84,
  "average_quality_score": 0.885,
  "failure_rate": 0.047,
  "retry_rate": 0.071,
  "action_breakdown": {
    "accept": 74,
    "retry_stt": 4,
    "retry_tts": 2,
    "ask_repeat": 3,
    "switch_provider": 1
  },
  "provider_latencies": {
    "deepgram": { "stt_avg_latency_ms": 210.4 },
    "elevenlabs": { "tts_avg_latency_ms": 350.8 }
  }
}

```

---

## Web Interfaces & Dashboards

* **FastAPI Swagger Documentation:** `http://localhost:8000/docs`

* **Django Quality Report UI:** `http://localhost:8001/report/`

* **Django Admin Panel:** `http://localhost:8001/admin/`

* **Prometheus Metrics Scraper:** `http://localhost:8000/metrics`


---

## Running Automated Tests

The test suite covers nominal acceptance, language-specific hallucination detection, and Redis-backed adaptive threshold learning.

Run the tests inside the container:

```bash
docker compose exec api python -m pytest tests/ -v

```

Expected output:

```text
tests/test_service.py::test_nominal_turn_accepted PASSED                     [ 33%]
tests/test_service.py::test_turkish_hallucination_detection PASSED           [ 66%]
tests/test_service.py::test_adaptive_threshold_learning_and_anomaly PASSED [100%]

============================== 3 passed in 1.15s ==============================

```

---

## Production Roadmap & Improvements

1. **Streaming Audio Evaluation:** Extend the physical audio evaluator to ingest chunked WebRTC/RTP audio frames in real time over WebSockets rather than awaiting turn completion.
2. **Forced Alignment for Phoneme Verification:** Integrate CTC-forced alignment (e.g., Wav2Vec2) to compare synthesised audio directly against text scripts, catching subtle dropped syllables or hallucinated words.
3. **Dynamic Database Partitioning:** Partition the PostgreSQL `evaluations` table by `created_at` (monthly or weekly) to sustain high write volumes and query performance over millions of records.
4. **Distributed Tracing:** Add OpenTelemetry tracing context across incoming API requests, Celery background tasks, and outbound provider API calls to provide distributed latency flame graphs.