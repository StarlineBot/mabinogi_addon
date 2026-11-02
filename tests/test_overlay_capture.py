"""0.37.1: 우리 오버레이를 판독 캡처에서 항상 빼기(설정 없음) — 가짜 capture_exclusion으로 맥·리눅스 확인."""

import os
import pathlib
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from mabinogi_addon.system import capture_exclusion
from mabinogi_addon.ui import overlay_capture

UI = pathlib.Path(__file__).resolve().parents[1] / "src/mabinogi_addon/ui"


def test_every_always_on_top_window_is_classified():
    """항상 위에 뜨는 창을 새로 만들면 OVERLAYS(상시 제외)나 NOT_OVERLAYS 중 하나에 넣어야 한다(누락 방지)."""
    found = set()
    for path in UI.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        classes = [(m.start(), m.group(1)) for m in re.finditer(r"^class (\w+)\(", text, re.M)]
        for hit in re.finditer("WindowStaysOnTopHint", text):
            owner = [name for pos, name in classes if pos < hit.start()]
            if owner:
                found.add(owner[-1])
    missing = found - overlay_capture.OVERLAYS - overlay_capture.NOT_OVERLAYS
    assert not missing, f"분류 안 된 항상 위 창: {sorted(missing)}"
    assert not overlay_capture.OVERLAYS & overlay_capture.NOT_OVERLAYS


@pytest.fixture
def fake(monkeypatch):
    QApplication.instance() or QApplication([])
    calls = []
    state = {"available": True}
    monkeypatch.setattr(capture_exclusion, "available", lambda: state["available"])
    monkeypatch.setattr(capture_exclusion, "set_excluded", lambda hwnd, excluded: calls.append((hwnd, excluded)) or True)
    yield calls, state


def _chunk():
    from mabinogi_addon.ui.skillbar_mirror import ChunkOverlay, group_defs
    return ChunkOverlay(group_defs()[0])


def test_overlay_is_excluded_when_shown(fake):
    calls, _ = fake
    w = _chunk()
    try:
        w.show()
        QApplication.processEvents()
        assert (int(w.winId()), True) in calls  # 상시 제외
        w.hide(); calls.clear(); w.show(); QApplication.processEvents()
        assert (int(w.winId()), True) in calls  # 다시 떠도 다시 건다(창 핸들이 바뀌어도)
    finally:
        w.close()


def test_main_window_dialogs_and_region_selector_untouched(fake):
    calls, _ = fake
    from mabinogi_addon.ui.region_highlight import RegionHighlight
    dialog, highlight = QDialog(), RegionHighlight()
    try:
        dialog.show(); highlight.show(); QApplication.processEvents()
        assert calls == []
        assert not overlay_capture.is_overlay(dialog) and not overlay_capture.is_overlay(highlight)
    finally:
        dialog.close(); highlight.close()


def test_old_windows_does_nothing(fake):
    calls, state = fake
    state["available"] = False
    w = _chunk()
    try:
        w.show(); QApplication.processEvents()
        assert calls == []
    finally:
        w.close()


def test_main_window_is_not_an_overlay(fake):
    from test_navigation import window  # noqa: F401
    from mabinogi_addon.ui.main_window import MainWindow
    assert not any(cls.__name__ in overlay_capture.OVERLAYS for cls in MainWindow.__mro__)


def test_every_overlay_class_registers_itself():
    """0.37.1 Windows 검증 뒤: 앱 전체 필터 대신 오버레이 생성자에서 그 창에만 등록 — 빠진 오버레이가 없게."""
    registered = set()
    for path in UI.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        classes = [(m.start(), m.group(1)) for m in re.finditer(r"^class (\w+)\(", text, re.M)]
        for hit in re.finditer(r"overlay_capture\.watch\(self\)", text):
            owner = [name for pos, name in classes if pos < hit.start()]
            if owner:
                registered.add(owner[-1])
    assert registered == set(overlay_capture.OVERLAYS)


def test_no_app_wide_filter_and_errors_never_escape(fake, monkeypatch):
    """앱 전체 이벤트 필터를 쓰지 않고, 제외 함수가 예외를 내도 창 표시·이벤트는 그대로."""
    calls, _ = fake
    assert not hasattr(overlay_capture, "install")
    w = _chunk()
    try:
        def boom(*a):
            raise RuntimeError("native failure")
        monkeypatch.setattr(capture_exclusion, "set_excluded", boom)
        w.show()
        QApplication.processEvents()
        assert w.isVisible()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendEvent(w, QEvent(QEvent.Type.ActivationChange))
    finally:
        w.close()
