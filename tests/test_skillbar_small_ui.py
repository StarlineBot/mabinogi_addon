"""작은 인터페이스 단축바(테스터 11-26 image (34)): 아이콘 배율 0.764, ◀n▶ 원래 크기, 둘째 단축바가 떨어져 있음."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.detect import cooldown as cd
from mabinogi_addon.detect.click_targets import skill_cells
from mabinogi_addon.detect.skillbar_anchor import (
    anchor_of, compose, layout, locate_skillbar, source_box_of, split_layout)

DATA = Path(__file__).parent / "data"
BOX = (3, 17, 1033, 68)


@pytest.fixture(scope="module")
def frame():
    return image_io.imread(DATA / "small_ui_skillbar_20261126.png", cv2.IMREAD_COLOR)


def test_layout_standard_boxes_unchanged():
    for box in ((6, 14, 1168, 89), (0, 0, 1752, 134), (0, 0, 876, 67), (0, 0, 2336, 178)):
        s, gap = layout(box)
        assert gap == 620 and not split_layout(box)
        assert anchor_of(box) == {"x": box[0], "y": box[1]}
    assert not split_layout((5, 5, 40, 40))  # 직접 지정(첫 칸 상자)


def test_layout_small_box():
    s, gap = layout(BOX)
    assert s == pytest.approx(0.764, abs=0.002) and gap == pytest.approx(804, abs=3)
    assert split_layout(BOX)
    assert anchor_of(BOX) == {"x": 3, "y": 17, "w": 1033, "h": 68}
    assert source_box_of(anchor_of(BOX)) == BOX
    assert source_box_of({"x": 6, "y": 14}) == (6, 14, 1168, 89)
    assert source_box_of({"x": 6, "y": 14, "w": 40, "h": 40}) == (6, 14, 1168, 89)  # 예전 형식·이상한 크기는 기본
    assert source_box_of(None) is None


def test_compose_joins_both_bars(frame):
    out = compose(frame, BOX)
    assert out.shape == (89, 1168, 3)
    edges = cv2.dilate(cv2.Canny(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY), 50, 120), np.ones((3, 3), np.uint8)) > 0
    from mabinogi_addon.ui.skillbar_mirror import group_defs
    for g in group_defs():  # 12묶음 모두 칸 테두리가 기본 격자 자리에 있다
        tile = edges[g.y:g.y + 40, g.x:g.x + 40]
        border = np.concatenate((tile[1, :], tile[-2, :], tile[:, 1], tile[:, -2]))
        assert border.mean() >= 0.6, g


def test_compose_of_captured_region_matches(frame):
    x, y, w, h = BOX  # 미러는 상자만 찍어 (0, 0, w, h)로 붙인다
    a = compose(frame[y:y + h, x:x + w], (0, 0, w, h))
    assert np.array_equal(a, compose(frame, BOX))


def test_skill_cells_cover_second_bar(frame):
    cells = skill_cells(BOX)
    assert len(cells) == 48
    first2 = next(c for c in cells if c.info["block"] == 1 and c.info["row"] == 0 and c.info["group"] == 0 and c.info["slot"] == 0)
    s, gap = layout(BOX)
    assert first2.rect[0] == round(3 + gap * s)
    assert 615 <= first2.rect[0] <= 625  # 보라 원 오른쪽 둘째 단축바 첫 칸(화면 실측 ≈617)
    assert first2.rect[2] == round(40 * s)


def test_selector_rects_find_native_arrows(frame):
    for row, top in ((0, 24), (1, 61)):
        rects = cd.selector_rects(BOX, row)
        assert rects[0] == (432, top, 15, 16)  # 실측 숫자 상자(원래 크기)
        assert cd.key_block(frame, rects) == 0
        assert cd.page_rect(frame, BOX, row) == rects[0]
        assert cd.page_signature(frame, rects[0]) is not None


def test_locate_small_ui_is_fast_enough(frame):
    import time
    t = time.perf_counter()
    trace = {}
    assert tuple(locate_skillbar(frame, None, trace)) == BOX
    assert trace["stage"] == "small_ui"
    assert time.perf_counter() - t < 3.0
