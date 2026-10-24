from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from mabinogi_addon import config
from mabinogi_addon.ui.blackbox_recovery import BlackboxRecovery
from mabinogi_addon.ui.main_window import MainWindow


def test_preferences_preserve_access_and_profile(tmp_path):
    path = tmp_path / 'config.json'
    config._write_local_config({'blackbox': {'enabled': True, 'validationProfile': {'x': 1}},
                               'other': {'keep': True}}, path)
    config.save_blackbox_preference('retentionMinutes', 7, path)
    config.save_blackbox_preference('outputFolder', str(tmp_path), path)
    assert config.load_blackbox_preferences(path) == {'retentionMinutes': 7, 'outputFolder': str(tmp_path)}
    assert config.load_blackbox_enabled(path)
    assert config.load_blackbox_profile(path) == {'x': 1}
    assert config._read_local_config(path)['other'] == {'keep': True}
    with pytest.raises(ValueError):
        config.save_blackbox_preference('retentionMinutes', 0, path)


def test_recovery_cancel_and_explicit_discard_are_separate(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime = object()
    cancelled, deleted = [], []
    service = SimpleNamespace(runtimes={}, _closing=False, _allowed=lambda: False,
        recoveries=lambda: [(runtime, 'running', None)], orphan_sources=lambda: ('orphan',),
        cancel_save=lambda r, t: cancelled.append((r,t)),
        spool=SimpleNamespace(discard=lambda t: deleted.append(t)))
    dialog = BlackboxRecovery(service)
    try:
        assert dialog.cancel.isEnabled() and not dialog.discard.isEnabled()
        assert not dialog.save_previous.isEnabled()
        dialog._cancel()
        assert cancelled == [(runtime, 'running')] and not deleted
        dialog.items.setCurrentIndex(1)
        assert not dialog.cancel.isEnabled() and dialog.discard.isEnabled()
        monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.No)
        dialog._discard()
        assert not deleted
        monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
        dialog._discard()
        assert deleted == ['orphan']
    finally:
        dialog.close(); dialog.deleteLater(); app.processEvents()


def test_update_waits_before_download_or_apply(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []
    host = SimpleNamespace(_pending_update={'version': 'test'}, _update_splash=None,
        blackbox_tools=SimpleNamespace(prepare_close=lambda: calls.append('drain') or False))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: calls.append('notice'))
    from mabinogi_addon.system import updater
    monkeypatch.setattr(updater, 'download', lambda *a, **k: pytest.fail('download before drain'))
    monkeypatch.setattr(updater, 'apply_update', lambda *a: pytest.fail('apply before drain'))
    MainWindow._on_update_clicked(host)
    assert calls == ['drain', 'notice']


def _recovery_service(entries, orphans, cleaned=0):
    return SimpleNamespace(runtimes={'1:2': object()}, _closing=False, _allowed=lambda: True,
        recoveries=lambda: list(entries), orphan_sources=lambda: tuple(orphans),
        retry_cleanup=lambda: cleaned, spool=SimpleNamespace(discard=lambda t: None))


def test_periodic_refresh_does_not_cancel_a_pressed_discard_click():
    """0.11.2 실사용: 100ms 갱신이 폐기 버튼을 껐다 켜 누르는 중 클릭이 취소됐다."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    orphans = ['0236988e' + 'f' * 24]
    dialog = BlackboxRecovery(_recovery_service([], orphans))
    try:
        dialog.show()
        clicked = []
        dialog.discard.clicked.disconnect()
        dialog.discard.clicked.connect(lambda: clicked.append(True))
        center = dialog.discard.rect().center()
        QTest.mousePress(dialog.discard, Qt.MouseButton.LeftButton, pos=center)
        for _ in range(3):
            dialog.refresh()
        QTest.mouseRelease(dialog.discard, Qt.MouseButton.LeftButton, pos=center)
        assert clicked == [True]
        # 내용이 바뀌면 다시 그리고 선택은 유지한다.
        orphans.append('a' * 32)
        dialog.refresh()
        assert dialog.items.count() == 2 and dialog.items.currentIndex() == 0
    finally:
        dialog.close(); dialog.deleteLater(); app.processEvents()


@pytest.mark.parametrize('cleaned, orphans, expected', [
    (2, ['o' * 32], ['원본 2건을 정리했어요.', '미완성 캡처 자료 1건은 앱을 닫을 때 자동으로 정리해요', '선택한 실패 자료 폐기']),
    (0, [], ['정리 대기 중인 원본이 없어요.']),
])
def test_cleanup_retry_reports_result_and_orphan_path(monkeypatch, cleaned, orphans, expected):
    app = QApplication.instance() or QApplication([])
    shown = []
    monkeypatch.setattr(QMessageBox, 'information', lambda parent, title, text: shown.append(text))
    dialog = BlackboxRecovery(_recovery_service([], orphans, cleaned))
    try:
        dialog._cleanup()
        assert len(shown) == 1 and all(part in shown[0] for part in expected)
        if not orphans:
            assert '미완성' not in shown[0]
    finally:
        dialog.close(); dialog.deleteLater(); app.processEvents()


def test_recovery_labels_use_times_not_internal_ids():
    from datetime import datetime
    from mabinogi_addon.ui.blackbox_recovery import clock_text, session_text
    now = datetime(2026, 10, 23, 18, 0)
    assert clock_text(datetime(2026, 10, 23, 15, 42).timestamp(), now) == '오후 3:42'
    assert clock_text(datetime(2026, 10, 23, 0, 5).timestamp(), now) == '오전 12:05'
    assert clock_text(datetime(2026, 10, 22, 9, 7).timestamp(), now) == '10월 22일 오전 9:07'
    created = int(datetime(2026, 10, 23, 15, 10).timestamp() * 10_000_000) + 116444736000000000
    assert session_text(f'28508:{created}', now) == '오후 3:10에 시작한 게임 실행'
    app = QApplication.instance() or QApplication([])
    runtime = SimpleNamespace(requested_at={'0236988e' + 'f' * 24: datetime.now().timestamp()})
    failed = SimpleNamespace(completed=False, error='encoder exited 1', cleanup_error=None)
    service = SimpleNamespace(runtimes={f'28508:{created}': runtime}, _closing=False, _allowed=lambda: True,
        recoveries=lambda: [(runtime, '0236988e' + 'f' * 24, failed)], orphan_sources=lambda: ('a' * 32,),
        spool=SimpleNamespace(created=lambda source: datetime.now().timestamp()))
    dialog = BlackboxRecovery(service)
    try:
        texts = [dialog.items.itemText(i) for i in range(dialog.items.count())] + [dialog.sessions.itemText(0)]
        assert texts[0].endswith('녹화 · 저장 실패') and texts[1].endswith('녹화 · 미완성 캡처 자료')
        assert not any('0236988e' in t or 'aaaa' in t or '28508' in t for t in texts)
        assert dialog.sessions.itemData(0) == f'28508:{created}'  # 저장 요청은 실행 ID로
    finally:
        dialog.close(); dialog.deleteLater(); app.processEvents()



def test_recording_stop_only_retries_close_and_update_without_recovery_window(monkeypatch):
    # 0.14.1: 녹화 중 종료·업데이트마다 저장 내역 창이 뜨고 취소되던 회귀. 녹화 중지만 남으면 창 없이 자동 재시도.
    from mabinogi_addon.ui.blackbox_controller import BlackboxController
    from mabinogi_addon.ui import main_window as module
    app = QApplication.instance() or QApplication([])
    shown = []
    c = BlackboxController.__new__(BlackboxController)
    c.panel = None
    c.service = SimpleNamespace(prepare_close=lambda: False, error=None, close_wait_reason=lambda: 'capture')
    monkeypatch.setattr(c, 'show_recovery', lambda: shown.append(1))
    assert c.prepare_close() is False and shown == [] and c.closing_capture_only()
    c.service.close_wait_reason = lambda: 'save'     # 저장 진행 중이면 기존처럼 복구 창
    c.prepare_close()
    assert shown == [1]
    # 업데이트: 녹화 중지만 남으면 다시 묻지 않고 200ms 뒤 이어서
    retries, asked = [], []
    monkeypatch.setattr(module.QTimer, 'singleShot', lambda ms, fn: retries.append(ms))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: asked.append(1) or QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: pytest.fail('capture-only must not ask to retry manually'))
    host = SimpleNamespace(_pending_update={'version': 'test'}, _update_splash=None, _on_update_clicked=lambda: None,
        blackbox_tools=SimpleNamespace(prepare_close=lambda: False, closing_capture_only=lambda: True))
    MainWindow._on_update_clicked(host)
    assert retries == [200] and asked == [1] and host._update_retry_until is not None
    MainWindow._on_update_clicked(host)              # 재시도는 다시 묻지 않는다
    assert asked == [1] and retries == [200, 200]


def test_service_close_reason_separates_capture_from_saves():
    from mabinogi_addon.blackbox_service import BlackboxService
    s = BlackboxService.__new__(BlackboxService)
    s._pending, s.runtimes, s.producer = {}, {}, object()
    assert s.close_wait_reason() == 'capture'
    s._pending = {'t': 1}
    assert s.close_wait_reason() == 'save'
    s._pending, s.producer = {}, None
    assert s.close_wait_reason() is None
