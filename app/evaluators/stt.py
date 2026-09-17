from collections import Counter
import re
from typing import Optional
from app.schemas import STTPayload, ComponentScore
from app.config import settings
from app.services.adaptive_thresholds import adaptive_thresholds

class STTEvaluator:
    @staticmethod
    def _detect_repetition_loop(transcript: str) -> bool:
        """Detects pathological token repetition loops in a language-agnostic manner."""
        tokens = re.findall(r"\w+", transcript.lower())
        if len(tokens) < 6:
            return False

        # Flag turns where a single word comprises >= 50% of the entire utterance
        counts = Counter(tokens)
        most_common_word, count = counts.most_common(1)[0]
        if count >= 4 and (count / len(tokens)) >= 0.50:
            return True

        # Check for repeating bigram loops (e.g., "please wait please wait please wait")
        bigrams = [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]
        bigram_counts = Counter(bigrams)
        if bigram_counts:
            _, bg_count = bigram_counts.most_common(1)[0]
            if bg_count >= 3:
                return True

        return False

    @classmethod
    def evaluate(cls, payload: STTPayload, audio_duration_ms: Optional[float] = None) -> ComponentScore:
        reasons = []
        score = 1.0

        dyn_conf = adaptive_thresholds.get_stt_confidence_threshold(payload.provider)
        active_min_conf = dyn_conf["threshold"]

        # 1. Confidence evaluation (Static vs Adaptive Baseline)
        if payload.confidence < active_min_conf:
            deficit = active_min_conf - payload.confidence
            score -= 0.35 + min(0.65, deficit * 1.5)
            if dyn_conf["is_adaptive"]:
                reasons.append(
                    f"Confidence {payload.confidence:.2f} below provider '{payload.provider}' "
                    f"adaptive threshold {active_min_conf:.2f} (avg: {dyn_conf['mean']:.2f})"
                )
            else:
                reasons.append(f"Confidence low: {payload.confidence:.2f} < {active_min_conf:.2f}")

        # 2. Token repetition loop detection
        if cls._detect_repetition_loop(payload.transcript):
            score -= 0.50
            reasons.append("Repetitive token loop detected in transcription")

        # 3. Speech pacing sanity check
        duration_ms = audio_duration_ms
        if duration_ms and duration_ms > 0:
            duration_sec = duration_ms / 1000.0
            chars_per_sec = len(payload.transcript.strip()) / duration_sec
            if chars_per_sec > settings.STT_MAX_CHARS_PER_SEC:
                score -= 0.40
                reasons.append(f"Implausible speech rate: {chars_per_sec:.1f} chars/sec")

        score = max(0.0, min(1.0, score))
        return ComponentScore(score=score, passed=score >= 0.70, reasons=reasons)