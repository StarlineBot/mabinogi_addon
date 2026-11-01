"""0.36.1 사용자 제보: 단축바 묶음(ChunkOverlay)을 끌 때 격자 맞춤이 없었다 — 다른 오버레이(mirror_overlay)와 같게."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui import grid
from mabinogi_addon.ui.skillbar_mirror import ChunkOverlay, group_defs


@pytest.fixture
def chunk():
    QApplication.instance() or QApplication([])
    w = ChunkOverlay(group_defs()[0])
    w.set_locked(False)
    w.move(100, 100)
    yield w
    w.close()


def _event(kind, global_pos, button=Qt.MouseButton.LeftButton):
    buttons = Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseButtonRelease else button
    return QMouseEvent(kind, QPointF(5, 5), QPointF(global_pos), button, buttons, Qt.KeyboardModifier.NoModifier)


def _drag(w, start, end):
    w.mousePressEvent(_event(QMouseEvent.Type.MouseButtonPress, start))
    w.mouseMoveEvent(_event(QMouseEvent.Type.MouseMove, end))
    w.mouseReleaseEvent(_event(QMouseEvent.Type.MouseButtonRelease, end))


@pytest.mark.parametrize("snap_on", [True, False])
def test_drag_snaps_to_grid_only_when_enabled(chunk, monkeypatch, snap_on):
    guides = []
    monkeypatch.setattr(grid, "enabled", lambda: snap_on)
    monkeypatch.setattr(grid, "size", lambda: 32)
    monkeypatch.setattr(grid, "_screen_center", lambda: (1000, 500))
    monkeypatch.setattr(grid, "show_guide", lambda: guides.append("show"))
    monkeypatch.setattr(grid, "hide_guide", lambda: guides.append("hide"))
    moved = []
    chunk.moved.connect(lambda: moved.append(1))
    start = chunk.frameGeometry().topLeft() + QPoint(5, 5)
    _drag(chunk, start, start + QPoint(237, 141))
    top_left = chunk.frameGeometry().topLeft()
    expected = QPoint(100 + 237, 100 + 141)
    if snap_on:
        assert top_left == grid.snap(expected, 32)
        assert (top_left.x() - 1000) % 32 == 0 and (top_left.y() - 500) % 32 == 0
        assert guides == ["show", "hide"]
    else:
        assert top_left == expected and guides == ["hide"]
    assert moved == [1]


def test_right_click_still_toggles_cell(chunk, monkeypatch):
    monkeypatch.setattr(grid, "enabled", lambda: True)
    toggled = []
    chunk.cell_toggled.connect(toggled.append)
    before = chunk.frameGeometry().topLeft()
    chunk.mousePressEvent(_event(QMouseEvent.Type.MouseButtonPress, before + QPoint(5, 5), Qt.MouseButton.RightButton))
    assert toggled == [0] and chunk.frameGeometry().topLeft() == before
