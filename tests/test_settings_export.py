"""Bounded private asset bundles, async UI lifetime and streamed relay boundaries."""
import io
import json
import os
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication,QEvent
from shiboken6 import isValid
from mabinogi_addon import config,paths,settings_sync
from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
from mabinogi_addon.ui import settings_tab as module
from test_support.regressions.settings_export import (
    spin,test_bundle_compression_does_not_run_on_ui_thread,
    test_automatic_recovery_backup_does_not_export_secrets,
)


@pytest.fixture
def source(tmp_path):
    root=tmp_path/'userdata';root.mkdir();cfg=root/'config.local.json'
    config._write_local_config({'nexonApiKey':'SYNTHETIC-SECRET','inquiryWebhookUrl':'SECRET-WEBHOOK','configWebhookUrl':'SECRET-RELAY','buffTracker':{'enabled':True}},cfg)
    config._write_local_config(config._read_local_config(cfg),cfg)
    for folder in config._BUNDLE_ASSET_DIRS:
        p=root/folder/'한글.png';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'PNG-ASSET')
    return root,cfg


def test_export_allowlist_keeps_assets_but_never_settings_copies_or_diagnostics(source):
    root,cfg=source
    for name in ('config.local.json.tmp','copy.json','.env','old.zip','logs/x.log','autofind_diagnostics/run/input.png',
                 'halo_timer_shots/shot.png','frame_recordings/frames.csv','buff/icon/copied.json','buff/icon/nested/raw.json'):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('SYNTHETIC-SECRET',encoding='utf-8')
    backup=cfg.with_name(cfg.name+'.bak').read_bytes()
    with zipfile.ZipFile(io.BytesIO(config.export_bundle_bytes(cfg,root))) as archive:
        assert set(archive.namelist())=={'config.json',*(f'userdata/{rel}/한글.png' for rel in config._BUNDLE_ASSET_DIRS)}
        assert all(secret not in archive.read(name) for name in archive.namelist()
                   for secret in (b'SYNTHETIC-SECRET',b'SECRET-WEBHOOK',b'SECRET-RELAY'))
    assert cfg.with_name(cfg.name+'.bak').read_bytes()==backup


def test_legacy_zip_restores_assets_without_reintroducing_raw_config(source,tmp_path):
    root,cfg=source;bundle=tmp_path/'old.zip'
    with zipfile.ZipFile(bundle,'w') as archive:
        archive.writestr('config.json','{"partyKeywords":["hello"],"nexonApiKey":"DO-NOT-IMPORT"}')
        archive.writestr('userdata/buff/icon/old.png',b'OLD-ICON')
        archive.writestr('userdata/config.local.json','{"nexonApiKey":"BAD"}')
        archive.writestr('userdata/config.local.json.bak','{"nexonApiKey":"BAD"}')
        archive.writestr('userdata/debug/input.png',b'DIAGNOSTIC')
    config.import_bundle(bundle,cfg,root)
    assert config._read_local_config(cfg)['nexonApiKey']=='SYNTHETIC-SECRET'
    assert config._read_local_config(cfg)['partyKeywords']==['hello']
    assert (root/'buff/icon/old.png').read_bytes()==b'OLD-ICON'
    assert not (root/'debug').exists()


@pytest.mark.parametrize('limits',[
    config.BundleLimits(max_files=1),config.BundleLimits(max_source_bytes=10),
    config.BundleLimits(max_config_bytes=5),config.BundleLimits(max_zip_bytes=20),
    config.BundleLimits(max_seconds=-1),
])
def test_limits_preserve_existing_destination_and_cleanup_temporary(source,tmp_path,limits):
    root,cfg=source;dest=tmp_path/'backup.zip';dest.write_bytes(b'PREVIOUS-BACKUP')
    with pytest.raises(ValueError): config.export_bundle(dest,cfg,root,limits=limits)
    assert dest.read_bytes()==b'PREVIOUS-BACKUP' and not list(tmp_path.glob('.settings-export-*'))


def test_source_limit_fails_before_any_compression(source,tmp_path,monkeypatch):
    root,cfg=source
    def forbidden(*a,**kw): pytest.fail('compression started despite preflight budget')
    monkeypatch.setattr(zipfile,'ZipFile',forbidden)
    with pytest.raises(ValueError): config.export_bundle(tmp_path/'out.zip',cfg,root,limits=config.BundleLimits(max_source_bytes=4))


@pytest.mark.parametrize('phase',['enumerate','copy','replace'])
def test_cancel_preserves_previous_zip_and_removes_temporary(source,tmp_path,monkeypatch,phase):
    root,cfg=source;dest=tmp_path/'backup.zip';dest.write_bytes(b'PREVIOUS')
    cancelled=threading.Event()
    if phase=='enumerate': cancelled.set()
    elif phase=='copy':
        original=zipfile.ZipFile.open
        def stop(self,*a,**kw):
            stream=original(self,*a,**kw)
            if a and str(a[0]).startswith('userdata/'): cancelled.set()
            return stream
        monkeypatch.setattr(zipfile.ZipFile,'open',stop)
    else:
        original=os.fsync
        def stop(fd): original(fd);cancelled.set()
        monkeypatch.setattr(os,'fsync',stop)
    with pytest.raises(config.BundleCancelled): config.export_bundle(dest,cfg,root,cancelled=cancelled.is_set)
    assert dest.read_bytes()==b'PREVIOUS' and not list(tmp_path.glob('.settings-export-*'))


def test_failed_save_and_asset_replacement_preserve_original(source,tmp_path,monkeypatch):
    root,cfg=source;dest=tmp_path/'backup.zip';dest.write_bytes(b'PREVIOUS')
    original=os.open
    def replace_asset(path,*a,**kw):
        path=Path(path)
        if path.suffix=='.png': path.unlink();path.write_bytes(b'NEW-CONTENT')
        return original(path,*a,**kw)
    monkeypatch.setattr(os,'open',replace_asset)
    with pytest.raises(ValueError,match='바뀌'): config.export_bundle(dest,cfg,root)
    assert dest.read_bytes()==b'PREVIOUS' and not list(tmp_path.glob('.settings-export-*'))


@pytest.mark.parametrize('pathkind',['file','folder','windows-reparse'])
def test_asset_links_are_rejected_without_reading_target(source,monkeypatch,pathkind):
    root,cfg=source
    original=config._is_link
    target=root/('buff/icon/한글.png' if pathkind=='file' else 'buff/icon')
    if pathkind=='windows-reparse':
        assert config._is_link(SimpleNamespace(lstat=lambda:SimpleNamespace(st_mode=0,st_file_attributes=0x400)))
    monkeypatch.setattr(config,'_is_link',lambda path:path==target or original(path))
    with pytest.raises(ValueError,match='연결'): config.export_bundle_bytes(cfg,root)


@pytest.mark.parametrize('suffix',['','.bak','.tmp','.bak.tmp'])
def test_config_and_recovery_files_cannot_be_export_destination(source,suffix):
    root,cfg=source
    dest=cfg.with_name(cfg.name+suffix)
    before=dest.read_bytes() if dest.exists() else None
    with pytest.raises(ValueError): config.export_bundle(dest,cfg,root)
    assert (dest.read_bytes() if dest.exists() else None)==before


@pytest.fixture
def panel(source,monkeypatch):
    app=QApplication.instance() or QApplication([]);root,cfg=source
    account={'id':'one','name':'test'};messages=[]
    monkeypatch.setattr(config,'LOCAL_CONFIG_PATH',cfg)
    monkeypatch.setattr(paths,'user_data_dir',lambda:root)
    monkeypatch.setattr(config,'load_discord_user',lambda:account.copy() if account else None)
    monkeypatch.setattr(config,'get_config_webhook_url',lambda:'https://invalid.example/not-contacted')
    monkeypatch.setattr(module.QMessageBox,'information',lambda *a:messages.append(a[-1]))
    monkeypatch.setattr(module.QMessageBox,'warning',lambda *a:messages.append(a[-1]))
    widget=module.SettingsTab(AlwaysActiveWatcher())
    try: yield app,widget,account,messages
    finally:
        if isValid(widget):
            if widget._export_thread is not None:
                widget.prepare_close();spin(app,lambda:widget._export_thread is None)
            widget.shutdown();widget.close();widget.deleteLater();app.processEvents()


def held_export(monkeypatch):
    started,release=threading.Event(),threading.Event();original=config._write_bundle
    def held(*a,**kw):
        started.set();assert release.wait(3)
        return original(*a,**kw)
    monkeypatch.setattr(config,'_write_bundle',held)
    return started,release


def test_busy_export_blocks_duplicate_import_and_reset(panel,tmp_path,monkeypatch):
    app,w,account,messages=panel;started,release=held_export(monkeypatch)
    monkeypatch.setattr(module.QFileDialog,'getSaveFileName',lambda *a:(str(tmp_path/'out.zip'),''))
    monkeypatch.setattr(module.QFileDialog,'getOpenFileName',lambda *a:pytest.fail('import opened during export'))
    try:
        w._on_export_config();spin(app,started.is_set);worker=w._export_thread
        w._on_export_config();w._on_export_discord();w._on_import_config();w._on_reset_config()
        assert w._export_thread is worker and not w._import_btn.isEnabled() and not w._reset_btn.isEnabled()
    finally: release.set()
    spin(app,lambda:w._export_thread is None)
    assert w._import_btn.isEnabled() and w._reset_btn.isEnabled()


@pytest.mark.parametrize('transition',['close','logout'])
def test_close_or_account_change_cancels_before_send_and_suppresses_stale_result(panel,monkeypatch,transition):
    app,w,account,messages=panel;started,release=held_export(monkeypatch)
    monkeypatch.setattr(settings_sync,'send_config_backup_file',lambda *a,**kw:pytest.fail('cancelled export reached relay'))
    try:
        w._on_export_discord();spin(app,started.is_set)
        if transition=='close': assert w.prepare_close() is False
        else: account.clear();w._refresh_login()
    finally: release.set()
    spin(app,lambda:w._export_thread is None)
    assert not messages
    if transition=='close': assert w.prepare_close() is True
    else: assert w._file_export_btn.isEnabled() and not w._dm_export_btn.isEnabled()


def test_compression_failure_restores_buttons_and_reports_failure(panel,tmp_path,monkeypatch):
    app,w,account,messages=panel
    def fail(*a,**kw): raise OSError('synthetic disk full')
    monkeypatch.setattr(config,'export_bundle',fail)
    w._start_export(tmp_path/'out.zip')
    spin(app,lambda:w._export_thread is None)
    assert w._file_export_btn.isEnabled() and w._import_btn.isEnabled()
    assert len(messages)==1 and '실패' in messages[0]


def test_streamed_relay_uses_bounded_file_and_correct_content_length(tmp_path):
    file=tmp_path/'bundle.zip';file.write_bytes(b'PK\x03\x04synthetic');seen={}
    class Response:
        status=204
        def __enter__(self): return self
        def __exit__(self,*a): pass
    def send(request,timeout):
        assert not isinstance(request.data,bytes)
        body=request.data.read();seen['body']=body
        assert int(request.get_header('Content-length'))==len(body)
        assert timeout==5
        return Response()
    settings_sync.send_config_backup_file('https://invalid.example','123',file,urlopen=send)
    assert b'<@123>' in seen['body'] and file.read_bytes() in seen['body']


@pytest.mark.parametrize('failure',['oversize','cancel','server413','network'])
def test_relay_limits_and_transport_errors_are_safe(tmp_path,failure):
    import urllib.error
    file=tmp_path/'bundle.zip';file.write_bytes(b'x'*32);calls=[]
    def send(*a,**kw):
        calls.append(None)
        if failure=='server413': raise urllib.error.HTTPError('https://secret-token.invalid',413,'too large',{},None)
        raise urllib.error.URLError('private-webhook-URL')
    with pytest.raises((ValueError,config.BundleCancelled)) as caught:
        settings_sync.send_config_backup_file('https://invalid.example','123',file,urlopen=send,
            upload_budget=16 if failure=='oversize' else 64,cancelled=lambda:failure=='cancel')
    assert 'secret-token' not in str(caught.value) and 'private-webhook' not in str(caught.value)
    if failure in ('oversize','cancel'): assert not calls


def test_destroyed_panel_cancels_worker_without_destroying_running_qthread(panel,monkeypatch):
    app,w,account,messages=panel;started,release=held_export(monkeypatch)
    monkeypatch.setattr(settings_sync,'send_config_backup_file',lambda *a,**kw:pytest.fail('destroyed panel sent request'))
    try:
        w._on_export_discord();spin(app,started.is_set);worker=w._export_thread
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert not isValid(w) and worker.isInterruptionRequested()
    finally: release.set()
    spin(app,lambda:not isValid(worker) or not worker.isRunning())
    app.processEvents()
    assert not messages


def test_permission_or_disk_error_does_not_publish_partial_zip(source,tmp_path,monkeypatch):
    root,cfg=source;dest=tmp_path/'out.zip';dest.write_bytes(b'PREVIOUS')
    original=os.replace
    def denied(src,target):
        if Path(target)==dest: raise PermissionError('synthetic read-only destination')
        original(src,target)
    monkeypatch.setattr(os,'replace',denied)
    with pytest.raises(PermissionError): config.export_bundle(dest,cfg,root)
    assert dest.read_bytes()==b'PREVIOUS' and not list(tmp_path.glob('.settings-export-*'))
