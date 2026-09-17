import redis
import numpy as np
from typing import Dict, Any, Optional
from app.config import settings

class AdaptiveThresholdService:
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_client = redis.Redis.from_url(
            redis_url or settings.REDIS_URL,
            decode_responses=True
        )
        self.window_size = 100
        self.min_samples = 15

    def _get_key(self, provider_type: str, provider: str, metric: str) -> str:
        return f"adaptive_metrics:{provider_type.lower()}:{provider.lower()}:{metric.lower()}"

    def record_metric(self, provider_type: str, provider: str, metric: str, value: float) -> None:
        if not provider or value is None:
            return
        key = self._get_key(provider_type, provider, metric)
        pipe = self.redis_client.pipeline()
        pipe.lpush(key, str(value))
        pipe.ltrim(key, 0, self.window_size - 1)
        pipe.execute()

    def get_rolling_stats(self, provider_type: str, provider: str, metric: str) -> Dict[str, float]:
        key = self._get_key(provider_type, provider, metric)
        raw_values = self.redis_client.lrange(key, 0, -1)
        if len(raw_values) < self.min_samples:
            return {"count": len(raw_values), "ready": False}

        values = np.array([float(v) for v in raw_values], dtype=np.float32)
        return {
            "count": len(values),
            "ready": True,
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "p95": float(np.percentile(values, 95))
        }

    def get_tts_latency_threshold(self, provider: str) -> Dict[str, Any]:
        stats = self.get_rolling_stats("tts", provider, "latency_ms")
        if not stats.get("ready"):
            return {
                "threshold": settings.TTS_MAX_LATENCY_MS,
                "is_adaptive": False,
                "reason": f"Insufficient baseline ({stats.get('count', 0)}/{self.min_samples})"
            }
        adaptive_limit = stats["mean"] + (2.5 * stats["std"])
        final_threshold = min(settings.TTS_MAX_LATENCY_MS, max(adaptive_limit, 400.0))
        return {
            "threshold": round(final_threshold, 2),
            "is_adaptive": True,
            "mean": round(stats["mean"], 2),
            "std": round(stats["std"], 2),
            "p95": round(stats["p95"], 2)
        }

    def get_stt_confidence_threshold(self, provider: str) -> Dict[str, Any]:
        stats = self.get_rolling_stats("stt", provider, "confidence")
        if not stats.get("ready"):
            return {
                "threshold": settings.STT_MIN_CONFIDENCE,
                "is_adaptive": False,
                "reason": f"Insufficient baseline ({stats.get('count', 0)}/{self.min_samples})"
            }
        adaptive_floor = stats["mean"] - (2.0 * stats["std"])
        final_threshold = max(0.60, min(adaptive_floor, settings.STT_MIN_CONFIDENCE))
        return {
            "threshold": round(final_threshold, 3),
            "is_adaptive": True,
            "mean": round(stats["mean"], 3),
            "std": round(stats["std"], 3)
        }

adaptive_thresholds = AdaptiveThresholdService()