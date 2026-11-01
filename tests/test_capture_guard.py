"""0.36.1: 보스 체력바 판독 캡처에서 우리 오버레이 빼기(도르카와 같은 방식) — 가짜 capture_exclusion으로 맥·리눅스 확인."""

import os
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QWidget

from mabinogi_addon.system import capture_exclusion
from mabinogi_addon.ui.capture_guard import CaptureGuard


class _Fake:
    def __init__(self, available=True, fail_restore=False):
        self.available_value = available
        self.calls = []
        self.inside = []
        self.fail_restore = fail_restore
        self.restored = []

    def install(self, monkeypatch):
        monkeypatch.setattr(capture_exclusion, "available", lambda: self.available_value)

        @contextmanager
        def excluding(handles, box):
            self.calls.append((set(handles), box))
            pending = []
            self.inside.append(True)
            yield pending
            self.inside.append(False)
            if self.fail_restore:
                pending.extend((h, 0) for h in handles)
        monkeypatch.setattr(capture_exclusion, "excluding_windows", excluding)
        monkeypatch.setattr(capture_exclusion, "restore_window", lambda hwnd, prev: self.restored.append(hwnd) or True)


@pytest.fixture
def overlay():
    QApplication.instance() or QApplication([])
    w = QWidget()
    w.setGeometry(10, 10, 50, 20)
    w.show()
    yield w
    w.close()


def test_grab_inside_exclusion_with_our_visible_windows(monkeypatch, overlay):
    fake = _Fake()
    fake.install(monkeypatch)
    seen = []

    def grab(x, y, w, h):
        seen.append(((x, y, w, h), list(fake.inside)))
        return np.zeros((h, w, 3), np.uint8)
    frame = CaptureGuard().grab(grab, 5, 6, 70, 30)
    assert frame.shape == (30, 70, 3)
    handles, box = fake.calls[0]
    assert int(overlay.winId()) in handles and box == (5, 6, 70, 30)
    assert seen == [((5, 6, 70, 30), [True])]  # 제외한 동안 찍는다


def test_not_available_uses_plain_capture(monkeypatch, overlay):
    fake = _Fake(available=False)
    fake.install(monkeypatch)
    calls = []
    CaptureGuard().grab(lambda *a: calls.append(a), 1, 2, 3, 4)
    assert calls == [(1, 2, 3, 4)] and fake.calls == []


def test_failed_restore_is_retried_next_time(monkeypatch, overlay):
    fake = _Fake(fail_restore=True)
    fake.install(monkeypatch)
    guard = CaptureGuard()
    guard.grab(lambda *a: None, 0, 0, 10, 10)
    assert guard._pending  # 되돌리기 실패한 창을 기억
    guard.restore()
    assert int(overlay.winId()) in fake.restored and not guard._pending


def test_boss_tab_capture_goes_through_guard(monkeypatch):
    from types import SimpleNamespace
    from mabinogi_addon.ui.boss_tab import BossTab

    QApplication.instance() or QApplication([])
    fake = _Fake()
    fake.install(monkeypatch)
    tab = BossTab(SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False))
    try:
        raw = []
        monkeypatch.setattr(tab, "_grab_raw", lambda *a: raw.append(a) or np.zeros((4, 4, 3), np.uint8))
        tab._grab_rect(100, 50, 600, 36)
        assert raw == [(100, 50, 600, 36)] and fake.calls and fake.calls[0][1] == (100, 50, 600, 36)
    finally:
        tab.shutdown()
        tab.close()


def test_restore_does_not_wait_for_dwm_flush(monkeypatch):
    """0.37.0 QA: 되돌린 뒤 DwmFlush로 화면 스레드를 막지 않는다(제외 쪽 1번만)."""
    import ctypes
    import os as _os

    class User:
        def __init__(self):
            self.affinity = {}

        def GetWindowThreadProcessId(self, hwnd, pid):
            pid._obj.value = _os.getpid()
            return 1

        def IsWindowVisible(self, hwnd):
            return True

        def IsWindow(self, hwnd):
            return True

        def GetWindowRect(self, hwnd, rect):
            r = rect._obj
            r.left, r.top, r.right, r.bottom = 0, 0, 100, 100
            return True

        def GetWindowDisplayAffinity(self, hwnd, out):
            out._obj.value = self.affinity.get(hwnd, 0)
            return True

        def SetWindowDisplayAffinity(self, hwnd, value):
            self.affinity[hwnd] = value
            return True

    class Dwm:
        flushes = 0

        def DwmFlush(self):
            Dwm.flushes += 1
            return 0

    user, dwm = User(), Dwm()
    monkeypatch.setattr(capture_exclusion, "available", lambda: True)
    monkeypatch.setattr(capture_exclusion, "_api", lambda: (user, dwm))
    monkeypatch.setattr(ctypes, "byref", lambda obj: type("Ref", (), {"_obj": obj})())
    with capture_exclusion.excluding_windows([11, 12], (10, 10, 50, 50)) as pending:
        assert user.affinity == {11: 0x11, 12: 0x11} and Dwm.flushes == 1
    assert user.affinity == {11: 0, 12: 0} and pending == []
    assert Dwm.flushes == 1  # 복원 쪽 Flush 없음
