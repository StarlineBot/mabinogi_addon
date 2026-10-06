"""개발용: 알림 TTS 음성 오디션 스크립트. (배포에는 포함하지 않는다)

집 PC에서 한 번 실행해 후보 음성으로 `"{버프이름} 연장"`을 뽑아 들어보고,
마음에 드는 엔진·음성을 정한다. 정한 값은 나중에 Notifier/TtsCache의
코드 상수로 박는다.

사용 예:
    # Edge-TTS 뉴럴 음성 (네트워크 필요, 품질 높음)
    uv run --with edge-tts python scripts/tts_preview.py --engine edge

    # Windows 내장 SAPI (오프라인, Windows 전용)
    uv run python scripts/tts_preview.py --engine sapi

결과물은 scripts/_tts_preview/ 에 저장된다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

OUT_DIR = Path(__file__).parent / "_tts_preview"

# 후보 음성. 들어보고 하나로 정한다.
EDGE_VOICES = [
    "ko-KR-SunHiNeural",  # 여성
    "ko-KR-InJoonNeural",  # 남성
    "ko-KR-HyunsuMultilingualNeural",  # 남성, 최신 멀티링궐
]


def preview_edge(text: str) -> None:
    """Edge-TTS 뉴럴 음성으로 mp3 생성. edge-tts 패키지와 네트워크 필요."""
    try:
        import edge_tts
    except ImportError:
        sys.exit("edge-tts가 없습니다. `uv run --with edge-tts python scripts/tts_preview.py --engine edge`")

    import asyncio

    async def one(voice: str) -> None:
        out = OUT_DIR / f"edge_{voice}.mp3"
        await edge_tts.Communicate(text, voice).save(str(out))
        print("저장:", out)

    async def run() -> None:
        for voice in EDGE_VOICES:
            await one(voice)

    asyncio.run(run())


def preview_sapi(text: str) -> None:
    """Windows 내장 SAPI5 음성으로 wav 생성. Windows 전용."""
    if sys.platform != "win32":
        sys.exit("SAPI는 Windows에서만 동작합니다. 집 Windows에서 실행하세요.")

    import win32com.client  # pywin32

    voice = win32com.client.Dispatch("SAPI.SpVoice")
    tokens = voice.GetVoices()
    for i in range(tokens.Count):
        token = tokens.Item(i)
        name = token.GetDescription()
        safe = "".join(c if c.isalnum() else "_" for c in name)
        out = OUT_DIR / f"sapi_{safe}.wav"

        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(str(out), 3)  # 3 = SSFMCreateForWrite
        voice.AudioOutputStream = stream
        voice.Voice = token
        voice.Speak(text)
        stream.Close()
        print("저장:", out, f"({name})")


def main() -> None:
    parser = argparse.ArgumentParser(description="알림 TTS 음성 오디션")
    parser.add_argument("--engine", choices=["edge", "sapi"], default="edge")
    parser.add_argument("--text", default="마법 대미지 증가 연장")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    if args.engine == "edge":
        preview_edge(args.text)
    else:
        preview_sapi(args.text)
    print(f"\n{OUT_DIR} 안의 파일을 재생해 들어보고 음성을 고르세요.")


if __name__ == "__main__":
    main()
