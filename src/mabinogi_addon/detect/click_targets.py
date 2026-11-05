"""클릭 경계 자동 맞춤(click-snap 명세) — 화면 스냅샷 → 맞출 수 있는 사각형 목록, 커서 → 겹치는 대상.

기존 탐지기를 그대로 쓴다(새 탐지 없음):
- 단축바 칸 하나(48칸): `skillbar_anchor.locate_skillbar` → 칸 좌표는 `ui/skillbar_mirror.py` 격자 상수.
- 체력바 줄 하나(생명력·마나·스태미나): `stat_bars.locate_stat_bars` + 줄 나누기 `_bands`.
- 보스 체력바(보일 때만): `boss_bar.locate_boss_bar(validate=make_validator())`.
좌표는 모두 스냅샷(물리 픽셀) 기준. 작업 스레드에서 1회 돈다(선택창을 열 때) — 화면 스레드는 `hit`만 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SKILL, STAT, BOSS = "skill", "stat", "boss"
ALL_KINDS = (SKILL, STAT, BOSS)
STAT_NAMES = ("생명력 바", "마나 바", "스태미나 바")


@dataclass(frozen=True)
class Target:
    kind: str
    rect: tuple[int, int, int, int]   # 물리 픽셀 (x, y, w, h)
    name: str
    info: dict = field(default_factory=dict, compare=False, hash=False)  # 단축바 칸: block,row,group,slot,source

    @property
    def label(self) -> str:
        return f"{self.name} {self.rect[2]} × {self.rect[3]}"


def skill_cells(source_box) -> list[Target]:
    """단축바 소스 사각형(1168×89 기준 배율) → 칸 48개."""
    from ..ui.skillbar_mirror import BLOCK_X, CELLS, GROUP_DX, ICON, IPITCH, ROW_Y
    x, y, w, _h = source_box
    s = w / 1168.0
    out = []
    for b, bx in enumerate(BLOCK_X):
        for r, ry in enumerate(ROW_Y):
            for g, gx in enumerate(GROUP_DX):
                for i in range(CELLS):
                    rect = (round(x + (bx + gx + i * IPITCH) * s), round(y + ry * s), round(ICON * s), round(ICON * s))
                    out.append(Target(SKILL, rect, "단축바 칸",
                                      {"block": b, "row": r, "group": g, "slot": i, "source": tuple(source_box)}))
    return out


def find_targets(frame: np.ndarray | None, kinds=ALL_KINDS) -> list[Target]:
    """스냅샷(BGR, 물리 픽셀) → 맞출 수 있는 대상. 탐지기 하나가 실패해도 나머지는 돌려준다."""
    if frame is None or getattr(frame, "ndim", 0) != 3 or frame.size == 0:
        return []
    targets: list[Target] = []
    if SKILL in kinds:
        try:
            from .skillbar_anchor import locate_skillbar
            box = locate_skillbar(frame)
            if box is not None:
                targets += skill_cells(box)
        except Exception:  # noqa: BLE001 — 한 탐지기 실패가 나머지를 막지 않게
            pass
    if STAT in kinds:
        try:
            from .stat_bars import _bands, locate_stat_bars
            box = locate_stat_bars(frame)
            if box is not None:
                bx, by, bw, bh = box
                for name, (r0, r1) in zip(STAT_NAMES, _bands(frame[by:by + bh, bx:bx + bw])):
                    targets.append(Target(STAT, (bx, by + r0, bw, r1 - r0), name))
        except Exception:  # noqa: BLE001
            pass
    if BOSS in kinds:
        try:
            from .boss_bar import locate_boss_bar, make_validator
            box = locate_boss_bar(frame, validate=make_validator())
            if box is not None:
                targets.append(Target(BOSS, tuple(int(v) for v in box), "보스 체력바"))
        except Exception:  # noqa: BLE001
            pass
    return targets


def hit(targets, x: float, y: float) -> Target | None:
    """(물리 픽셀) 점을 덮는 대상 중 가장 작은 것 — 사각형 비교만(화면 스레드에서 매 마우스 이동)."""
    best = None
    for t in targets:
        tx, ty, tw, th = t.rect
        if tx <= x < tx + tw and ty <= y < ty + th and (best is None or tw * th < best.rect[2] * best.rect[3]):
            best = t
    return best
