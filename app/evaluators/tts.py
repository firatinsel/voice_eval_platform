from app.schemas import TTSPayload, ComponentScore
from app.config import settings
from app.services.adaptive_thresholds import adaptive_thresholds

class TTSEvaluator:
    @staticmethod
    def evaluate(payload: TTSPayload) -> ComponentScore:
        reasons = []
        score = 1.0

        if payload.status_code != 200:
            return ComponentScore(
                score=0.0,
                passed=False,
                reasons=[f"Provider error status: {payload.status_code}"]
            )

        dyn_lat = adaptive_thresholds.get_tts_latency_threshold(payload.provider)
        active_max_latency = dyn_lat["threshold"]

        # Latency evaluation: breach carries a base penalty of 0.35 so score < 0.70
        if payload.latency_ms > active_max_latency:
            excess = payload.latency_ms - active_max_latency
            deduction = 0.35 + min(0.65, (excess / 1000.0) * 0.4)
            score -= deduction
            if dyn_lat["is_adaptive"]:
                reasons.append(
                    f"TTS latency {payload.latency_ms:.0f}ms breached provider '{payload.provider}' "
                    f"adaptive threshold {active_max_latency:.0f}ms (avg: {dyn_lat['mean']:.0f}ms)"
                )
            else:
                reasons.append(f"TTS latency high: {payload.latency_ms:.0f}ms > {active_max_latency:.0f}ms")

        # Pacing evaluation
        text_len = len(payload.input_text.strip())
        if text_len > 0 and payload.audio_duration_ms > 0:
            duration_sec = payload.audio_duration_ms / 1000.0
            chars_per_sec = text_len / duration_sec
            if chars_per_sec < settings.TTS_MIN_CHARS_PER_SEC:
                score -= 0.4
                reasons.append(f"TTS audio unnaturally stretched: {chars_per_sec:.1f} chars/sec")
            elif chars_per_sec > settings.TTS_MAX_CHARS_PER_SEC:
                score -= 0.5
                reasons.append(f"TTS audio likely truncated: {chars_per_sec:.1f} chars/sec")

        score = max(0.0, min(1.0, score))
        return ComponentScore(score=score, passed=score >= 0.70, reasons=reasons)