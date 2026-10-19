"""One-shot upper timer finding, native boundaries and approval-only setup."""

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox

from mabinogi_addon import config, image_io, setup_state, autofind_diagnostics as diag
from mabinogi_addon.autofind_replay import detector_assets,run_detector,replay
from mabinogi_addon.detect.halo_timer import read_seconds
from mabinogi_addon.system import window_capture
from mabinogi_addon.ui import autofind_confirm, screen_grab
from mabinogi_addon.ui import setup_flow
from test_halo_presentation import creator_section,window
from test_halo_timer import frame as timer_frame


@pytest.fixture
def storage(tmp_path,monkeypatch):
    store = diag.DiagnosticStore(tmp_path/'진단')
    monkeypatch.setattr(diag,'_store',store)
    yield store
    store.io.close()


def canvas(*, multiple=False, bottom=False):
    result = np.zeros((600,1000,3),np.uint8)
    y = 450 if bottom else 70
    result[y:y+42,440:559] = timer_frame(1)
    if multiple:
        result[y:y+42,600:719] = timer_frame(2)
    return result


@pytest.mark.parametrize('index',[1,2,33,48,74])
def test_various_values_find_all_digits_and_colon(index):
    source = canvas()
    source[70:112,440:559] = timer_frame(index)
    trace = {}
    box = run_detector('halo_timer',source,detector_assets('halo_timer'),trace)
    assert box is not None
    x,y,w,h = box
    assert read_seconds(source[y:y+h,x:x+w])==read_seconds(timer_frame(index))
    assert trace['search_region']==[250,0,500,150]


def test_full_game_original_and_zip_replay_use_same_pixels(storage,tmp_path,monkeypatch):
    source = image_io.imread(Path(__file__).parent/'data/스크린샷 2026-10-09 185247.png')
    _,_,_,box = diag.perform_autofind('halo_timer',lambda:(source,-1920,100),storage=storage)
    assert box is not None
    x,y,w,h = box
    assert read_seconds(source[y:y+h,x:x+w])==897
    storage.io.wait()
    record = storage.recent()[0]
    archive = storage.export(record,tmp_path/'한글 경로'/'헤일로.zip')
    monkeypatch.setattr('mabinogi_addon.detect.halo_timer.references',lambda:pytest.fail('replay must use ZIP assets'))
    result = replay(archive)
    assert result['replayed'] and result['matches_recorded']
    assert record.metadata['result_global_physical']==[x-1920,y+100,w,h]


@pytest.mark.parametrize('mode',['multiple','bottom','blank'])
def test_missing_or_multiple_timers_never_choose_one(mode):
    source = canvas(multiple=mode=='multiple',bottom=mode=='bottom')
    if mode=='blank':
        source[:]=0
    assert run_detector('halo_timer',source,detector_assets('halo_timer'),{}) is None


@pytest.mark.parametrize('mode',['ok','wrong_foreground','changed_process','changed_geometry'])
def test_strict_capture_has_no_desktop_fallback(monkeypatch,mode):
    target = (11,22,-1900,80,1000,600)
    calls = []
    def registered(previous=None):
        if previous is not None and mode=='changed_process':
            return (11,33,*target[2:])
        if previous is not None and mode=='changed_geometry':
            return (11,22,-1900,80,900,600)
        return target
    monkeypatch.setattr(window_capture,'registered_game_target',registered)
    monkeypatch.setitem(sys.modules,'win32gui',SimpleNamespace(
        GetForegroundWindow=lambda:99 if mode=='wrong_foreground' else 11,IsIconic=lambda *a:False))
    monkeypatch.setattr(screen_grab,'_grab_mon',lambda mon:(calls.append(mon),canvas())[1])
    token = diag.capture_info.set({})
    try:
        frame,x,y = screen_grab._grab_foreground_game()
        assert (frame is not None)==(mode=='ok')
        if frame is not None:
            assert (x,y)==(-1900,80) and diag.capture_info.get()['game_target']==list(target)
        assert len(calls)==(0 if mode=='wrong_foreground' else 1)
    finally:
        diag.capture_info.reset(token)


@pytest.mark.parametrize('outcome',['yes','no','logout','target_change','clear','save_error'])
def test_approval_is_transactional(window,monkeypatch,storage,outcome):
    _,_,s = creator_section(window,monkeypatch)
    before = dict(s._region)
    target = (11,22,-1900,80,1000,600)
    calls = []
    original_write = config._write_local_config
    def capture(**kwargs):
        assert kwargs['strict_game'] and kwargs['require_game']
        calls.append(True)
        diag.capture_info.get()['game_target']=list(target)
        return canvas(),-1900,80
    monkeypatch.setattr(screen_grab,'capture_for_autofind',capture)
    monkeypatch.setattr(window_capture,'registered_game_target',lambda *a:target)
    monkeypatch.setattr(autofind_confirm,'to_logical',lambda x,y,w,h:(x//2,y//2,w//2,h//2))
    def approve(*a,**k):
        if outcome=='logout':
            monkeypatch.setattr(config,'load_discord_user',lambda:None)
        elif outcome=='target_change':
            monkeypatch.setattr(window_capture,'registered_game_target',lambda *a:None)
        elif outcome=='clear':
            s._persist(None)
        elif outcome=='save_error':
            def fail(*a,**k): raise PermissionError('controlled')
            monkeypatch.setattr(config,'_write_local_config',fail)
        return QMessageBox.StandardButton.No if outcome=='no' else QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox,'question',approve)
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:None)
    try:
        s._on_auto_find()
    finally:
        monkeypatch.setattr(config,'_write_local_config',original_write)
    assert len(calls)==1 and not s._autofind_busy and s._autofind_highlight is None
    if outcome=='yes':
        assert s._region != before and s._region['x']<0
    elif outcome=='clear':
        assert s._region is None
    else:
        assert s._region==before


def test_setup_selection_dependency_and_navigation(window,monkeypatch):
    w,app = window
    raw = config._read_local_config()
    assert setup_state.missing('halo_timer',raw)==['boss','halo_timer']
    setup_state.save_selection('halo_timer',True)
    assert setup_state.pending(feature_keys=('halo_timer',),automatic_only=True)==['boss','halo_timer']
    w.setup_guide.stage=1
    w.setup_guide.refresh()
    keys = list(w.setup_guide.checks)
    assert keys.index('halo_timer')==keys.index('boss')+1
    assert w.setup_guide.checks['halo_timer'].isChecked()
    assert w._open_setup_feature('halo_timer')
    assert w.boss_tab.pattern_tabs.currentIndex()==1
    w._apply_setup_region('boss',(0,0,300,30))
    assert setup_state.pending(feature_keys=('halo_timer',))==['halo_timer']
    w._apply_setup_region('halo_timer',(440,70,119,42))
    assert setup_state.missing('halo_timer')==[]
    w.setup_guide.refresh()
    assert w.setup_guide.statuses['halo_timer'].text()=='등록됨'
    w.setup_page.refresh()
    assert w.setup_page.feature_rows['halo_timer'][1].text()=='영역 등록됨'


def test_window_position_write_failure_cannot_abort_shutdown(window,monkeypatch):
    w,_ = window
    def denied(*a,**k): raise PermissionError('controlled position write failure')
    with monkeypatch.context() as fault:
        fault.setattr(config,'save_window_pos',denied)
        w._force_quit=True
        w.close()
    assert w._closing and not w.boss_tab.halo_capture._timer.isActive()


@pytest.mark.parametrize('choice',['accept','reject_halo','target_change'])
def test_sequential_setup_registers_boss_before_timer(window,monkeypatch,storage,choice):
    w,_ = window
    raw = config._read_local_config()
    raw.setdefault('general',{})['gameExe']='Client.exe'
    config._write_local_config(raw)
    setup_state.save_selection('halo_timer',True)
    target = (11,22,0,0,1000,600)
    captures,approvals = [],[]
    def capture(**kwargs):
        captures.append(kwargs)
        diag.capture_info.get()['game_target']=list(target)
        return canvas(),0,0
    def approve(key,box):
        approvals.append(key)
        if key=='halo_timer' and choice=='reject_halo':
            return None
        if key=='halo_timer' and choice=='target_change':
            monkeypatch.setattr(window_capture,'registered_game_target',lambda *a:None)
        return box
    monkeypatch.setattr(window_capture,'registered_game_target',lambda *a:target)
    monkeypatch.setattr(setup_flow,'capture_for_autofind',capture)
    monkeypatch.setattr(w._setup_flow,'_approve',approve)
    monkeypatch.setattr(w._setup_flow,'_detect',lambda key,*args:(10,250,300,30) if key=='boss' else (440,70,119,42))
    monkeypatch.setattr(w._setup_flow,'_notice',lambda *a:None)
    results = []
    w.setup_guide.stage=1
    w._setup_flow.run(page=w.setup_guide,feature_keys=('halo_timer',),on_result=lambda *args:results.append(args))
    assert approvals==['boss','halo_timer']
    assert 'strict_game' not in captures[0] and captures[1]['strict_game']
    assert setup_state.valid_box(config.load_boss_bar_region())
    assert (w.boss_tab.halo_capture._region is not None)==(choice=='accept')
    assert not w.setup_guide.busy and not w._setup_flow.running
    assert [key for key,status in results]==['boss','halo_timer']


def test_capture_revocation_before_native_read_never_grabs(window,monkeypatch):
    monkeypatch.setattr(screen_grab,'_mss',lambda:SimpleNamespace(monitors=[]))
    monkeypatch.setattr(screen_grab,'_save_debug_frame',lambda *a:None)
    monkeypatch.setattr(screen_grab,'_grab_foreground_game',lambda:pytest.fail('access revoked before capture'))
    monkeypatch.setattr('time.sleep',lambda *a:None)
    assert screen_grab.capture_for_autofind(strict_game=True,capture_allowed=lambda:False)==(None,0,0)
