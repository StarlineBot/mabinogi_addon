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
    (2, ['o' * 32], ['원본 2건을 정리했어요.', '미완성 캡처 자료 1건은 자동으로 지우지 않아요', '선택한 실패 자료 폐기']),
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
