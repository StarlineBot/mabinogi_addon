"""Independent real-UI compression checks using synthetic files and no relay calls."""
import io
import json
import random
import threading
import time
import zipfile

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, paths, settings_sync
from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
from mabinogi_addon.ui import settings_tab as module


@pytest.mark.parametrize('mode', ['file', 'discord'])
def test_real_compression_keeps_ui_alive(tmp_path, monkeypatch, mode):
    app = QApplication.instance() or QApplication([])
    user = tmp_path / 'userdata'
    asset = user / 'buff' / 'icon' / 'synthetic.png'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(random.Random(73).randbytes((24 if mode == 'file' else 4) * 1024 * 1024))
    cfg = user / 'config.local.json'
    cfg.write_text('{}', encoding='utf-8')
    real_read = config._read_local_config
    monkeypatch.setattr(config, '_read_local_config', lambda *a, **k: real_read(cfg))
    monkeypatch.setattr(config, 'LOCAL_CONFIG_PATH', cfg)
    monkeypatch.setattr(paths, 'user_data_dir', lambda: user)
    monkeypatch.setattr(config, 'load_discord_user', lambda: {'id': 'synthetic', 'name': 'test'})
    monkeypatch.setattr(config, 'get_nexon_api_key', lambda: None)
    monkeypatch.setattr(config, 'get_config_webhook_url', lambda: 'https://invalid.example/never-contacted')
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *a: (str(tmp_path / 'backup.zip'), ''))
    messages, sent, ticks, evidence = [], [], [], {}
    monkeypatch.setattr(module.QMessageBox, 'information', lambda *a: messages.append(a[-1]))
    monkeypatch.setattr(module.QMessageBox, 'warning', lambda *a: messages.append(a[-1]))

    def relay(url, account, filename, **kwargs):
        with zipfile.ZipFile(filename) as archive:
            sent.append(archive.namelist())

    monkeypatch.setattr(settings_sync, 'send_config_backup_file', relay)
    ui_id = threading.get_ident()
    original = config._write_bundle

    def compress(*args, **kwargs):
        evidence['ui_thread'] = threading.get_ident() == ui_id
        before = len(ticks)
        start = time.monotonic()
        result = original(*args, **kwargs)
        evidence['seconds'] = round(time.monotonic() - start, 3)
        evidence['heartbeat_during_compression'] = len(ticks) - before
        return result

    monkeypatch.setattr(config, '_write_bundle', compress)
    host = module.SettingsTab(AlwaysActiveWatcher())
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    try:
        (host._on_export_config if mode == 'file' else host._on_export_discord)()
        deadline = time.monotonic() + 10
        while host._export_thread is not None and time.monotonic() < deadline:
            app.processEvents()
            threading.Event().wait(.001)
        assert host._export_thread is None, 'worker did not finish'
        assert evidence['ui_thread'] is False, evidence
        assert evidence['heartbeat_during_compression'] > 0, evidence
        names = sent[0] if mode == 'discord' else zipfile.ZipFile(tmp_path / 'backup.zip').namelist()
        assert 'userdata/buff/icon/synthetic.png' in names
        assert messages and host._file_export_btn.isEnabled()
        print(mode, evidence)
    finally:
        timer.stop()
        if host._export_thread is not None:
            host.prepare_close()
            worker = host._export_thread
            worker.wait(5000)
            app.processEvents()
        host.shutdown()
        host.close()
        host.deleteLater()
        app.processEvents()


def test_all_secret_copies_are_excluded_and_assets_round_trip(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    cfg = root / 'config.local.json'
    secrets = {name: 'SYNTHETIC-' + name for name in ('nexonApiKey', 'inquiryWebhookUrl', 'configWebhookUrl')}
    config._write_local_config(dict(secrets, memo={'text': 'keep'}), cfg)
    config._write_local_config(dict(secrets, memo={'text': 'keep'}), cfg)
    (root / 'config.local.json.tmp').write_text(json.dumps(secrets), encoding='utf-8')
    (root / 'renamed-settings.json').write_text(json.dumps(secrets), encoding='utf-8')
    asset = root / 'buff' / 'icon' / 'custom.png'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b'SYNTHETIC-ICON')
    payload = config.export_bundle_bytes(cfg, root)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {'config.json', 'userdata/buff/icon/custom.png'}
        assert all(value.encode() not in archive.read(name) for value in secrets.values() for name in archive.namelist())
    backup = tmp_path / 'backup.zip'
    backup.write_bytes(payload)
    target = tmp_path / 'target'
    target.mkdir()
    target_cfg = target / 'config.local.json'
    config._write_local_config({name: 'TARGET-' + name for name in secrets}, target_cfg)
    config.import_bundle(backup, target_cfg, target)
    restored = config._read_local_config(target_cfg)
    assert all(restored[name] == 'TARGET-' + name for name in secrets)
    assert restored['memo'] == {'text': 'keep'}
    assert (target / 'buff/icon/custom.png').read_bytes() == b'SYNTHETIC-ICON'
