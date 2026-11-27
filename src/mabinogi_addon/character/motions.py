"""호감도 모션(25·75 보상, docs/characters/호감도_모션.md '앱 동작' — 사용자 11-26 확정).

모션 하나 = 시작(소품 꺼냄) → 반복 구간 2~3번 → 끝(소품 치우고 서 있기 자세). 반복 구간은 그 문서의 프레임 설명
('A/B 번갈아 반복')으로 정함. 레나 공중 앉기만 반복을 길게(10~20초). 반복 설명이 없는 모션(이안 옷매무새·Starline)은 한 번.
그림 파일은 assets/characters/<폴더>/<key>_N.png(착장은 outfits/<옷>/ 같은 이름).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

FRAME = 0.3     # 한 장 시간(초)


@dataclass(frozen=True)
class Motion:
    stage: int                         # 열리는 호감도 구간
    key: str                           # 파일 이름 앞부분(motion_water → motion_water_0.png …)
    count: int                         # 장 수
    loop: tuple[int, int] | None       # 반복 구간 [시작, 끝) — 없으면 한 번
    long_loop: tuple[float, float] | None = None   # 반복을 이 초만큼(레나 공중 앉기)
    hold: tuple[tuple[int, float], ...] = ()       # 장마다 머무는 시간(번호, 초) — 없으면 FRAME(다래 양인형 안기 2.1초, 레나 마법서 이 악묾 0.6·'탁' 1.2초, 아리아 물주기 들어 보이기 1.2초·화관 쓴 5번 2.0초, 11-26 · Starline 손가락 총·모자에 손 넣기 1.0초, 11-27)

    def names(self) -> tuple[str, ...]:
        return tuple(f"{self.key}_{i}" for i in range(self.count))

    def sequence(self, rng: random.Random) -> tuple[tuple[str, float], ...]:
        """(프레임, 초) 순서 — 반복 구간은 2~3번(긴 반복이면 그 시간만큼)."""
        names = self.names()
        held = dict(self.hold)
        dur = {f"{self.key}_{i}": held.get(i, FRAME) for i in range(self.count)}
        if self.loop is None:
            return tuple((n, dur[n]) for n in names)
        a, b = self.loop
        part = names[a:b]
        if self.long_loop is not None:
            reps = max(2, round(rng.uniform(*self.long_loop) / (FRAME * len(part))))
        else:
            reps = rng.randint(2, 3)
        order = names[:a] + part * reps + names[b:]
        return tuple((n, dur[n]) for n in order)


MOTIONS: dict[str, tuple[Motion, ...]] = {
    "아리아": (Motion(25, "motion_water", 8, (2, 4), hold=((6, 1.2),)), Motion(75, "motion_wreath", 8, (2, 4), hold=((5, 2.0),))),
    # 양인형: 6번(인형을 안아 올림)은 2.1초 머묾(사용자 11-26 '껴안고 있는 프레임이 좀 유지되어야')
    "다래": (Motion(25, "motion_sheep_doll", 8, (2, 4), hold=((6, 2.1),)), Motion(75, "motion_bubbles", 8, (2, 4))),
    "레나": (Motion(25, "motion_grimoire", 8, (2, 4), hold=((4, 0.6), (5, 1.2))), Motion(75, "motion_float_sit", 8, (2, 5), (10.0, 20.0))),
    "이안": (Motion(25, "motion_tidy", 8, None), Motion(75, "motion_tea", 6, (2, 4))),
    "Starline": (Motion(25, "motion_flame_shot", 6, None, hold=((0, 1.0),)),
                  Motion(75, "motion_hat_magic", 6, None, hold=((1, 1.0),))),
}


def of(folder: str) -> tuple[Motion, ...]:
    return MOTIONS.get(folder, ())


def frame_names(folder: str) -> set[str]:
    return {n for m in of(folder) for n in m.names()}


def unlocked(folder: str, stage: int, frames) -> dict[str, float]:
    """열린 모션 → 고를 무게(지금 구간에서 새로 열린 것 2배). 그림이 다 있는 것만(입은 옷에 없으면 빠짐)."""
    out = {}
    for m in of(folder):
        if m.stage <= stage and all(n in frames for n in m.names()):
            out[m.key] = 2.0 if m.stage == stage else 1.0
    return out
