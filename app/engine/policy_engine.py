from typing import Tuple, List, Optional
from app.schemas import ActionType, ComponentScore, VoiceTurnRequest

class RecoveryPolicyEngine:
    @staticmethod
    def decide(
        request: VoiceTurnRequest,
        audio_res: Optional[ComponentScore],
        stt_res: Optional[ComponentScore],
        tts_res: Optional[ComponentScore]
    ) -> Tuple[ActionType, float, List[str]]:
        diagnostics = []
        scores = []

        if audio_res:
            scores.append(audio_res.score)
            diagnostics.extend([f"[Audio] {r}" for r in audio_res.reasons])
        if stt_res:
            scores.append(stt_res.score)
            diagnostics.extend([f"[STT] {r}" for r in stt_res.reasons])
        if tts_res:
            scores.append(tts_res.score)
            diagnostics.extend([f"[TTS] {r}" for r in tts_res.reasons])

        overall_score = float(sum(scores) / len(scores)) if scores else 1.0

        # Precedence Rule 1: Audio physical-layer failure
        if audio_res and not audio_res.passed:
            diagnostics.append("Decision: Severe audio corruption or silence. Action: ask_repeat")
            return ActionType.ASK_REPEAT, overall_score, diagnostics

        # Precedence Rule 2: STT comprehension failure
        if stt_res and not stt_res.passed:
            attempt = request.stt.attempt_count if request.stt else 1
            if attempt == 1:
                diagnostics.append("Decision: First STT failure. Action: retry_stt")
                return ActionType.RETRY_STT, overall_score, diagnostics
            elif attempt == 2:
                diagnostics.append("Decision: Second STT failure. Action: switch_provider")
                return ActionType.SWITCH_PROVIDER, overall_score, diagnostics
            diagnostics.append("Decision: Exhausted STT recovery. Action: safe_fallback")
            return ActionType.SAFE_FALLBACK, overall_score, diagnostics

        # Precedence Rule 3: TTS generation failure
        if tts_res and not tts_res.passed:
            attempt = request.tts.attempt_count if request.tts else 1
            if request.tts and request.tts.status_code >= 500:
                diagnostics.append("Decision: TTS provider 5xx internal error. Action: switch_provider")
                return ActionType.SWITCH_PROVIDER, overall_score, diagnostics
            elif attempt == 1:
                diagnostics.append("Decision: TTS latency/pacing anomaly. Action: retry_tts")
                return ActionType.RETRY_TTS, overall_score, diagnostics
            diagnostics.append("Decision: Repeated TTS anomaly. Action: switch_provider")
            return ActionType.SWITCH_PROVIDER, overall_score, diagnostics

        # Precedence Rule 4: Cumulative degradation
        if overall_score < 0.65:
            diagnostics.append("Decision: Multi-signal cumulative degradation. Action: safe_fallback")
            return ActionType.SAFE_FALLBACK, overall_score, diagnostics

        diagnostics.append("Decision: All turn signals verified within acceptable bounds. Action: accept")
        return ActionType.ACCEPT, overall_score, diagnostics