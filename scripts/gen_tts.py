"""알림 목소리 팩(mp3) 생성기 — edge-tts(무료) / Google Chirp 3 HD(고품질) 백엔드.

앱은 `assets/sounds/<팩이름>/<파일명>.mp3` 를 "목소리 팩"으로 인식한다(설정 →
알림 목소리에서 선택). 팩은 '기본과 같은 파일명, 다른 음성·말투' 묶음이다.
팩에 없는 파일은 기본(flat) 녹음본으로 자동 폴백한다.

실행(인터넷 되는 내 PC에서):
    # edge-tts (무료, 설정 0)
    uv run --with edge-tts python scripts/gen_tts.py
    uv run --with edge-tts python scripts/gen_tts.py --pack "부드러운 여성"

    # Google Chirp 3 HD (고품질, API 키 필요 · 월 100만 자 무료라 우리 사용량은 $0)
    #   GCP: Cloud Text-to-Speech API 사용 설정 → API 키 발급
    set GOOGLE_TTS_API_KEY=...      (Windows cmd)   /   $env:GOOGLE_TTS_API_KEY="..." (PowerShell)
    uv run python scripts/gen_tts.py --backend google
    uv run python scripts/gen_tts.py --backend google --pack "차분한 남성"

편집 포인트:
- lines: 파일명 → 읽을 문구(말투). 파일명은 기본 팩과 동일해야 앱이 매칭한다.
- edge_voice / rate / pitch: edge-tts용. (여성 SunHi/JiMin/SeoHyeon/YuJin, 남성 InJoon/Hyunsu 등)
- google_voice: Google Chirp 3 HD 보이스(ko-KR-Chirp3-HD-*). 샘플은 GCP 콘솔에서 들어보고 고름.
- speaking_rate: Google 말속도(0.25~4.0, 1.0=기본). Chirp3는 pitch 미지원이라 속도만.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import urllib.request
from pathlib import Path

SOUNDS_DIR = Path(__file__).resolve().parents[1] / "src" / "mabinogi_addon" / "assets" / "sounds"

# 기본 팩과 동일한 파일명 집합(팩마다 재사용)
F_VIVACE = "비바체 연장.mp3"
F_SHARP = "상태지원 알림.mp3"
F_HAM = "햄 버닝 연장.mp3"
F_MARCH = "행진곡 연장.mp3"
F_OVERTURE = "전장의 서곡 연장.mp3"
F_PARTY = "파티 알림.mp3"
F_TUARIM = "투아림 부스트 발동 직전.mp3"

# 팩 정의 — 성격마다 목소리·말투를 다르게. 자유롭게 추가/수정하세요.
PACKS: list[dict] = [
    {
        "name": "부드러운 여성",
        "edge_voice": "ko-KR-SunHiNeural",
        "rate": "-6%",
        "pitch": "-2Hz",
        "google_voice": "ko-KR-Chirp3-HD-Pulcherrima",
        "speaking_rate": 0.95,
        "lines": {
            F_VIVACE: "비바체 연장해요",
            F_SHARP: "상지 잊지 말아요",
            F_HAM: "햄 버닝 연장할 시간이에요",
            F_MARCH: "행진곡 연장해요",
            F_OVERTURE: "전장의 서곡 연장해요",
            F_PARTY: "파티 모집이 올라왔어요",
            F_TUARIM: "투아림 곧 터져요",
        },
    },
    {
        "name": "밝은 여성",
        "edge_voice": "ko-KR-SunHiNeural",
        "rate": "+10%",
        "pitch": "+6Hz",
        "google_voice": "ko-KR-Chirp3-HD-Sulafat",
        "speaking_rate": 1.05,
        "lines": {
            F_VIVACE: "비바체 연장할 때예요!",
            F_SHARP: "상지 챙기세요!",
            F_HAM: "햄 버닝 또 가요!",
            F_MARCH: "행진곡 연장해요!",
            F_OVERTURE: "서곡 다시 넣어요!",
            F_PARTY: "파티 떴어요, 얼른!",
            F_TUARIM: "투아림 터져요 터져요!",
        },
    },
    {
        "name": "차분한 남성",
        "edge_voice": "ko-KR-InJoonNeural",
        "rate": "-4%",
        "pitch": "+0Hz",
        "google_voice": "ko-KR-Chirp3-HD-Algieba",
        "speaking_rate": 0.97,
        "lines": {
            F_VIVACE: "비바체 연장하세요",
            F_SHARP: "상태 지원 잊지 마세요",
            F_HAM: "햄 버닝 연장하세요",
            F_MARCH: "행진곡 연장하세요",
            F_OVERTURE: "전장의 서곡 연장하세요",
            F_PARTY: "파티 모집이 올라왔습니다",
            F_TUARIM: "투아림 부스트 발동 직전입니다",
        },
    },
]


# ---- edge-tts 백엔드 (무료) ----
async def _gen_edge(pack: dict) -> None:
    import edge_tts  # 지연 import

    out = SOUNDS_DIR / pack["name"]
    out.mkdir(parents=True, exist_ok=True)
    print(f"[edge] {pack['name']}  {pack['edge_voice']} rate={pack['rate']} pitch={pack['pitch']}")
    for filename, text in pack["lines"].items():
        c = edge_tts.Communicate(
            text, pack["edge_voice"], rate=pack["rate"], pitch=pack["pitch"]
        )
        await c.save(str(out / filename))
        print(f"  ✓ {filename}  ←  “{text}”")


# ---- Google Chirp 3 HD 백엔드 (고품질, API 키) ----
_GOOGLE_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"


def _gen_google(pack: dict, api_key: str) -> None:
    out = SOUNDS_DIR / pack["name"]
    out.mkdir(parents=True, exist_ok=True)
    print(f"[google] {pack['name']}  {pack['google_voice']} rate={pack['speaking_rate']}")
    for filename, text in pack["lines"].items():
        body = {
            "input": {"text": text},
            "voice": {"languageCode": "ko-KR", "name": pack["google_voice"]},
            # Chirp 3 HD는 pitch 미지원 → speakingRate만. mp3로 바로 받음.
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": float(pack.get("speaking_rate", 1.0)),
            },
        }
        req = urllib.request.Request(
            f"{_GOOGLE_URL}?key={api_key}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            audio = json.loads(resp.read())["audioContent"]
        (out / filename).write_bytes(base64.b64decode(audio))
        print(f"  ✓ {filename}  ←  “{text}”")


def main() -> None:
    ap = argparse.ArgumentParser(description="알림 목소리 팩 생성기")
    ap.add_argument("--backend", choices=["edge", "google"], default="edge")
    ap.add_argument("--pack", help="특정 팩만 생성(이름). 생략 시 전체")
    args = ap.parse_args()

    targets = [p for p in PACKS if args.pack is None or p["name"] == args.pack]
    if not targets:
        print(f"'{args.pack}' 팩을 못 찾음. 사용 가능: {[p['name'] for p in PACKS]}")
        sys.exit(1)

    if args.backend == "google":
        import os

        key = os.environ.get("GOOGLE_TTS_API_KEY", "").strip()
        if not key:
            print("환경변수 GOOGLE_TTS_API_KEY 가 필요합니다.")
            sys.exit(1)
        for pack in targets:
            _gen_google(pack, key)
    else:
        for pack in targets:
            asyncio.run(_gen_edge(pack))

    print(f"\n완료 → {SOUNDS_DIR}")
    print("생성된 폴더를 git add/commit 하면 exe 빌드에도 포함됩니다.")


if __name__ == "__main__":
    main()
