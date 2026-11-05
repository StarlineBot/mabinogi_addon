"""격자 안내선이 한동안 남던 문제(사용자 11-05): 뗌 이벤트를 못 받아도·드래그 중 숨김/고정·설정 끄기에서 바로 사라진다."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui import grid


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    yield app
    grid.hide_guide()


def _overlay():
    from mabinogi_addon.ui.memo_overlay import MemoOverlay
    o = MemoOverlay()
    o.set_locked(False)
    o.show()
    return o


def test_guide_hides_itself_when_button_released_without_release_event(app, monkeypatch):
    """누른 뒤 뗌 이벤트 없이 버튼이 풀림 → 100ms 확인에서 스스로 숨김."""
    owner = _overlay()
    try:
        monkeypatch.setattr(QGuiApplication, "mouseButtons", staticmethod(lambda: Qt.MouseButton.LeftButton))
        grid.show_guide(owner)
        assert grid.guide_visible() and grid._guide._watch.isActive() and grid._guide._watch.interval() == 100
        grid._guide.check()
        assert grid.guide_visible()  # 아직 누르고 있음 — 유지
        monkeypatch.setattr(QGuiApplication, "mouseButtons", staticmethod(lambda: Qt.MouseButton.NoButton))
        grid._guide.check()  # 타이머 한 번
        assert not grid.guide_visible() and not grid._guide._watch.isActive()
    finally:
        owner.close()


def test_hiding_dragged_overlay_hides_guide_immediately(app, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "mouseButtons", staticmethod(lambda: Qt.MouseButton.LeftButton))
    owner = _overlay()
    try:
        grid.show_guide(owner)
        owner.hide()  # 드래그 중 오버레이 숨김(게임 비활성 등)
        assert not grid.guide_visible()
    finally:
        owner.close()


def test_locking_dragged_overlay_hides_guide_immediately(app, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "mouseButtons", staticmethod(lambda: Qt.MouseButton.LeftButton))
    owner = _overlay()
    try:
        grid.show_guide(owner)
        owner.set_locked(True)  # 드래그 중 고정(전체 위치 잠금 등)
        assert not grid.guide_visible()
    finally:
        owner.close()


@pytest.mark.parametrize("name", ["overlay.BuffOverlay", "frame_overlay.FrameOverlay", "pattern_overlay.PatternWarningOverlay",
                                  "upcoming_overlay.UpcomingPatternsOverlay", "dorcha_overlay.DorchaOverlay"])
def test_every_overlay_lock_uses_common_cleanup(app, monkeypatch, name):
    import importlib
    import inspect
    module_name, cls = name.split(".")
    module = importlib.import_module(f"mabinogi_addon.ui.{module_name}")
    assert "owner_locked(self)" in inspect.getsource(getattr(module, cls).set_locked)


def test_unrelated_overlay_lock_keeps_guide(app, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "mouseButtons", staticmethod(lambda: Qt.MouseButton.LeftButton))
    owner, other = _overlay(), _overlay()
    try:
        grid.show_guide(owner)
        other.set_locked(True)
        assert grid.guide_visible()  # 다른 오버레이를 고정하는 건 상관없음
    finally:
        owner.close()
        other.close()


def test_turning_off_grid_snap_hides_guide(window, monkeypatch):
    w, app = window
    monkeypatch.setattr(QGuiApplication, "mouseButtons", staticmethod(lambda: Qt.MouseButton.LeftButton))
    w.settings_tab._grid_snap.setChecked(True)
    grid.show_guide()
    assert grid.guide_visible()
    w.settings_tab._grid_snap.setChecked(False)  # 설정에서 격자 맞춤 끄기
    assert not grid.guide_visible()


from test_navigation import window  # noqa: E402,F401  (창 픽스처)
