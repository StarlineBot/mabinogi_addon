"""캐릭터 목록(명세 1절·3절 4번). 카드 순서 = 이 목록 순서.

목소리 팩(assets/sounds/<팩>/)마다 캐릭터 하나. 이름이 정해진 캐릭터는 다래(조용한 여성)뿐이고,
나머지는 실루엣 + `???`(사용자 제작 예정). 미정 캐릭터도 고르면 그 목소리 팩이 그대로 쓰인다.
"""
from __future__ import annotations

from dataclasses import dataclass

UNKNOWN_NAME = "???"


@dataclass(frozen=True)
class Character:
    key: str          # 저장 키(호감도 등) — 목소리 팩 이름과 같게 둔다(팩이 곧 캐릭터)
    name: str         # 카드에 보이는 이름
    pack: str         # 알림 목소리 팩 폴더
    color: str        # 캐릭터 색(이름 글자·Zzz 등 코드로 그리는 장식)
    card: str         # 카드 그림(assets/characters/ 아래 경로)
    known: bool       # False면 실루엣을 테마 회색으로 칠해 씀
    has_pet: bool     # 화면을 돌아다니는 SD 펫 그림이 있는지(알파는 다래만)


DARE = Character("조용한 여성", "다래", "조용한 여성", "#B9A3E3", "다래/card.png", True, True)

ROSTER: tuple[Character, ...] = (
    DARE,
    Character("부드러운 여성", UNKNOWN_NAME, "부드러운 여성", "#9AA0AA", "silhouette_f.png", False, False),
    Character("자연스러운 여성", UNKNOWN_NAME, "자연스러운 여성", "#9AA0AA", "silhouette_f.png", False, False),
    Character("화난 여성", UNKNOWN_NAME, "화난 여성", "#9AA0AA", "silhouette_f.png", False, False),
    Character("차분한 남성", UNKNOWN_NAME, "차분한 남성", "#9AA0AA", "silhouette_m.png", False, False),
)


def by_pack(pack: str) -> Character | None:
    """그 목소리 팩의 캐릭터(없으면 None — 기본 녹음 등)."""
    return next((c for c in ROSTER if c.pack == pack), None)
