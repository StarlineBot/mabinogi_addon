"""Register A, recover moved UI at B, restart, and reacquire B without approval."""

from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[2]
from mabinogi_addon import config, image_io
from mabinogi_addon.detect.dorcha_anchor import locate_dorcha
from mabinogi_addon.detect.dorcha_reader import read_dorcha
from mabinogi_addon.ui.dorcha_tab import DorchaTab

A = (30, 40, 28, 23)
B = (160, 110, 28, 23)


def finish_search(tab):
    deadline = monotonic() + 5
    while tab._search_worker is not None and monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
    assert tab._search_worker is None


@pytest.fixture
def moved(monkeypatch):
    app = QApplication.instance() or QApplication([])
    previous_threads = cv2.getNumThreads()
    cv2.setNumThreads(1)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa"})
    monkeypatch.setattr("mabinogi_addon.ui.dpi.to_physical",
                        lambda box: tuple(box[key] for key in ("x", "y", "w", "h")))
    config.save_dorcha({"enabled": True, "pos": {"x": 250, "y": 150}, "locked": True})
    source = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-16 211914.png")
    zero = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-09 185117.png")
    assert source is not None and zero is not None
    panel = source[931:988, 933:978].copy()
    zero = zero[892:915, 716:744].copy()
    assert read_dorcha(zero) == 0
    frame = np.zeros((220, 320, 3), np.uint8)
    captures, tabs = [], []
    monkeypatch.setattr(DorchaTab, "_search_target", lambda self: (101, 202, 0, 0, 320, 220))

    def grab(self, x, y, width, height):
        captures.append((x, y, width, height))
        return frame[y:y + height, x:x + width].copy()

    monkeypatch.setattr(DorchaTab, "_grab_rect", grab)

    def create():
        for existing in tabs:
            existing.shutdown()
            existing.close()
        tab = DorchaTab(SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False))
        tab._timer.stop()
        tabs.append(tab)
        return tab

    try:
        first = create()
        first._apply_region(*A)
        frame[A[1] - 17:A[1] + 40, A[0] - 8:A[0] + 37] = panel
        first._tick()
        finish_search(first)
        assert first._overlay.value == 15
        frame[:] = 0
        frame[B[1] - 17:B[1] + 40, B[0] - 8:B[0] + 37] = panel
        first._tick()
        finish_search(first)
        assert first._live_box == B and first._overlay.value == 15
        assert config.load_dorcha()["box"] == dict(zip(("x", "y", "w", "h"), A))
        yield app, create, frame, zero, captures, first
    finally:
        for tab in tabs:
            tab.shutdown()
            for widget in (tab._overlay, tab):
                if widget is not None:
                    widget.close()
                    widget.deleteLater()
        app.processEvents()
        cv2.setNumThreads(previous_threads)


@pytest.mark.parametrize("old_digits", [False, True], ids=["blank-old-roi", "unrelated-old-zero"])
def test_restart_must_reacquire_visible_moved_resource(moved, old_digits):
    _, create, frame, zero, captures, _ = moved
    if old_digits:
        frame[A[1]:A[1] + A[3], A[0]:A[0] + A[2]] = zero
    assert locate_dorcha(frame) == B
    restarted = create()
    captures.clear()
    for _ in range(30):
        restarted._tick()
        finish_search(restarted)
    print({"old_digits": old_digits, "saved": restarted._region, "live": restarted._live_box,
           "value": restarted._overlay.value, "full_searches": captures.count((0, 0, 320, 220))})
    assert restarted._overlay.value == 15 and restarted._live_box == B


def test_one_shot_autofind_approval_recovers_the_same_input(moved):
    _, create, frame, zero, captures, _ = moved
    frame[A[1]:A[1] + A[3], A[0]:A[0] + A[2]] = zero
    restarted = create()
    restarted._tick()
    finish_search(restarted)
    print({"before_approval": restarted._overlay.value, "live": restarted._live_box})
    box = locate_dorcha(frame)
    assert box == B
    restarted._apply_region(*box)
    restarted._tick()
    finish_search(restarted)
    assert restarted._overlay.value == 15 and restarted._live_box == B


@pytest.mark.parametrize("manual", [False, True], ids=["runtime-recovery", "manual-autofind-control"])
def test_restart_recovery_with_own_window_over_ornament(moved, monkeypatch, manual):
    app, create, frame, _, captures, first = moved
    from mabinogi_addon.ui import screen_grab

    blocker = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    blocker.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    blocker.setStyleSheet("background:#ffffff;")
    blocker.setGeometry(B[0] - 8, B[1] - 17, 45, 17)
    blocker.show()
    app.processEvents()

    def visible_frame():
        result = frame.copy()
        if blocker.isVisible():
            image = blocker.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            rgba = np.frombuffer(image.bits(), np.uint8).reshape(image.height(), image.bytesPerLine())
            pixels = rgba[:, :image.width() * 4].reshape(image.height(), image.width(), 4)
            x, y = blocker.x(), blocker.y()
            result[y:y + image.height(), x:x + image.width()] = pixels[:, :, :3][:, :, ::-1]
        return result

    def grab(self, x, y, width, height):
        captures.append((x, y, width, height))
        return visible_frame()[y:y + height, x:x + width].copy()

    monkeypatch.setattr(DorchaTab, "_grab_rect", grab)
    monkeypatch.setattr(screen_grab, "_grab_game_window", lambda: (visible_frame(), 0, 0))
    monkeypatch.setattr(screen_grab, "_mss", lambda: SimpleNamespace(monitors=[]))
    try:
        # The application-owned window covers only the ornament, not the digits.
        assert read_dorcha(visible_frame()[B[1]:B[1] + B[3], B[0]:B[0] + B[2]]) == 15
        assert locate_dorcha(frame) == B
        assert locate_dorcha(visible_frame()) is None
        first._tick()
        finish_search(first)
        assert first._overlay.value == 15 and first._live_box == B
        restarted = create()
        captures.clear()
        restarted._tick()
        finish_search(restarted)
        print({"manual": manual, "before_manual": restarted._overlay.value,
               "full_searches": captures.count((0, 0, 320, 220)), "blocker_visible": blocker.isVisible()})
        if manual:
            captured, ox, oy = screen_grab.capture_for_autofind(require_game=True)
            assert (ox, oy) == (0, 0)
            assert locate_dorcha(captured) == B
            restarted._apply_region(*locate_dorcha(captured))
            restarted._tick()
            finish_search(restarted)
        assert restarted._overlay.value == 15 and restarted._live_box == B
    finally:
        blocker.close()
        blocker.deleteLater()
        app.processEvents()
