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
