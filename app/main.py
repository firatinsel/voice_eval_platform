from fastapi import FastAPI, Depends, Query, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import datetime
from prometheus_fastapi_instrumentator import Instrumentator
from app.database import engine, Base, get_db
from app.models import EvaluationRecord
from app.schemas import VoiceTurnRequest, EvaluationResponse, AggregateStatsResponse, ActionType, ComponentScore, STTPayload, TTSPayload
from app.evaluators.audio import AudioEvaluator
from app.evaluators.stt import STTEvaluator
from app.evaluators.tts import TTSEvaluator
from app.engine.policy_engine import RecoveryPolicyEngine
from app.tasks import process_deep_audio_task
from app.services.adaptive_thresholds import adaptive_thresholds



Base.metadata.create_all(bind=engine)

app = FastAPI(title="Voice Quality Evaluation and Intelligent Recovery Service", version="1.0.0")

# Prometheus instrumentation on /metrics
Instrumentator().instrument(app).expose(app)

@app.post("/api/v1/evaluations/turn", response_model=EvaluationResponse, status_code=status.HTTP_201_CREATED)
def evaluate_voice_turn(turn: VoiceTurnRequest, db: Session = Depends(get_db)):
    pcm_present = bool(turn.audio and turn.audio.pcm_base64)
    
    # 1. Fast path audio evaluation
    if turn.audio and (turn.audio.snr_db is not None or turn.audio.silence_ratio is not None):
        audio_res = AudioEvaluator.evaluate(turn.audio)
    else:
        audio_res = ComponentScore(score=1.0, passed=True, reasons=["PCM passed to background worker"])

    # 2. STT & TTS evaluations
    audio_dur = turn.audio.duration_ms if turn.audio else 0.0
    stt_res = STTEvaluator.evaluate(turn.stt, audio_duration_ms=audio_dur) if turn.stt else None
    tts_res = TTSEvaluator.evaluate(turn.tts) if turn.tts else None

    # 3. Decision engine
    action, overall_score, diagnostics = RecoveryPolicyEngine.decide(turn, audio_res, stt_res, tts_res)

    # 4. Record adaptive telemetry
    if turn.stt:
        adaptive_thresholds.record_metric("stt", turn.stt.provider, "confidence", turn.stt.confidence)
    if turn.tts and turn.tts.status_code == 200:
        adaptive_thresholds.record_metric("tts", turn.tts.provider, "latency_ms", turn.tts.latency_ms)

    # 5. Persist turn record
    record = EvaluationRecord(
        call_id=turn.call_id,
        turn_id=turn.turn_id,
        bot_id=turn.bot_id,
        stt_provider=turn.stt.provider if turn.stt else None,
        tts_provider=turn.tts.provider if turn.tts else None,
        action=action.value,
        overall_score=overall_score,
        audio_processing_status="pending" if pcm_present else "skipped",
        audio_score=audio_res.score if audio_res else None,
        stt_score=stt_res.score if stt_res else None,
        tts_score=tts_res.score if tts_res else None,
        stt_latency_ms=turn.stt.latency_ms if turn.stt else None,
        tts_latency_ms=turn.tts.latency_ms if turn.tts else None,
        diagnostics=diagnostics,
        raw_payload=turn.model_dump(exclude={"audio": {"pcm_base64"}})
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 6. Dispatch async deep audio evaluation if raw PCM is present
    if pcm_present:
        process_deep_audio_task.delay(str(record.id), turn.audio.pcm_base64, turn.audio.sample_rate)

    return EvaluationResponse(
        evaluation_id=record.id,
        call_id=record.call_id,
        turn_id=record.turn_id,
        bot_id=record.bot_id,
        action=action,
        overall_score=overall_score,
        audio_eval=audio_res,
        stt_eval=stt_res,
        tts_eval=tts_res,
        diagnostics=diagnostics,
        created_at=record.created_at
    )

@app.get("/api/v1/evaluations/{evaluation_id}", response_model=EvaluationResponse)
def get_evaluation(evaluation_id: str, db: Session = Depends(get_db)):
    record = db.query(EvaluationRecord).filter(EvaluationRecord.id == evaluation_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Evaluation record not found")
    return EvaluationResponse(
        evaluation_id=record.id,
        call_id=record.call_id,
        turn_id=record.turn_id,
        bot_id=record.bot_id,
        action=ActionType(record.action),
        overall_score=record.overall_score,
        audio_eval={"score": record.audio_score or 0.0, "passed": (record.audio_score or 0) >= 0.7, "reasons": []},
        stt_eval={"score": record.stt_score or 0.0, "passed": (record.stt_score or 0) >= 0.7, "reasons": []},
        tts_eval={"score": record.tts_score or 0.0, "passed": (record.tts_score or 0) >= 0.7, "reasons": []},
        diagnostics=record.diagnostics,
        created_at=record.created_at
    )

@app.post(
    "/api/v1/evaluations/turn/upload-audio",
    response_model=EvaluationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Evaluate Turn with Audio File and Discrete Parameters"
)
async def evaluate_turn_with_audio_file(
    audio_file: UploadFile = File(..., description="Binary .wav sound file"),
    call_id: str = Form(..., description="Call session identifier"),
    turn_id: str = Form(..., description="Turn sequence identifier"),
    bot_id: str = Form(..., description="Bot / Agent identifier"),
    stt_provider: Optional[str] = Form(None, description="STT Provider (e.g. deepgram, whisper)"),
    stt_transcript: Optional[str] = Form(None, description="Recognized speech transcript"),
    stt_confidence: Optional[float] = Form(None, description="STT model confidence (0.0 to 1.0)"),
    stt_latency_ms: Optional[float] = Form(None, description="STT request latency in milliseconds"),
    tts_provider: Optional[str] = Form(None, description="TTS Provider (e.g. elevenlabs, cartesia)"),
    tts_input_text: Optional[str] = Form(None, description="Text synthesized into speech"),
    tts_audio_duration_ms: Optional[float] = Form(None, description="Synthesized audio duration in milliseconds"),
    tts_latency_ms: Optional[float] = Form(None, description="TTS synthesis latency in milliseconds"),
    tts_status_code: Optional[int] = Form(200, description="HTTP status code from TTS provider"),
    db: Session = Depends(get_db)
):
    # 1. Decode WAV sound file
    file_bytes = await audio_file.read()
    try:
        samples, sample_rate, duration_ms = AudioEvaluator.extract_pcm_from_wav(file_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read WAV sound file: {str(exc)}")

    # 2. Construct domain sub-payloads from discrete form fields
    stt_payload = None
    if stt_provider and stt_transcript:
        stt_payload = STTPayload(
            provider=stt_provider,
            transcript=stt_transcript,
            confidence=stt_confidence if stt_confidence is not None else 1.0,
            latency_ms=stt_latency_ms if stt_latency_ms is not None else 0.0,
            attempt_count=1
        )

    tts_payload = None
    if tts_provider and tts_input_text:
        tts_payload = TTSPayload(
            provider=tts_provider,
            input_text=tts_input_text,
            audio_duration_ms=tts_audio_duration_ms if tts_audio_duration_ms is not None else 0.0,
            latency_ms=tts_latency_ms if tts_latency_ms is not None else 0.0,
            status_code=tts_status_code if tts_status_code is not None else 200,
            attempt_count=1
        )

    turn = VoiceTurnRequest(
        call_id=call_id,
        turn_id=turn_id,
        bot_id=bot_id,
        stt=stt_payload,
        tts=tts_payload
    )

    # 3. Evaluate waveform acoustics and component models
    audio_res, metrics = AudioEvaluator.evaluate_waveform(samples, sample_rate)
    stt_res = STTEvaluator.evaluate(turn.stt, audio_duration_ms=duration_ms) if turn.stt else None
    tts_res = TTSEvaluator.evaluate(turn.tts) if turn.tts else None

    # 4. Determine recovery policy
    action, overall_score, diagnostics = RecoveryPolicyEngine.decide(turn, audio_res, stt_res, tts_res)

    # 5. Persist record to PostgreSQL
    record = EvaluationRecord(
        call_id=turn.call_id,
        turn_id=turn.turn_id,
        bot_id=turn.bot_id,
        stt_provider=turn.stt.provider if turn.stt else None,
        tts_provider=turn.tts.provider if turn.tts else None,
        action=action.value,
        overall_score=overall_score,
        audio_processing_status="completed",
        audio_score=audio_res.score,
        stt_score=stt_res.score if stt_res else None,
        tts_score=tts_res.score if tts_res else None,
        stt_latency_ms=turn.stt.latency_ms if turn.stt else None,
        tts_latency_ms=turn.tts.latency_ms if turn.tts else None,
        diagnostics=diagnostics,
        deep_audio_metrics=metrics,
        raw_payload=turn.model_dump()
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return EvaluationResponse(
        evaluation_id=record.id,
        call_id=record.call_id,
        turn_id=record.turn_id,
        bot_id=record.bot_id,
        action=action,
        overall_score=overall_score,
        audio_eval=audio_res,
        stt_eval=stt_res,
        tts_eval=tts_res,
        diagnostics=diagnostics,
        created_at=record.created_at
    )

@app.get("/api/v1/evaluations", response_model=List[EvaluationResponse])
def list_evaluations(
    call_id: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    action: Optional[ActionType] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    q = db.query(EvaluationRecord)
    if call_id:
        q = q.filter(EvaluationRecord.call_id == call_id)
    if bot_id:
        q = q.filter(EvaluationRecord.bot_id == bot_id)
    if provider:
        q = q.filter((EvaluationRecord.stt_provider == provider) | (EvaluationRecord.tts_provider == provider))
    if action:
        q = q.filter(EvaluationRecord.action == action.value)
    if from_date:
        q = q.filter(EvaluationRecord.created_at >= from_date)
    if to_date:
        q = q.filter(EvaluationRecord.created_at <= to_date)
    records = q.order_by(EvaluationRecord.created_at.desc()).limit(limit).all()
    return [
        EvaluationResponse(
            evaluation_id=r.id,
            call_id=r.call_id,
            turn_id=r.turn_id,
            bot_id=r.bot_id,
            action=ActionType(r.action),
            overall_score=r.overall_score,
            audio_eval=None,
            stt_eval=None,
            tts_eval=None,
            diagnostics=r.diagnostics,
            created_at=r.created_at
        ) for r in records
    ]

@app.get("/api/v1/analytics/stats", response_model=AggregateStatsResponse)
def get_aggregate_stats(
    bot_id: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    db: Session = Depends(get_db)
):
    q = db.query(EvaluationRecord)
    if bot_id:
        q = q.filter(EvaluationRecord.bot_id == bot_id)
    if from_date:
        q = q.filter(EvaluationRecord.created_at >= from_date)
    if to_date:
        q = q.filter(EvaluationRecord.created_at <= to_date)

    total = q.count()
    if total == 0:
        return AggregateStatsResponse(
            total_evaluations=0,
            average_quality_score=0.0,
            failure_rate=0.0,
            retry_rate=0.0,
            action_breakdown={},
            provider_latencies={}
        )

    avg_score = q.with_entities(func.avg(EvaluationRecord.overall_score)).scalar() or 0.0
    actions = q.with_entities(EvaluationRecord.action, func.count(EvaluationRecord.id)).group_by(EvaluationRecord.action).all()
    action_map = {act: count for act, count in actions}

    retry_count = action_map.get(ActionType.RETRY_STT.value, 0) + action_map.get(ActionType.RETRY_TTS.value, 0)
    failure_count = (
        action_map.get(ActionType.SAFE_FALLBACK.value, 0)
        + action_map.get(ActionType.SWITCH_PROVIDER.value, 0)
        + action_map.get(ActionType.ASK_REPEAT.value, 0)
    )

    stt_latencies = q.filter(EvaluationRecord.stt_provider.isnot(None))\
                     .with_entities(EvaluationRecord.stt_provider, func.avg(EvaluationRecord.stt_latency_ms))\
                     .group_by(EvaluationRecord.stt_provider).all()
    tts_latencies = q.filter(EvaluationRecord.tts_provider.isnot(None))\
                     .with_entities(EvaluationRecord.tts_provider, func.avg(EvaluationRecord.tts_latency_ms))\
                     .group_by(EvaluationRecord.tts_provider).all()

    provider_latency_map = {}
    for prov, avg_lat in stt_latencies:
        provider_latency_map.setdefault(prov, {})["stt_avg_latency_ms"] = round(avg_lat or 0.0, 2)
    for prov, avg_lat in tts_latencies:
        provider_latency_map.setdefault(prov, {})["tts_avg_latency_ms"] = round(avg_lat or 0.0, 2)

    return AggregateStatsResponse(
        total_evaluations=total,
        average_quality_score=round(avg_score, 3),
        failure_rate=round(failure_count / total, 3),
        retry_rate=round(retry_count / total, 3),
        action_breakdown=action_map,
        provider_latencies=provider_latency_map
    )