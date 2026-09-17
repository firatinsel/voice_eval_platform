import io
import wave
import numpy as np
from typing import Tuple
from app.schemas import AudioSignalPayload, ComponentScore
from app.config import settings

class AudioEvaluator:
    @staticmethod
    def extract_pcm_from_wav(file_bytes: bytes) -> Tuple[np.ndarray, int, float]:
        """
        Parses 8-bit, 16-bit, 24-bit, and 32-bit standard PCM WAV files.
        Returns: (normalized_samples, sample_rate, duration_ms)
        """
        with wave.open(io.BytesIO(file_bytes), "rb") as wf:
            num_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            num_frames = wf.getnframes()
            raw_frames = wf.readframes(num_frames)

            # 1. Parse raw samples based on bit depth
            if sample_width == 1:
                # 8-bit unsigned PCM
                samples = (np.frombuffer(raw_frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0

            elif sample_width == 2:
                # 16-bit signed PCM (Standard telephony / TTS)
                samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0

            elif sample_width == 3:
                # 24-bit signed PCM (Studio / High-Res)
                raw_bytes = np.frombuffer(raw_frames, dtype=np.uint8).reshape(-1, 3)
                # Prepend 0 byte to convert 24-bit little endian into 32-bit signed int
                padded = np.pad(raw_bytes, ((0, 0), (1, 0)), mode="constant", constant_values=0)
                samples = padded.view(np.int32).flatten().astype(np.float32) / 2147483648.0

            elif sample_width == 4:
                # 32-bit signed PCM
                samples = np.frombuffer(raw_frames, dtype=np.int32).astype(np.float32) / 2147483648.0

            else:
                raise ValueError(f"Unsupported sample width: {sample_width} bytes")

            # 2. Downmix multi-channel / stereo to mono
            if num_channels > 1:
                samples = samples.reshape(-1, num_channels).mean(axis=1)

            duration_ms = (num_frames / float(sample_rate)) * 1000.0
            return samples, sample_rate, duration_ms

    @staticmethod
    def evaluate_waveform(samples: np.ndarray, sample_rate: int) -> Tuple[ComponentScore, dict]:
        reasons = []
        score = 1.0

        if len(samples) == 0:
            return ComponentScore(score=0.0, passed=False, reasons=["Sound file contained 0 audio frames"]), {}

        clipping_ratio = float(np.sum(np.abs(samples) >= 0.99) / len(samples))
        frame_len = max(int(sample_rate * 0.02), 1)
        num_frames = len(samples) // frame_len
        
        if num_frames > 0:
            frames = samples[: num_frames * frame_len].reshape((num_frames, frame_len))
            frame_rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-9)
            noise_floor = np.percentile(frame_rms, 10)
            signal_energy = np.percentile(frame_rms, 90)
            snr_db = float(20 * np.log10((signal_energy + 1e-6) / (noise_floor + 1e-6)))
            silence_ratio = float(np.sum(frame_rms < settings.AUDIO_MIN_RMS_ENERGY) / num_frames)
        else:
            snr_db = 0.0
            silence_ratio = 1.0

        if snr_db < settings.AUDIO_MIN_SNR_DB:
            score -= 0.4
            reasons.append(f"Low SNR: {snr_db:.1f}dB < {settings.AUDIO_MIN_SNR_DB}dB")
        if clipping_ratio > settings.AUDIO_MAX_CLIPPING_RATIO:
            score -= 0.4
            reasons.append(f"Clipping: {clipping_ratio * 100:.1f}%")
        if silence_ratio > settings.AUDIO_MAX_SILENCE_RATIO:
            score -= 0.5
            reasons.append(f"Excess silence: {silence_ratio * 100:.1f}%")

        score = max(0.0, min(1.0, score))
        metrics = {
            "snr_db": round(snr_db, 2),
            "clipping_ratio": round(clipping_ratio, 4),
            "silence_ratio": round(silence_ratio, 4)
        }
        return ComponentScore(score=score, passed=score >= 0.70, reasons=reasons), metrics

    @staticmethod
    def evaluate(payload: AudioSignalPayload) -> ComponentScore:
        reasons = []
        score = 1.0
        if payload.snr_db is not None and payload.snr_db < settings.AUDIO_MIN_SNR_DB:
            score -= 0.4
            reasons.append(f"Low SNR: {payload.snr_db:.1f}dB < {settings.AUDIO_MIN_SNR_DB}dB")
        if payload.clipping_ratio is not None and payload.clipping_ratio > settings.AUDIO_MAX_CLIPPING_RATIO:
            score -= 0.4
            reasons.append(f"Clipping: {payload.clipping_ratio * 100:.1f}%")
        if payload.silence_ratio is not None and payload.silence_ratio > settings.AUDIO_MAX_SILENCE_RATIO:
            score -= 0.5
            reasons.append(f"Excessive silence: {payload.silence_ratio * 100:.1f}%")
        score = max(0.0, min(1.0, score))
        return ComponentScore(score=score, passed=score >= 0.70, reasons=reasons)