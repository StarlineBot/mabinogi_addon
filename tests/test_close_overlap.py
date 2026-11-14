"""종료 시간 줄이기(0.49.0, 사용자 결정 11-14): 동기화 올림을 다른 정리와 겹치고 끝에서 남은 시간만 기다림 + 종료 기록."""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui import account_controller as ac
from mabinogi_addon.ui.main_window import close_summary
from test_main_shutdown import window  # noqa: F401 — 픽스처


@pytest.fixture
def ctrl(monkeypatch):
    QApplication.instance() or QApplication([])
    c = ac.AccountController(executor=ThreadPoolExecutor(1))
    monkeypatch.setattr(c, "_token", lambda: "t")
    monkeypatch.setattr(c, "sync_enabled", lambda: True)
    return c


def test_upload_overlaps_other_cleanup(ctrl, monkeypatch):
    monkeypatch.setattr(ctrl, "_job_upload", lambda rev, force: time.sleep(0.4) or ("uploaded", {}))
    start = time.monotonic()
    ctrl.begin_shutdown()
    time.sleep(0.4)  # 파티·추적 정지·오버레이 닫기 등 다른 정리
    waited = ctrl.finish_shutdown()
    total = time.monotonic() - start
    assert total < 0.65  # ≈ max(올림, 정리), 더하기(0.8초)가 아님
    assert waited < 150


def test_upload_failure_or_timeout_does_not_stop_cleanup(ctrl, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="mabinogi_addon.account")

    def boom(rev, force):
        raise RuntimeError("서버 꺼짐")
    monkeypatch.setattr(ctrl, "_job_upload", boom)
    ctrl.begin_shutdown()
    ctrl.finish_shutdown()  # 예외가 밖으로 나오지 않음
    assert any("종료 때 올리기 실패" in r.getMessage() for r in caplog.records)
    c2 = ac.AccountController(executor=ThreadPoolExecutor(1))
    monkeypatch.setattr(c2, "_token", lambda: "t")
    monkeypatch.setattr(c2, "sync_enabled", lambda: True)
    monkeypatch.setattr(ac, "FLUSH_TIMEOUT", 0.3)
    monkeypatch.setattr(c2, "_job_upload", lambda rev, force: time.sleep(1.0))
    start = time.monotonic()
    c2.begin_shutdown()
    c2.finish_shutdown()
    assert time.monotonic() - start < 0.7  # 시작부터 최대 FLUSH_TIMEOUT까지만


def test_close_summary_format():
    line = close_summary(2.31, {"블랙박스": [0.0, 2, 0.41]}, 120.4)
    assert line == ("종료 요청 → 끝 2310ms · 블랙박스 대기 410ms(다시 시도 2번) · 설정 대기 0ms · 최적화 대기 0ms"
                    " · 동기화 남은 기다림 120ms")


def test_close_starts_upload_after_state_save_and_waits_at_end(window, monkeypatch, caplog):  # noqa: F811
    w, _starts = window
    order = []
    monkeypatch.setattr(w, "_save_overlay_state", lambda: order.append("상태 저장"))
    monkeypatch.setattr(w._account, "begin_shutdown", lambda flush=True: order.append("올림 시작"))
    monkeypatch.setattr(w._account, "finish_shutdown", lambda: order.append("올림 기다림") or 12.0)
    monkeypatch.setattr(w.party_tab, "stop_polling", lambda wait_ms=0: order.append("파티 정지"))
    calls = {"n": 0}

    def blackbox_ready():
        calls["n"] += 1
        return calls["n"] > 2  # 두 번 다시 시도 뒤 준비
    monkeypatch.setattr(w.blackbox_tools, "prepare_close", blackbox_ready)
    caplog.set_level(logging.INFO)
    w._force_quit = True
    for _ in range(3):
        w.close()
    assert order.index("상태 저장") < order.index("올림 시작") < order.index("파티 정지") < order.index("올림 기다림")
    line = [r.getMessage() for r in caplog.records if r.getMessage().startswith("종료 요청 → 끝")][-1]
    assert "블랙박스 대기" in line and "다시 시도 2번" in line and "동기화 남은 기다림 12ms" in line
