import base64
import numpy as np
from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import EvaluationRecord
from app.config import settings

@celery_app.task(name="tasks.process_deep_audio", bind=True, max_retries=2)
def process_deep_audio_task(self, evaluation_id: str, pcm_base64: str, sample_rate: int):
    db = SessionLocal()
    try:
        record = db.query(EvaluationRecord).filter(EvaluationRecord.id == evaluation_id).first()
        if not record:
            return {"status": "record_not_found"}

        raw_bytes = base64.b64decode(pcm_base64)
        samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
        
        if len(samples) == 0:
            record.audio_processing_status = "failed"
            record.diagnostics.append("[Audio-Async] Payload contained 0 PCM samples")
            db.commit()
            return {"status": "empty_samples"}

        samples /= 32768.0

        clipping_ratio = float(np.sum(np.abs(samples) >= 0.99) / len(samples))

        frame_len = int(sample_rate * 0.02)
        if len(samples) < frame_len:
            frame_len = len(samples)

        num_frames = len(samples) // frame_len
        frames = samples[: num_frames * frame_len].reshape((num_frames, frame_len))
        frame_rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-9)

        noise_floor = np.percentile(frame_rms, 10)
        signal_energy = np.percentile(frame_rms, 90)
        snr_db = float(20 * np.log10((signal_energy + 1e-6) / (noise_floor + 1e-6)))
        silence_ratio = float(np.sum(frame_rms < settings.AUDIO_MIN_RMS_ENERGY) / num_frames)

        audio_score = 1.0
        reasons = []
        if snr_db < settings.AUDIO_MIN_SNR_DB:
            audio_score -= 0.4
            reasons.append(f"Low SNR: {snr_db:.1f}dB")
        if clipping_ratio > settings.AUDIO_MAX_CLIPPING_RATIO:
            audio_score -= 0.4
            reasons.append(f"Clipping: {clipping_ratio * 100:.1f}%")
        if silence_ratio > settings.AUDIO_MAX_SILENCE_RATIO:
            audio_score -= 0.5
            reasons.append(f"Excess silence: {silence_ratio * 100:.1f}%")

        audio_score = max(0.0, min(1.0, audio_score))

        record.audio_score = audio_score
        record.audio_processing_status = "completed"
        record.deep_audio_metrics = {
            "snr_db": round(snr_db, 2),
            "clipping_ratio": round(clipping_ratio, 4),
            "silence_ratio": round(silence_ratio, 4),
            "samples_processed": len(samples)
        }
        if reasons:
            record.diagnostics.extend([f"[Audio-Async] {r}" for r in reasons])

        db.commit()
        return {"status": "success", "audio_score": audio_score}
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc, countdown=3)
    finally:
        db.close()