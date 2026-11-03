"""Approved discovery/selection and C-policy boundaries, with deterministic clocks."""
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, autofind_state as state, setup_state, image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect.halo_timer import read_seconds

BOX=dict(x=100,y=200,w=300,h=400)


def test_discovery_does_not_activate_and_selection_restores_only_chosen():
    raw={'general':{'gameExe':'Client.exe'},'dorcha':{'box':BOX,'enabled':False,'scale':150}}
    config._write_local_config(raw)
    for key in ('buff','boss','halo_timer','debuff'): state.remember(key,BOX,(1,2,0,0,1920,1080))
    saved=config._read_local_config()
    assert saved['dorcha']==raw['dorcha']
    assert not any(state.active(k,saved) for k in ('buff','boss','halo_timer','debuff','dorcha'))
    state.select('buff',True)
    assert state.box_for('buff',config._read_local_config())==BOX
    assert not state.active('boss')
    state.select('buff',False)
    assert state.box_for('buff',config._read_local_config()) is None
    assert state.remembered('buff')['box']==BOX
    state.select('buff',True)
    assert state.active('buff')
    state.select('dorcha',True)
    state.select('dorcha',False)
    assert config._read_local_config()['dorcha']==raw['dorcha']


@pytest.mark.parametrize('consumer',['boss','halo_timer','debuff','stat','blackbox','none'])
def test_five_shared_consumers_and_no_consumer(consumer):
    raw={'bossPattern':{'box':BOX,'use':consumer=='boss'},
         'haloTimer':{'box':BOX,'use':consumer=='halo_timer'},
         'debuffTracker':{'captureRegion':BOX,'use':consumer=='debuff'},
         'statBars':{'box':BOX,'bars':{'hp':{'alert':{'on':consumer=='stat'}}}}}
    config._write_local_config(raw)
    external=consumer=='blackbox'
    assert state.shared_needed(external=external)==(consumer!='none')
    state.release_unused_boss(external=external)
    assert (config.load_boss_bar_region() is not None)==(consumer!='none')
    assert state.active('boss')==(consumer=='boss')
    if consumer=='none':
        assert state.remembered('boss')['box']==BOX
        state.release_unused_boss(external=True)
        assert config.load_boss_bar_region()==BOX and not state.active('boss')


def test_pattern_off_preserves_halo_and_migrates_once():
    config._write_local_config({'bossPattern':{'box':BOX},'haloTimer':{'box':BOX}})
    state.select('boss',False)
    state.release_unused_boss()
    assert not state.active('boss') and state.active('halo_timer')
    assert config.load_boss_bar_region()==BOX
    state.select('halo_timer',False)
    state.release_unused_boss()
    assert config.load_boss_bar_region() is None


def test_stat_display_off_and_custom_enabled_are_preserved():
    raw={'statBars':{'box':BOX,'enabled':True,'bars':{k:{'show':False} for k in ('hp','mp','sta')}},
         'customOverlay':{'enabled':False,'overlays':[BOX]}}
    config._write_local_config(raw)
    assert not state.active('stat_bars') and not state.active('custom')
    assert not setup_state.enabled('stat_bars')
    state.select('stat_bars',True)
    assert state.active('stat_bars')
    state.select('stat_bars',False)
    assert state.box_for('stat_bars',config._read_local_config())==BOX


def test_confirmation_fresh_frames_failures_pause_and_single_write(caplog,monkeypatch):
    config.save_capture_region(0,0,30,40)
    c=state.Confirmation(BOX,state.epoch('buff'),(1,2))
    def read(fid,t,ok=True,running=True):
        return c.observe(frame_id=fid,now=t,readable=ok,stamp=state.epoch('buff'),target=(1,2),running=running)
    assert not read(1,0)
    assert not read(1,10)  # duplicate frame does not count elapsed wall time
    assert not read(2,1)
    assert not read(3,2,False)
    assert not read(4,3)
    assert not read(5,4)
    assert not read(6,99,running=False)
    assert not read(7,100)
    assert not read(8,101)
    assert read(9,102)
    writes=[]
    original=config._write_local_config
    monkeypatch.setattr(config,'_write_local_config',lambda raw:(writes.append(deepcopy(raw)),original(raw))[1])
    with caplog.at_level('INFO'):
        assert c.commit('buff')
        assert not c.commit('buff')
    assert len(writes)==1
    assert '자동 찾기 위치 저장 buff:' in caplog.text
    assert config.load_capture_region()==BOX


@pytest.mark.parametrize('change',['manual','clear','off','target'])
def test_confirmation_invalidated_by_user_or_target(change):
    config.save_capture_region(0,0,30,40)
    c=state.Confirmation(BOX,state.epoch('buff'),(1,2))
    if change=='manual': config.save_capture_region(8,8,30,40)
    if change=='clear': state.select('buff',False)
    if change=='off': state.set_automatic(False)
    target=(2,3) if change=='target' else (1,2)
    assert not c.observe(frame_id=1,now=0,readable=True,stamp=state.epoch('buff'),target=target)
    assert not c.observe(frame_id=2,now=4,readable=True,stamp=state.epoch('buff'),target=target)
    assert config.load_capture_region()!=BOX


@pytest.mark.parametrize('index,expected',[ (1,1135),(2,1131),(3,966),(4,883)])
def test_1080_buff_and_long_halo_location(index,expected):
    frame=image_io.imread(Path(__file__).parent/'data'/f'image0{index}.png')
    trace={}
    box=run_detector('buff',frame,detector_assets('buff'),trace)
    assert box is not None and 100<=box[0]<=120 and box[2]==304
    assert trace['fallback']=='aligned_distinct_buff_icons'
    timer=run_detector('halo_timer',frame,detector_assets('halo_timer'),{})
    assert timer is not None
    x,y,w,h=timer
    value=read_seconds(frame[y:y+h,x:x+w],max_seconds=3600)
    assert value is not None  # exact values below are read from held-out original screenshots
    if index==1: assert value==1135 and read_seconds(frame[y:y+h,x:x+w]) is None
    if index==4: assert value==883


def test_blank_and_shortcut_only_never_establish_buff_column():
    from mabinogi_addon.detect.status_panel import locate_icon_column,fallback_assets
    frame=np.zeros((600,800,3),np.uint8)
    assert locate_icon_column(frame) is None
    for index,template in enumerate(fallback_assets().values()):
        frame[30:46,30+index*24:46+index*24]=template
    assert locate_icon_column(frame) is None


def test_guide_defer_persists_without_selection_or_restarting():
    from mabinogi_addon.ui.setup_guide import SetupGuide
    app=QApplication.instance() or QApplication([])
    config._write_local_config({'statBars':{'bars':{k:{'show':False} for k in ('hp','mp','sta')}}})
    guide=SetupGuide()
    guide.reset(first_run=True)
    guide.move(1)
    assert guide.stage==1
    guide.defer()
    assert not guide.active and not setup_state.needs_start_screen()
    assert not state.active('buff')
    guide.close()


def test_batch_remembers_without_registration_and_rejects_late_user_edit(monkeypatch):
    from mabinogi_addon.ui.setup_page import SetupPage
    from mabinogi_addon.ui.setup_guide import SetupGuide
    from mabinogi_addon.ui import setup_flow
    from mabinogi_addon.system import window_capture
    from mabinogi_addon.ui.setup_flow import SetupFlow
    app=QApplication.instance() or QApplication([])
    config._write_local_config({'general':{'gameExe':'Client.exe'}})
    target=(11,22,0,0,1920,1080)
    monkeypatch.setattr(window_capture,'registered_game_target',lambda *a:target)
    monkeypatch.setattr(setup_flow,'capture_for_autofind',lambda **kw:(np.zeros((1080,1920,3),np.uint8),0,0))
    page,guide=SetupPage(),SetupGuide()
    applied=[]
    flow=SetupFlow(page,lambda *args:applied.append(args))
    monkeypatch.setattr(flow,'_detect',lambda *args:(100,200,300,400))
    flow.find_all(guide,('buff',))
    assert state.remembered('buff') and not config.load_capture_region()
    assert guide.outcomes['buff']=='찾음' and not applied
    def edit(*args):
        config.save_capture_region(20,30,40,50)
        return 100,200,300,400
    monkeypatch.setattr(flow,'_detect',edit)
    flow.find_all(guide,('buff',))
    assert config.load_capture_region()==dict(x=20,y=30,w=40,h=50)
    assert guide.outcomes['buff']=='설정이 변경되어 결과를 버렸어요'
    guide.close();page.close();flow.shutdown()


def test_readable_registered_buffs_and_cropped_waiting_timer():
    from mabinogi_addon.ui.autofind_runtime import readable,find_expected
    f=image_io.imread(Path(__file__).parent/'data/image01.png')
    assert readable('buff',f[420:910,112:416])
    assert not readable('buff',np.zeros((400,300,3),np.uint8))
    boss=find_expected('boss',f[770:920,620:1300])
    assert boss is not None and boss[:2]==(78,47)
    crop=f[110:220,820:1100]
    box=find_expected('halo_timer',crop)
    assert box is not None
    x,y,w,h=box
    assert read_seconds(crop[y:y+h,x:x+w],max_seconds=3600)==1135


def test_runtime_late_search_and_off_result_do_not_commit(monkeypatch):
    from types import SimpleNamespace
    from mabinogi_addon.ui.autofind_runtime import AutofindRuntime
    app=QApplication.instance() or QApplication([])
    from PySide6.QtWidgets import QWidget
    window=QWidget()
    changes=[]
    window._reload_autofind_feature=changes.append
    window.setup_guide=SimpleNamespace(record_result=lambda *a:None)
    runtime=AutofindRuntime(window)
    runtime.timer.stop()
    runtime.target=(1,2,0,0,1920,1080)
    job=dict(kind='search',keys=('buff',),detector='buff',physical=(0,0,1920,1080),waiting=False)
    runtime._accept(job,((100,200,300,400),{}),10,False,0)
    assert not runtime.candidates and not changes
    runtime._accept(job,((100,200,300,400),{}),10,True,0)
    assert runtime.candidates['buff'].elapsed==0
    config.save_capture_region(1,2,3,4)
    c=runtime.candidates['buff']
    assert not c.observe(frame_id=1,now=20,readable=True,stamp=state.epoch('buff'),target=runtime.target)
    assert config.load_capture_region()==dict(x=1,y=2,w=3,h=4)
    runtime.shutdown();window.close()


def test_shared_frame_subscriptions_do_not_own_capture_or_each_other(monkeypatch):
    from mabinogi_addon.capture import shared
    clock=[10.0]
    monkeypatch.setattr(shared,'monotonic',lambda:clock[0])
    producer=shared.SharedFrame()
    a,b=producer.source(),producer.source()
    frame=np.full((37,521,3),42,np.uint8)
    producer.publish(frame)
    frame[:]=0
    assert a.grab()[0,0,0]==42 and b.grab()[0,0,0]==42
    a.close()
    assert a.grab() is None and b.grab() is not None
    clock[0]=11.1
    assert b.grab() is None


@pytest.mark.parametrize('consumer',['halo_timer','debuff','stat','blackbox','none'])
def test_actual_shared_capture_has_independent_pattern_output(monkeypatch,consumer):
    from types import SimpleNamespace
    from mabinogi_addon.ui import boss_tab
    app=QApplication.instance() or QApplication([])
    config._write_local_config({'bossPattern':{'box':BOX,'use':False},
        'haloTimer':{'box':BOX,'use':consumer=='halo_timer'},
        'debuffTracker':{'captureRegion':BOX,'use':consumer=='debuff'},
        'statBars':{'box':BOX,'bars':{'hp':{'alert':{'on':consumer=='stat'}}}}})
    tab=boss_tab.BossTab(SimpleNamespace(is_game_active=lambda:True,is_self_active=lambda:False))
    tab._timer.stop();tab.halo_capture._timer.stop()
    tab.set_presence_consumer(lambda:consumer in ('stat','blackbox'))
    captures=[];warnings=[];sounds=[];contexts=[]
    monkeypatch.setattr(tab,'_grab_rect',lambda *a:(captures.append(a),np.zeros((37,521,3),np.uint8))[1])
    monkeypatch.setattr(tab,'_show_preview',lambda *a:None)
    monkeypatch.setattr(tab,'_play',sounds.append)
    monkeypatch.setattr(tab._overlay,'show_message',lambda *a:warnings.append(a))
    monkeypatch.setattr(tab.halo_capture,'set_boss_context',contexts.append)
    monkeypatch.setattr(boss_tab,'identify',lambda *a,**k:'lenen_miir_hoehan')
    hp=[90]
    monkeypatch.setattr(boss_tab,'read_percent',lambda *a:hp[0])
    for value in (90,90,90,65,65,65,60,60,60):
        hp[0]=value;tab._tick()
    assert bool(captures)==(consumer!='none')
    assert not warnings and not sounds and not tab._upcoming.isVisible()
    assert ('lenen_miir_hoehan' in contexts)==(consumer=='halo_timer')
    if consumer in ('stat','blackbox'): assert tab.is_boss_present()
    tab.shutdown()


def test_confirmation_runtime_restarts_three_seconds_after_one_failed_frame():
    from types import SimpleNamespace
    from PySide6.QtWidgets import QWidget
    from mabinogi_addon.ui.autofind_runtime import AutofindRuntime
    app=QApplication.instance() or QApplication([])
    window=QWidget();changes=[]
    window._reload_autofind_feature=changes.append
    runtime=AutofindRuntime(window);runtime.timer.stop()
    runtime.target=(1,2,0,0,1920,1080)
    config.save_capture_region(1,2,30,40)
    c=state.Confirmation(BOX,state.epoch('buff'),runtime.target);c.created=0
    runtime.candidates['buff']=c
    for i,ok in enumerate((True,True,False,True,True,True,True)):
        runtime._accept(dict(kind='read',frame_id=i,delta=.5),{'buff':ok},float(i),True,.5)
        if i<6: assert config.load_capture_region()!=BOX
    assert config.load_capture_region()==BOX and changes==['buff']
    runtime.shutdown();window.close()


def test_explicit_selection_survives_missing_discovery_and_later_only_registers_it():
    state.select('buff',True)
    state.remember('buff',BOX)
    state.remember('skillbar',BOX)
    assert state.apply_discovered('buff')
    assert not state.apply_discovered('skillbar')
    assert config.load_capture_region()==BOX
    assert config.load_skillbar()['anchor'] is None


def test_migration_is_idempotent_and_preserves_legacy_off_values(monkeypatch):
    config._write_local_config({'bossPattern':{'box':BOX},'haloTimer':{'box':BOX},
        'debuffTracker':{'captureRegion':BOX},'dorcha':{'box':BOX,'enabled':False}})
    state.initialize_consumers()
    assert all(state.active(k) for k in state.SHARED)
    assert not state.active('dorcha')
    monkeypatch.setattr(config,'_write_local_config',lambda *a:pytest.fail('second migration must not write'))
    state.initialize_consumers()


def test_safe_tick_restarts_remembered_shared_bar_for_external_consumer(monkeypatch):
    from types import SimpleNamespace
    from mabinogi_addon.ui.boss_tab import BossTab
    app=QApplication.instance() or QApplication([])
    config._write_local_config({'bossPattern':{'use':False}})
    state.remember('boss',BOX)
    tab=BossTab(SimpleNamespace(is_game_active=lambda:True,is_self_active=lambda:False))
    tab._timer.stop();tab.halo_capture._timer.stop()
    tab.set_presence_consumer(lambda:True)
    captured=[]
    monkeypatch.setattr(tab,'_grab_rect',lambda *a:captured.append(a))
    tab._safe_tick()
    assert tab._region==BOX and len(captured)==1 and not state.active('boss')
    tab.shutdown()


def test_absent_boss_does_not_starve_waiting_halo(monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QWidget
    from mabinogi_addon.ui import autofind_runtime as runtime_module
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window._setup_busy = lambda: False
    window._watcher = SimpleNamespace(is_game_active=lambda: True)
    runtime = runtime_module.AutofindRuntime(window)
    runtime.timer.stop()
    target = (1, 2, 0, 0, 1920, 1080)
    monkeypatch.setattr(runtime_module, 'registered_game_target', lambda previous=None: target)
    clock = [100.0]
    monkeypatch.setattr(runtime_module, 'monotonic', lambda: clock[0])
    config._write_local_config({'autofind': {'armed': True}, 'dorcha': {'enabled': False},
                                'tuarim': {'enabled': False}})
    searches = []
    def search(detector, keys, now, **kwargs):
        searches.append(detector)
        runtime.next_search[detector] = now + 10
    monkeypatch.setattr(runtime, '_search', search)
    runtime.tick()
    clock[0] += 10
    runtime.tick()
    assert searches == ['boss', 'halo_timer']
    runtime.shutdown()
    window.close()


@pytest.mark.parametrize('interrupt', ['cancel', 'target', 'shutdown'])
def test_batch_drops_result_after_interruption(monkeypatch, interrupt):
    from mabinogi_addon.ui import setup_flow
    from mabinogi_addon.ui.setup_page import SetupPage
    from mabinogi_addon.ui.setup_guide import SetupGuide
    from mabinogi_addon.system import window_capture
    app = QApplication.instance() or QApplication([])
    config._write_local_config({'general': {'gameExe': 'Client.exe'}})
    target = [(11, 22, 0, 0, 1920, 1080)]
    monkeypatch.setattr(window_capture, 'registered_game_target', lambda *a: target[0])
    monkeypatch.setattr(setup_flow, 'capture_for_autofind',
                        lambda **kw: (np.zeros((1080, 1920, 3), np.uint8), 0, 0))
    page, guide = SetupPage(), SetupGuide()
    flow = setup_flow.SetupFlow(page, lambda *args: pytest.fail('unexpected registration'))
    def detect(*args):
        if interrupt == 'cancel': flow.cancel()
        elif interrupt == 'shutdown': flow.shutdown()
        else: target[0] = (33, 44, 0, 0, 1920, 1080)
        return 100, 200, 300, 400
    monkeypatch.setattr(flow, '_detect', detect)
    flow.find_all(guide, ('buff',))
    assert state.remembered('buff') is None
    assert config.load_capture_region() is None
    assert not flow.running
    if interrupt == 'shutdown':
        assert flow.closed  # Closing UI is not refreshed or re-enabled.
    else:
        assert not guide.busy
    guide.close()
    page.close()
    flow.shutdown()
