"""UI compression and automatic-backup privacy regressions from 2026-10-21 QA."""
import io
import random
import threading
import time
import zipfile
import json
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from mabinogi_addon import config,paths,settings_sync
from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
from mabinogi_addon.ui import settings_tab as module


def spin(app, condition, seconds=5):
    deadline=time.monotonic()+seconds
    while not condition() and time.monotonic()<deadline:
        app.processEvents()
        threading.Event().wait(.002)
    assert condition(), 'export did not reach its completion condition'


@pytest.mark.parametrize('destination',['file','discord'])
def test_bundle_compression_does_not_run_on_ui_thread(tmp_path,monkeypatch,destination):
    app=QApplication.instance() or QApplication([])
    user=tmp_path/'userdata';asset=user/'buff'/'icon'/'synthetic.png'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(random.Random(73).randbytes(4*1024*1024))
    diagnostic=user/'halo_timer_shots'/'old.bin';diagnostic.parent.mkdir();diagnostic.write_bytes(b'diagnostic')
    cfg=user/'config.local.json';cfg.write_text('{}',encoding='utf-8')
    monkeypatch.setattr(config,'LOCAL_CONFIG_PATH',cfg)
    monkeypatch.setattr(paths,'user_data_dir',lambda:user)
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':'synthetic','name':'test'})
    monkeypatch.setattr(config,'get_config_webhook_url',lambda:'https://invalid.example/not-contacted')
    messages=[];sent=[]
    monkeypatch.setattr(module.QMessageBox,'information',lambda *a:messages.append(a[-1]))
    monkeypatch.setattr(module.QMessageBox,'warning',lambda *a:messages.append(a[-1]))
    monkeypatch.setattr(module.QFileDialog,'getSaveFileName',lambda *a:(str(tmp_path/'backup.zip'),''))
    def send(webhook,user_id,path,**kw):
        sent.append(zipfile.ZipFile(path).namelist())
    monkeypatch.setattr(settings_sync,'send_config_backup_file',send)
    host=module.SettingsTab(AlwaysActiveWatcher())
    started,release=threading.Event(),threading.Event();heartbeat=[];evidence={}
    ui_thread_id=threading.get_ident()
    original=config._write_bundle
    def measured(*a,**kw):
        evidence['ui_thread']=threading.get_ident()==ui_thread_id
        started.set()
        assert release.wait(3), 'UI never released worker'
        return original(*a,**kw)
    monkeypatch.setattr(config,'_write_bundle',measured)
    QTimer.singleShot(0,lambda:heartbeat.append('processed'))
    try:
        (host._on_export_config if destination=='file' else host._on_export_discord)()
        spin(app,started.is_set)
        assert heartbeat and host._export_busy()
        assert not host._file_export_btn.isEnabled() and not host._dm_export_btn.isEnabled()
        assert evidence['ui_thread'] is False,evidence
        release.set()
        spin(app,lambda:host._export_thread is None)
        assert messages and host._file_export_btn.isEnabled() and host._dm_export_btn.isEnabled()
        names=sent[0] if destination=='discord' else zipfile.ZipFile(tmp_path/'backup.zip').namelist()
        assert 'userdata/buff/icon/synthetic.png' in names
        assert not any('halo_timer_shots' in name for name in names)
        if destination=='discord': assert '접수' in messages[0] and 'DM 도착' in messages[0]
    finally:
        release.set()
        if host._export_thread is not None:
            host.prepare_close();spin(app,lambda:host._export_thread is None)
        host.shutdown();host.close();host.deleteLater();app.processEvents()


def test_automatic_recovery_backup_does_not_export_secrets(tmp_path):
    cfg=tmp_path/'config.local.json'
    data={'nexonApiKey':'SYNTHETIC-NOT-A-REAL-KEY',
          'inquiryWebhookUrl':'https://invalid.example/synthetic-secret',
          'buffTracker':{'enabled':True}}
    config._write_local_config(data,cfg)
    config._write_local_config(dict(data,general={'theme':'dark'}),cfg)
    assert cfg.with_name(cfg.name+'.bak').exists()
    payload=config.export_bundle_bytes(path=cfg,user_dir=tmp_path)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert 'nexonApiKey' not in json.loads(archive.read('config.json'))
        exposed=[]
        for name in archive.namelist():
            body=archive.read(name)
            if any(value.encode() in body for key,value in data.items() if key in config._SECRET_KEYS): exposed.append(name)
    assert not exposed,exposed
