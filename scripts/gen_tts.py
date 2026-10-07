"""알림 목소리 팩(mp3) 생성기 — edge-tts(무료 MS Neural) 사용.

앱은 `assets/sounds/<팩이름>/<파일명>.mp3` 를 "목소리 팩"으로 인식한다(설정 →
알림 목소리에서 선택). 팩은 '기본과 같은 파일명, 다른 음성·말투' 묶음이다.
팩에 없는 파일은 기본(flat) 녹음본으로 자동 폴백한다.

실행(인터넷 되는 내 PC에서):
    uv run --with edge-tts python scripts/gen_tts.py            # 전체 생성
    uv run --with edge-tts python scripts/gen_tts.py 부드러운\\ 여성   # 특정 팩만

목소리·말투를 바꾸려면 아래 PACKS를 편집하면 된다.
- voice:  edge-tts 한국어 보이스
    여성: ko-KR-SunHiNeural
    남성: ko-KR-InJoonNeural, ko-KR-HyunsuNeural
  (전체 목록: `uv run --with edge-tts edge-tts --list-voices | findstr ko-KR`)
- rate/pitch: 말투 조절. 예) rate="+12%"(빠르게) "-8%"(느리게), pitch="+8Hz" "-2Hz"
- lines: 파일명 → 읽을 문구. 파일명은 기본 팩과 동일해야 앱이 매칭한다.

생성된 폴더를 git에 커밋하면 배포 exe에도 포함된다(release.yml이 assets 통째로 번들).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

SOUNDS_DIR = Path(__file__).resolve().parents[1] / "src" / "mabinogi_addon" / "assets" / "sounds"

# 기본 팩과 동일한 파일명 집합(여기 키를 팩마다 재사용한다)
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
        "voice": "ko-KR-SunHiNeural",
        "rate": "-6%",
        "pitch": "-2Hz",
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
        "name": "발랄한 여성",
        "voice": "ko-KR-SunHiNeural",
        "rate": "+14%",
        "pitch": "+8Hz",
        "lines": {
            F_VIVACE: "비바체 연장할 때!",
            F_SHARP: "상지 챙겨야지!",
            F_HAM: "햄 버닝 또 가자!",
            F_MARCH: "행진곡 연장 고고!",
            F_OVERTURE: "서곡 다시 넣자!",
            F_PARTY: "파티 떴어요 얼른!",
            F_TUARIM: "투아림 터진다 터진다!",
        },
    },
    {
        "name": "차분한 남성",
        "voice": "ko-KR-InJoonNeural",
        "rate": "-4%",
        "pitch": "+0Hz",
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


async def _gen_pack(edge_tts, pack: dict) -> None:
    out = SOUNDS_DIR / pack["name"]
    out.mkdir(parents=True, exist_ok=True)
    print(f"[{pack['name']}] {pack['voice']} rate={pack['rate']} pitch={pack['pitch']}")
    for filename, text in pack["lines"].items():
        dest = out / filename
        c = edge_tts.Communicate(
            text, pack["voice"], rate=pack["rate"], pitch=pack["pitch"]
        )
        await c.save(str(dest))
        print(f"  ✓ {filename}  ←  “{text}”")


async def _main(only: str | None) -> None:
    import edge_tts  # 지연 import: 스크립트 실행 때만 필요

    targets = [p for p in PACKS if only is None or p["name"] == only]
    if not targets:
        print(f"'{only}' 팩을 못 찾음. 사용 가능: {[p['name'] for p in PACKS]}")
        return
    for pack in targets:
        await _gen_pack(edge_tts, pack)
    print(f"\n완료 → {SOUNDS_DIR}")
    print("생성된 폴더를 git add/commit 하면 exe 빌드에도 포함됩니다.")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(_main(only))
