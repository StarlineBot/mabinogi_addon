"""캐릭터 착장(옷) — 기본 옷 + 호감도 50·100에서 열리는 두 벌(docs/character-pet-spec.md 3-2절, 사용자 11-25).

착장 그림은 assets/characters/<폴더>/outfits/<key>/ 아래. 지금은 카드(card.png)만 있고, 펫 SD 프레임이 생기면
같은 이름(stand_0.png 등)으로 그 폴더에 넣으면 펫 창이 그걸 먼저 쓴다(없는 프레임은 기본 옷 그대로).
"""
from __future__ import annotations

from dataclasses import dataclass

BASE = ""   # 기본 옷 key(저장 값이 비어 있으면 기본)


@dataclass(frozen=True)
class Outfit:
    key: str      # 저장 값·폴더 이름(기본 옷은 "")
    name: str     # 한글 이름(원본 그림 폴더 docs/characters/assets/<폴더>/의상/<이름>/)
    level: int    # 열리는 호감도(기본 0)


_BASE = Outfit(BASE, "기본", 0)

# 캐릭터 폴더 → (기본, 50, 100). Starline은 착장 없음(서랍 없음).
OUTFITS: dict[str, tuple[Outfit, ...]] = {
    "다래": (_BASE, Outfit("frill_pajama", "프릴 잠옷 원피스", 50),
             Outfit("white_offshoulder", "하얀 오프숄더 프릴 원피스", 100)),
    "아리아": (_BASE, Outfit("tshirt", "티셔츠 차림", 50), Outfit("summer_dress", "가벼운 여름 드레스", 100)),
    "레나": (_BASE, Outfit("lab", "연구실 차림", 50), Outfit("red_dress", "빨간 원피스", 100)),
    "이안": (_BASE, Outfit("vest_tie", "넥타이 조끼", 50), Outfit("guild_uniform", "길드 고위 정복", 100)),
}


def of(folder: str) -> tuple[Outfit, ...]:
    """그 캐릭터 착장(기본 포함, 기본 → 50 → 100). 착장이 없으면 ()."""
    return OUTFITS.get(folder, ())


def find(folder: str, key: str) -> Outfit | None:
    return next((o for o in of(folder) if o.key == key), None)


def unlocked(outfit: Outfit, affinity: int) -> bool:
    return affinity >= outfit.level


def drawer(folder: str, current: str) -> list[Outfit]:
    """서랍에 보일 옷 — 지금 입은 옷을 뺀 나머지(기본 → 50 → 100 순서). 착장이 없으면 []."""
    items = of(folder)
    if find(folder, current) is None:
        current = BASE
    return [o for o in items if o.key != current]


def wearing(folder: str, saved: str) -> str:
    """저장 값 → 실제 입는 옷 key(모르는 값이면 기본)."""
    return saved if find(folder, saved) is not None else BASE


def asset(folder: str, key: str, name: str) -> str:
    """assets/characters/ 아래 상대 경로 — 착장 폴더(기본 옷이면 캐릭터 폴더)의 그 파일."""
    return f"{folder}/{name}" if key == BASE else f"{folder}/outfits/{key}/{name}"
