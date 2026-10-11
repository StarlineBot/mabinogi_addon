"""단축바 미러 격자/슬라이싱 회귀 테스트.

실제 오버레이(Qt 위젯)는 offscreen 전체 스위트에서만 다루고, 여기선 순수 로직만 본다.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

# QPixmap 생성(slice_group)에 QApplication이 필요 — 단독 실행 시 세그폴트 방지.
_app = QApplication.instance() or QApplication([])

from mabinogi_addon.ui.skillbar_mirror import (
    BLOCK_X,
    CELLS,
    GROUP_DX,
    ICON,
    IPITCH,
    ROW_Y,
    SRC_H,
    SRC_W,
    group_defs,
    slice_group,
)


def test_group_defs_count_and_layout():
    gds = group_defs()
    assert len(gds) == len(BLOCK_X) * len(ROW_Y) * len(GROUP_DX) == 12
    keys = {g.key for g in gds}
    assert len(keys) == 12  # 중복 없음
    # 블록1 윗줄 1번째 그룹은 앵커(0,0)
    g0 = next(g for g in gds if g.key == "b0r0c0")
    assert (g0.x, g0.y) == (0, 0)


def test_src_dims_cover_all_groups():
    for g in group_defs():
        assert g.x + (CELLS - 1) * IPITCH + ICON <= SRC_W
        assert g.y + ICON <= SRC_H


def test_slice_group_extracts_cells_and_respects_toggle():
    # 각 칸을 서로 다른 단색으로 채운 소스 → 슬라이스가 그 칸을 집는지 + 토글 반영.
    src = np.zeros((SRC_H, SRC_W, 3), np.uint8)
    g = next(x for x in group_defs() if x.key == "b0r0c0")
    for i in range(CELLS):
        src[g.y : g.y + ICON, g.x + i * IPITCH : g.x + i * IPITCH + ICON] = (i + 1) * 40
    cells = slice_group(src, g, [True, False, True, True])
    assert cells[1] is None  # 꺼진 칸 → None(투명)
    assert cells[0] is not None and cells[2] is not None and cells[3] is not None
    assert cells[0].width() == ICON and cells[0].height() == ICON


def test_slice_group_out_of_bounds_is_none():
    small = np.zeros((10, 10, 3), np.uint8)
    g = group_defs()[0]
    assert slice_group(small, g, [True] * CELLS) == [None] * CELLS
