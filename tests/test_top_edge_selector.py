"""위 경계 조절 오버레이 좌표 계산 스모크 테스트.

좌/우(너비)·아래(화면 끝)는 고정, 위만 사용자가 정한다 → selected(x, y, w, h)에서
h = 화면끝 - 위경계 가 맞는지 확인.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon.ui.top_edge_selector import TopEdgeSelector  # noqa: E402


def test_emits_region_with_bottom_fixed():
    QApplication.instance() or QApplication([])
    w = TopEdgeSelector(x=100, w=300, initial_top=200)
    # 렌더/테스트 환경의 화면 크기와 무관하게 좌표계 고정.
    w._geo = QRect(0, 0, 2560, 1440)
    w._bottom = 1440
    w._x = 100
    out = []
    w.selected.connect(lambda x, y, ww, hh: out.append((x, y, ww, hh)))
    w.set_top_for_preview(500)  # 사용자가 위 경계를 500으로
    w._commit()
    assert out == [(100, 500, 300, 940)], out  # 아래=1440 고정 → h=1440-500


def test_enter_commits_auto_not_mouse():
    """Enter는 '자동값 그대로' — 마우스가 아래로 움직여 _top이 바뀌어도 자동값으로 확정."""
    QApplication.instance() or QApplication([])
    w = TopEdgeSelector(x=12, w=304, initial_top=257)
    w._geo = QRect(0, 0, 2560, 1440)
    w._bottom = 1440
    w._x = 12
    w._auto_top = 257
    w.set_top_for_preview(900)  # 마우스가 아래로 이동(=_top=900)
    out = []
    w.selected.connect(lambda x, y, ww, hh: out.append((x, y, ww, hh)))
    w._commit_auto()  # Enter
    assert out == [(12, 257, 304, 1183)], out  # 자동값 257 사용, h=1440-257


def test_top_clamped_above_bottom():
    QApplication.instance() or QApplication([])
    w = TopEdgeSelector(x=0, w=100, initial_top=99999)  # 화면 밖으로 줘도
    w._geo = QRect(0, 0, 1920, 1080)
    w._bottom = 1080
    w.set_top_for_preview(99999)
    out = []
    w.selected.connect(lambda *a: out.append(a))
    w._commit()
    assert out and out[0][1] <= 1080 - 10  # 위 경계가 바닥 위로 클램프됨
