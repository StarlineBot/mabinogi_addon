"""Explicit QA probes. Synthetic local files only; Discord is never contacted."""
import io
import json
import random
import time
import zipfile

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from mabinogi_addon import config, settings_sync
from mabinogi_addon.ui import settings_tab as module


@pytest.mark.parametrize('destination', ['file', 'discord'])
def test_bundle_compression_does_not_run_on_ui_thread(tmp_path, monkeypatch, destination):
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host._dm_export_btn = QPushButton('export', host)
    host._on_dm_result = lambda *args: None
    user_dir = tmp_path / 'userdata'
    shots = user_dir / 'halo_timer_shots' / 'synthetic-session'
    shots.mkdir(parents=True)
    (shots / 'synthetic.bin').write_bytes(random.Random(73).randbytes(24 * 1024 * 1024))
    cfg = user_dir / 'config.local.json'
    cfg.write_text('{}', encoding='utf-8')
    real_export = config.export_bundle_bytes
    evidence = {}
    heartbeat = []

    def measured_export(*args, **kwargs):
        evidence['ui_thread'] = QThread.currentThread() == app.thread()
        evidence['heartbeat_before'] = len(heartbeat)
        start = time.monotonic()
        result = real_export(path=cfg, user_dir=user_dir)
        evidence['seconds'] = round(time.monotonic() - start, 3)
        evidence['heartbeat_after'] = len(heartbeat)
        evidence['zip_bytes'] = len(result)
        return result

    monkeypatch.setattr(config, 'export_bundle_bytes', measured_export)
    monkeypatch.setattr(config, 'load_discord_user', lambda: {'id': 'synthetic', 'name': 'test'})
    monkeypatch.setattr(config, 'get_config_webhook_url', lambda: 'https://invalid.example/never-contacted')
    monkeypatch.setattr(settings_sync, 'send_config_backup', lambda *args, **kwargs: None)
    monkeypatch.setattr(module.QMessageBox, 'information', lambda *args: None)
    monkeypatch.setattr(module.QMessageBox, 'warning', lambda *args: None)
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *args: (str(tmp_path / 'backup.zip'), ''))
    QTimer.singleShot(0, lambda: heartbeat.append('processed'))
    try:
        if destination == 'file':
            module.SettingsTab._on_export_config(host)
        else:
            module.SettingsTab._on_export_discord(host)
            assert host._export_thread.wait(3000)
        app.processEvents()
        assert heartbeat
        assert evidence['ui_thread'] is False, evidence
    finally:
        worker = getattr(host, '_export_thread', None)
        if worker is not None:
            worker.wait(3000)
        host.close()
        host.deleteLater()
        app.processEvents()


def test_automatic_recovery_backup_does_not_export_secrets(tmp_path):
    # In frozen builds the configuration and user data live in the same folder.
    cfg = tmp_path / 'config.local.json'
    data = {'nexonApiKey': 'SYNTHETIC-NOT-A-REAL-KEY',
            'inquiryWebhookUrl': 'https://invalid.example/synthetic-secret',
            'buffTracker': {'enabled': True}}
    config._write_local_config(data, cfg)
    config._write_local_config(dict(data, general={'theme': 'dark'}), cfg)
    assert cfg.with_name(cfg.name + '.bak').exists()
    payload = config.export_bundle_bytes(path=cfg, user_dir=tmp_path)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert 'nexonApiKey' not in json.loads(archive.read('config.json'))
        exposed = []
        for name in archive.namelist():
            body = archive.read(name)
            if any(value.encode() in body for key, value in data.items() if key in config._SECRET_KEYS):
                exposed.append(name)
    assert not exposed, exposed
