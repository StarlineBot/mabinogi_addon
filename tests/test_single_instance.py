"""단일 인스턴스 가드: 두 번째 인스턴스는 '이미 실행 중'으로 판정된다."""

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mabinogi_addon.system.single_instance import SingleInstance


def _app():
    # QApplication으로 — conftest의 자동 정리 픽스처가 topLevelWidgets를 부르므로 QCoreApplication이면
    # 이 파일만 돌리거나 같은 작업자에서 먼저 돌 때 다른 테스트까지 에러가 난다(0.55.8 QA).
    return QApplication.instance() or QApplication([])


def test_second_instance_detected():
    _app()
    key = "test_" + uuid.uuid4().hex
    first = SingleInstance(key)
    assert first.already_running is False  # 첫 인스턴스
    second = SingleInstance(key)
    assert second.already_running is True  # 두 번째 → 이미 실행 중
    # first 를 끝까지 살려 둬야 세그먼트가 유지된다(참조 유지).
    assert first._shm is not None


def test_distinct_keys_do_not_collide():
    _app()
    a = SingleInstance("test_" + uuid.uuid4().hex)
    b = SingleInstance("test_" + uuid.uuid4().hex)
    assert a.already_running is False
    assert b.already_running is False


# ---- 0.55.8(사용자 11-24): 다시 실행 → 켜진 창 앞으로, 업데이트 재실행 전 자리 비우기 ----

def test_second_launch_leaves_one_show_request():
    from mabinogi_addon.system.single_instance import request_show

    _app()
    key = "test_" + uuid.uuid4().hex
    first = SingleInstance(key)
    assert first.take_show_request() is False  # 새 자리는 요청 없음
    assert SingleInstance(key).already_running
    assert request_show(key) is True
    assert first.take_show_request() is True
    assert first.take_show_request() is False  # 한 번 읽으면 지워진다
    assert request_show("test_" + uuid.uuid4().hex) is False  # 켜진 앱이 없으면 남길 곳도 없다


def test_watch_shows_request_made_while_loading_and_later_ones():
    import time as _time

    from mabinogi_addon.system.single_instance import request_show

    app = _app()
    key = "test_" + uuid.uuid4().hex
    first = SingleInstance(key)
    request_show(key)  # 메인 창 전(로딩 중)에 들어온 요청
    shown = []
    first.watch(lambda: shown.append(1), interval_ms=20)
    assert shown == [1]  # 시작할 때 한 번 반영
    request_show(key)
    deadline = _time.monotonic() + 2
    while len(shown) < 2 and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.01)
    assert shown == [1, 1]
    first.release()
    request_show(key)  # 자리를 비운 뒤엔 무해
    for _ in range(5):
        app.processEvents()
        _time.sleep(0.03)
    assert shown == [1, 1]


def test_release_lets_new_process_take_the_slot_at_once():
    from mabinogi_addon.system import single_instance

    _app()
    key = "test_" + uuid.uuid4().hex
    old = single_instance.acquire(key=key)
    assert old is not None and single_instance._held is old
    assert single_instance.acquire(key=key) is None
    single_instance.release_held()
    assert single_instance._held is None
    new = single_instance.acquire(key=key)  # 기다림 없이(wait=0) 바로 잡힌다
    assert new is not None
    new.release()
    single_instance.release_held()


def test_update_relaunch_frees_slot_before_new_exe_starts(monkeypatch, tmp_path):
    """업데이트·다시 켜기: 새 exe가 뜨는 시점엔 옛 자리가 이미 비어 있어 새 프로세스가 가드를 잡는다."""
    import subprocess
    import sys

    from mabinogi_addon.system import single_instance, updater

    _app()
    key = "test_" + uuid.uuid4().hex
    assert single_instance.acquire(key=key) is not None
    seen = []

    def popen(args, **kwargs):
        guard = single_instance.SingleInstance(key)  # 새 프로세스 입장
        seen.append(guard.already_running)
        guard.release()

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "Popen", popen)
    updater._relaunch(tmp_path / "app.exe")
    assert seen == [False]


def test_show_request_restores_hidden_and_minimized_main_window():
    """요청을 받으면 트레이에서 여는 것과 같은 길(_show_from_tray)로 숨김·최소화 모두 앞으로."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget

    from mabinogi_addon.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])

    class Window(QWidget):
        _show_from_tray = MainWindow._show_from_tray

        def _maybe_check_update(self, reason):
            pass

    w = Window()
    try:
        w._show_from_tray()  # 트레이에 숨어 있던 창
        assert w.isVisible()
        w.showMinimized()
        w._show_from_tray()
        assert w.isVisible() and not (w.windowState() & Qt.WindowState.WindowMinimized)
    finally:
        w.close()


def test_just_updated_is_read_from_leftover_old_exe(monkeypatch, tmp_path):
    import sys

    from mabinogi_addon import paths
    from mabinogi_addon.system import updater

    exe = tmp_path / "app.exe"
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    assert updater.just_updated() is False
    (tmp_path / "app.exe.old").write_bytes(b"")
    assert updater.just_updated() is True
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    assert updater.just_updated() is False


def test_release_from_worker_thread_detaches_on_main_thread():
    """0.55.9(QA 11-24): 앱 안 업데이트 작업 스레드가 자리를 비워도 실제 비우기는 메인 스레드에서(타이머와 겹치지 않게)."""
    import threading
    import time as _time

    from mabinogi_addon.system import single_instance

    app = _app()
    key = "test_" + uuid.uuid4().hex
    guard = single_instance.SingleInstance(key)
    worker = threading.Thread(target=guard.release)
    worker.start()
    worker.join()
    assert guard._shm.isAttached()  # 작업 스레드에선 바로 안 뗌
    deadline = _time.monotonic() + 2
    while guard._shm.isAttached() and _time.monotonic() < deadline:
        app.processEvents()
    assert not guard._shm.isAttached()
    assert not single_instance.SingleInstance(key).already_running
