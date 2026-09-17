import os
import wave
import numpy as np

def create_wav(filename: str, samples: np.ndarray, sample_rate: int = 16000):
    os.makedirs("fixtures", exist_ok=True)
    filepath = os.path.join("fixtures", filename)
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)        # Mono
        wf.setsampwidth(2)        # 16-bit PCM
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    print(f"[OK] Ses dosyası oluşturuldu: {filepath}")

def main():
    sr = 16000
    duration = 2.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)

    # 1. Temiz ses tonu (440Hz sinüs dalgası)
    clean = (np.sin(2 * np.pi * 440 * t) * 0.5 * 32767).astype(np.int16)
    create_wav("clean_tone.wav", clean, sr)

    # 2. Patlak / Kırpılmış ses (Clipping distorsiyonu)
    clipped = np.clip(np.sin(2 * np.pi * 440 * t) * 4.0, -1.0, 1.0)
    clipped = (clipped * 32767).astype(np.int16)
    create_wav("clipped_distortion.wav", clipped, sr)

    # 3. Ölü sessizlik
    silence = np.zeros(int(sr * duration), dtype=np.int16)
    create_wav("silent_dead_air.wav", silence, sr)

if __name__ == "__main__":
    main()