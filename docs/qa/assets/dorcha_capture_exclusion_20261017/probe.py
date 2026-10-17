"""Real exclusion helper and readers, with an affinity-aware capture boundary."""

import os
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from scripts.qa_dorcha_restart_after_move import A, B, finish_search, moved
from mabinogi_addon import config
from mabinogi_addon.detect.dorcha_anchor import locate_dorcha
from mabinogi_addon.system import capture_exclusion
from mabinogi_addon.ui.dorcha_tab import DorchaTab


@pytest.mark.parametrize("support,apply_ok", [(True, True), (True, False), (False, True)])
def test_restarted_reader_uses_affinity_not_widget_visibility(moved, monkeypatch, support, apply_ok):
    app, create, frame, _, _, first = moved
    blocker = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    blocker.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    blocker.setStyleSheet("background:#ffffff")
    blocker.setGeometry(B[0]-8, B[1]-17, 45, 17)
    blocker.show()
    app.processEvents()
    hwnd = int(blocker.winId())
    geometry = blocker.geometry()
    affinity, calls, captures = {}, [], []

    def widgets():
        return {int(widget.winId()): widget for widget in QApplication.topLevelWidgets()
                if widget.isVisible()}

    def owner(handle, pointer):
        pointer._obj.value = os.getpid()
        return 123

    def rect(handle, pointer):
        widget = widgets().get(handle)
        if widget is None:
            return False
        r = widget.geometry()
        target = pointer._obj
        target.left, target.top = r.x(), r.y()
        target.right, target.bottom = r.x()+r.width(), r.y()+r.height()
        return True

    def get(handle, pointer):
        pointer._obj.value = affinity.get(handle, 0)
        return True

    def set_value(handle, value):
        calls.append((handle, value))
        if value == 0x11 and not apply_ok:
            return False
        affinity[handle] = value
        return True

    user = SimpleNamespace(GetWindowThreadProcessId=owner, GetWindowRect=rect,
                           IsWindow=lambda handle: handle in widgets(),
                           IsWindowVisible=lambda handle: handle in widgets(),
                           GetWindowDisplayAffinity=get, SetWindowDisplayAffinity=set_value)
    monkeypatch.setattr(capture_exclusion, "available", lambda: support)
    monkeypatch.setattr(capture_exclusion, "_api", lambda: (user, SimpleNamespace(DwmFlush=lambda: 0)))
    monkeypatch.setattr(capture_exclusion, "_warned", False)

    image = blocker.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    rgba = np.frombuffer(image.bits(), np.uint8).reshape(image.height(), image.bytesPerLine())
    pixels = rgba[:, :image.width()*4].reshape(image.height(), image.width(), 4)[:, :, :3][:, :, ::-1].copy()

    def grab(self, x, y, width, height):
        assert blocker.isVisible() and blocker.geometry() == geometry
        current = frame.copy()
        excluded = affinity.get(hwnd, 0) == 0x11
        captures.append((width, height, excluded))
        if not excluded:
            bx, by = blocker.x(), blocker.y()
            current[by:by+pixels.shape[0], bx:bx+pixels.shape[1]] = pixels
        return current[y:y+height, x:x+width].copy()

    monkeypatch.setattr(DorchaTab, "_grab_rect", grab)
    original = dict(zip(("x", "y", "w", "h"), A))
    try:
        assert locate_dorcha(frame) == B
        first._tick()
        finish_search(first)
        assert first._overlay.value == 15
        for _ in range(5):
            tab = create()
            captures.clear()
            tab._tick()
            finish_search(tab)
            if support and apply_ok:
                assert tab._live_box == B and tab._overlay.value == 15
                assert any(w == 320 and h == 220 and excluded for w, h, excluded in captures)
            else:
                assert tab._overlay.value is None
                assert not any(excluded for _, _, excluded in captures)
            assert blocker.isVisible() and blocker.geometry() == geometry
            assert affinity.get(hwnd, 0) == 0 and not tab._capture_restore
            assert config.load_dorcha()["box"] == original
        if support and apply_ok:
            assert (hwnd, 0x11) in calls and (hwnd, 0) in calls
        elif not support:
            assert not calls
    finally:
        blocker.close()
        blocker.deleteLater()
        app.processEvents()
