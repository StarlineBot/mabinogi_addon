"""자동 실행(레지스트리 Run 키)의 비-Windows 안전성 테스트.

실제 레지스트리 등록은 Windows에서만 되므로, 다른 OS에서 호출이 안전한지만 본다.
"""

import sys

from mabinogi_addon.system import autostart


def test_available_matches_platform():
    assert autostart.available() == (sys.platform == "win32")


def test_safe_noop_off_windows():
    if sys.platform != "win32":
        assert autostart.is_enabled() is False
        assert autostart.set_enabled(True) is False
        assert autostart.set_enabled(False) is False
        autostart.reconcile(True)  # 예외 없이 통과(비Windows no-op)
        autostart.reconcile(False)


def _patch_common(monkeypatch, frozen):
    monkeypatch.setattr(autostart, "available", lambda: True)
    monkeypatch.setattr(autostart, "_is_frozen", lambda: frozen)


def test_frozen_enable_registers_task_and_clears_registry(monkeypatch):
    """배포본(작업 스케줄러)에서 켜면 작업을 등록하고, 구버전 Run 키 잔재는 제거한다
    (옛 exe가 같이 뜨던 중복 실행 방지)."""
    calls = []
    _patch_common(monkeypatch, frozen=True)
    monkeypatch.setattr(autostart, "_task_set", lambda e: calls.append(("task", e)) or True)
    monkeypatch.setattr(autostart, "_reg_delete", lambda: calls.append(("reg_del",)))
    assert autostart.set_enabled(True) is True
    assert calls == [("task", True), ("reg_del",)]


def test_frozen_disable_deletes_task_and_registry(monkeypatch):
    calls = []
    _patch_common(monkeypatch, frozen=True)
    monkeypatch.setattr(autostart, "_task_set", lambda e: calls.append(("task", e)) or True)
    monkeypatch.setattr(autostart, "_reg_delete", lambda: calls.append(("reg_del",)))
    autostart.set_enabled(False)
    assert calls == [("task", False), ("reg_del",)]


def test_dev_enable_cleans_stale_task(monkeypatch):
    """개발(레지스트리) 실행인데 배포본이 만든 작업 잔재가 남아 있으면 정리한다."""
    calls = []
    _patch_common(monkeypatch, frozen=False)
    monkeypatch.setattr(autostart, "_reg_set", lambda e: calls.append(("reg", e)) or True)
    monkeypatch.setattr(autostart, "_task_enabled", lambda: True)  # 잔재 있음
    monkeypatch.setattr(autostart, "_task_delete", lambda: calls.append(("task_del",)) or True)
    assert autostart.set_enabled(True) is True
    assert calls == [("reg", True), ("task_del",)]


def test_reconcile_reports_registration_failure(monkeypatch):
    """0.11.3: 일반 권한 실행에서 schtasks /RL HIGHEST 등록 실패가 로그에만 남던 문제 — 결과를 돌려준다."""
    _patch_common(monkeypatch, frozen=True)
    monkeypatch.setattr(autostart, "_reg_delete", lambda: None)
    monkeypatch.setattr(autostart, "_task_set", lambda e: False)
    assert autostart.reconcile(True) is False
    monkeypatch.setattr(autostart, "_task_set", lambda e: True)
    assert autostart.reconcile(True) is True


def test_startup_shows_notice_when_autostart_cannot_be_synced(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon import config
    from mabinogi_addon.ui import main_window, toast
    app = QApplication.instance() or QApplication([])
    shown = []
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(autostart, "reconcile", lambda intent: False)
    monkeypatch.setattr(toast, "show_toast", lambda title, body, *a, **k: shown.append((title, body)))
    monkeypatch.setattr(main_window.MainWindow, "_maybe_check_update", lambda self, *a: None)
    config._write_local_config({"general": {"skipSetup": True, "tourShown": True, "firstUseGuideShown": True}})
    w = main_window.MainWindow()
    try:
        w.start()
        assert any(title == "자동 실행 설정 실패" and "관리자 권한" in body for title, body in shown)
    finally:
        w._force_quit = True
        w.close()
