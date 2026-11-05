"""쿨타임 끝 효과음(assets/sounds/쿨타임 끝.wav)을 만든다 — 외부 음원 없이 직접 합성(라이선스 걱정 없음).

짧고 가벼운 두 음 '딩-딩'(A5 → E6, 약 0.4초). 상태지원 등 음성 안내와 겹쳐도 구별되게 높은 음, 음량은 -9dBFS 정도.
다시 만들기: uv run python scripts/make_cooldown_sound.py
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

RATE = 44100
OUT = Path(__file__).resolve().parents[1] / "src/mabinogi_addon/assets/sounds/쿨타임 끝.wav"


def _note(freq: float, start: float, length: float, total: float) -> np.ndarray:
    t = np.arange(int(total * RATE)) / RATE
    local = t - start
    on = (local >= 0) & (local < length)
    env = np.where(on, np.exp(-np.clip(local, 0, None) * 9.0), 0.0)
    attack = np.clip(local / 0.006, 0, 1)  # 6ms 부드러운 시작(딸깍 소리 방지)
    tone = np.sin(2 * np.pi * freq * local) + 0.25 * np.sin(2 * np.pi * freq * 2 * local)
    return tone * env * attack


def make() -> Path:
    total = 0.42
    sig = _note(880.0, 0.0, 0.30, total) + _note(1318.5, 0.11, 0.31, total)
    fade = np.clip((total - np.arange(int(total * RATE)) / RATE) / 0.03, 0, 1)  # 끝 30ms 페이드
    sig = sig * fade
    sig = sig / np.abs(sig).max() * 0.35  # 약 -9dBFS
    data = (sig * 32767).astype("<i2").tobytes()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
    return OUT


if __name__ == "__main__":
    print(make())
