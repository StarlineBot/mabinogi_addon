"""오버레이를 새로 만들 때마다 격자 맞춤이 빠지지 않게(사용자 11-05 질문) — 끌어서 옮기는 모든 오버레이가 격자를 쓰는지,
새 오버레이(쿨타임·보스바)는 실제로 끌면 격자에 붙는지 본다."""
from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui import grid

UI = Path(__file__).parents[1] / "src/mabinogi_addon/ui"


def _draggable_classes():
    """mouseMoveEvent 안에서 self.move(...)로 창을 옮기는 클래스 = 끌어서 옮기는 오버레이."""
    found = []
    for path in sorted(UI.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "mouseMoveEvent"):
                src = ast.get_source_segment(path.read_text(encoding="utf-8"), fn)
                if "self.move(" in src:
                    found.append((path.name, cls.name, src))
    return found


DRAGGABLE = _draggable_classes()


def test_draggable_overlays_found():
    names = {c for _f, c, _s in DRAGGABLE}
    assert {"BuffOverlay", "CooldownOverlay", "BossBarOverlay", "MemoOverlay"} <= names


@pytest.mark.parametrize("module,cls,src", DRAGGABLE, ids=[c for _f, c, _s in DRAGGABLE])
def test_every_draggable_overlay_snaps_to_grid(module, cls, src):
    assert "grid.snap(" in src, f"{module}:{cls} 드래그가 격자 맞춤(grid.snap)을 쓰지 않음"


def _mouse(kind, gx, gy):
    p = QPointF(gx, gy)
    return QMouseEvent(kind, QPointF(5, 5), p, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)


@pytest.mark.parametrize("make", ["cooldown", "bossbar"])
def test_new_overlays_snap_while_dragging_and_hide_guide(make):
    QApplication.instance() or QApplication([])
    config.save_general_flag("gridSnap", True)
    if make == "cooldown":
        from mabinogi_addon.ui.cooldown_overlay import CooldownOverlay
        ov = CooldownOverlay(100)
    else:
        from mabinogi_addon.ui.boss_bar_overlay import BossBarOverlay
        ov = BossBarOverlay(100)
    moved = []
    ov.moved.connect(lambda: moved.append(1))
    try:
        ov.set_locked(False)
        ov.move(100, 100)
        ov.show()
        start = ov.frameGeometry().topLeft() + QPoint(5, 5)
        ov.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, start.x(), start.y()))
        assert grid.guide_visible()  # 끄는 동안 격자 안내선
        ov.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, start.x() + 37, start.y() + 23))
        target = QPoint(100 + 37, 100 + 23)
        assert ov.pos() == grid.snap(target, grid.size())  # 격자 칸에 맞춰 이동
        ov.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, start.x() + 37, start.y() + 23))
        assert not grid.guide_visible() and moved == [1]
    finally:
        grid.hide_guide()
        ov.close()
