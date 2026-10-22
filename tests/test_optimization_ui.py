"""Actual app wiring, with the Windows collector and OS boundaries replaced."""
import sys
from types import SimpleNamespace
import pytest
from test_navigation import window
from mabinogi_addon.ui import optimization_controller as module
from mabinogi_addon.optimization.frames import FrameStream


def test_creator_entry_no_automatic_measurement_and_access_revocation(window,monkeypatch):
    w,app=window
    c=w.optimization_tools
    monkeypatch.setattr(module,'is_creator',lambda:False)
    c.refresh_access()
    assert w._tabs.indexOf(c.panel)==-1
    assert not c.frames and not c.collector.active and not c.engine.busy
    c.start_frames()
    assert not c.frames
    monkeypatch.setattr(module,'is_creator',lambda:True)
    c.refresh_access()
    assert w._tabs.tabText(w._tabs.indexOf(c.panel))=='최적화'
    assert [w._tabs.tabText(i) for i in range(w._tabs.count())]==['전투 보조','파티 모집','편의기능','최적화','설정']
    assert not hasattr(w.settings_tab,'optimization_button')
    c.open()
    assert c.panel is not None and not c.frames
    assert not hasattr(c.panel,'collector_path')
    monkeypatch.setattr(module.presentmon,'clock',lambda:(100,1000))
    monkeypatch.setattr(module.presentmon,'executable',lambda:object())
    monkeypatch.setattr(module.config,'load_game_exe',lambda:'Client.exe')
    monkeypatch.setattr(c.backend,'game',lambda:None)
    c.start_frames()
    assert c.frames and not c.collector.active
    monkeypatch.setattr(module,'is_creator',lambda:False)
    c.refresh_access()
    assert not c.frames and not c.overlay.isVisible()


def test_fps_pause_hides_only_and_focus_boundary_resets_frames(window,monkeypatch):
    w,app=window
    c=w.optimization_tools
    c.timer.stop()
    game={'pid':123,'birth':'999'}
    now=[100.0]
    active=[True]
    monkeypatch.setattr(module,'is_creator',lambda:True)
    monkeypatch.setattr(c.backend,'game',lambda:game)
    monkeypatch.setattr(module.presentmon,'clock',lambda:(now[0],1000))
    monkeypatch.setattr(module.presentmon,'game_context',lambda *a:(active[0],(11,123,0,0,1000,800)))
    c.frames=True;c.target=game;c.stream=FrameStream(123,1000)
    c.stream.feed('Application,ProcessID,SwapChainAddress,TimeInQPC,MsBetweenPresents',100)
    c._frame_tick(.25)
    def feed(start):
        for n in range(26):
            now[0]=start+n*.02
            c._line(f'game.exe,123,0xabc,{round(now[0]*1000)},20')
    feed(100.02)
    c._frame_tick(.25)
    assert c.overlay.isVisible()
    c.set_paused(True)
    assert c.frames and not c.overlay.isVisible()
    feed(100.54)
    c._frame_tick(.25)
    assert not c.overlay.isVisible() and c.stream.snapshot(now[0])['fps'] is not None
    c.set_paused(False);c._frame_tick(.25)
    assert c.overlay.isVisible()
    active[0]=False;c._frame_tick(.25)
    assert not c.overlay.isVisible() and not c.stream.sources
    active[0]=True;now[0]+=1;c._frame_tick(.25)
    assert not c.overlay.isVisible() and c.stream.snapshot(now[0])['fps'] is None
    c.stop_frames()
    assert not c.frames and c.stream is None


def test_common_pause_stops_combat_sound_and_unlocked_warnings(window,monkeypatch):
    w,app=window
    from mabinogi_addon.ui.pattern_overlay import PatternWarningOverlay
    calls=[]
    for tab,name in ((w.boss_tab,'boss'),(w.tuarim_tab,'tuarim')):
        tab._notifier=SimpleNamespace(stop=lambda name=name:calls.append(name))
    overlay=w.boss_tab._overlay
    overlay.set_locked(False)
    assert overlay.isVisible()
    w._set_paused(True)
    assert {'boss','tuarim'} <= set(calls)
    assert not overlay.isVisible()
    overlay.set_locked(True);overlay.set_locked(False)
    overlay.show_message('must not show')
    assert not overlay.isVisible()
    w._set_paused(False)
    assert overlay.isVisible() and overlay._text==overlay._sample
    overlay.set_locked(True)
    overlay.show_message('old warning')
    w._set_paused(True);w._set_paused(False)
    assert not overlay.isVisible() and not overlay._text  # Placement resumes; old alerts never replay.
    # Restore notifier shape before the normal window shutdown fixture.
    w.boss_tab._notifier=None;w.tuarim_tab._notifier=None


def test_owned_fps_marker_recovers_without_requiring_creator(window,monkeypatch):
    from mabinogi_addon.system.presentmon import Collector
    c=window[0].optimization_tools.collector
    name='MabinogiAddon-'+'a'*32
    c.marker.parent.mkdir(parents=True,exist_ok=True)
    c.marker.write_text(name,encoding='utf-8')
    previous=Collector()
    calls=[]
    monkeypatch.setattr(module.presentmon,'session_losses',lambda session,**kw:calls.append((session,kw)) or 0)
    monkeypatch.setattr(module,'is_creator',lambda:False)
    assert previous.pending
    assert previous.stop()
    assert calls==[(name,{'stop':True})]
    assert not previous.marker.exists()


def test_corrupt_fps_marker_never_stops_guessed_or_foreign_session(window,monkeypatch):
    from mabinogi_addon.system.presentmon import Collector
    c=window[0].optimization_tools.collector
    c.marker.parent.mkdir(parents=True,exist_ok=True)
    c.marker.write_text('OtherApplicationSession',encoding='utf-8')
    previous=Collector()
    monkeypatch.setattr(module.presentmon,'session_losses',lambda *a,**k:pytest.fail('must not query a guessed session'))
    assert previous.pending and not previous.stop()
    assert previous.marker.read_text(encoding='utf-8')=='OtherApplicationSession'
    c.marker.unlink()  # Fixture cleanup only; the product must preserve the corrupt record.


def test_fps_scale_and_lock_save_without_enabling_measurement(window,monkeypatch):
    w,app=window
    c=w.optimization_tools
    monkeypatch.setattr(module,'is_creator',lambda:True)
    c.open()
    c.panel.scale.setValue(200)
    assert c.overlay.width()==420 and not c.frames and not c.overlay.isVisible()
    c.panel.lock.setChecked(False)
    stored=module.config._read_local_config()['frameMeter']
    assert stored['scale']==200 and stored['overlay']['locked'] is False
    assert c.panel.scale.value()==200
    monkeypatch.setattr(module,'is_creator',lambda:False)
    c._set_scale(300)
    assert c._scale==200 and not c.frames


def test_config_restart_blocks_new_alpha_operations_and_stops_capture(window,monkeypatch):
    w,app=window
    c=w.optimization_tools
    monkeypatch.setattr(module,'is_creator',lambda:True)
    c.open()
    c.frames=True
    w._config_pending_restart=True
    monkeypatch.setattr(c.engine,'start',lambda *a:pytest.fail('no new optimization while restart pending'))
    c.refresh_access()
    assert not c.frames
    c._start_optimization();c.start_frames()
    assert not c.frames and not c.engine.busy
    w._config_pending_restart=False


def test_collector_csv_reaches_app_parser_in_fragmented_chunks(window,monkeypatch):
    from pathlib import Path
    from collections import deque
    c=window[0].optimization_tools
    data=(Path(__file__).parent/'data'/'presentmon-v2.3.1-v1-qpc.csv').read_bytes()
    chunks=deque((data[:17],data[17:213],data[213:]))
    monkeypatch.setattr(c.collector,'process',SimpleNamespace(readAllStandardOutput=lambda:chunks.popleft()))
    monkeypatch.setattr(module.presentmon,'clock',lambda:(100.52,1000))
    monkeypatch.setattr(module,'is_creator',lambda:True)
    c.frames=True;c.stream=FrameStream(123,1000);c.collector.active=True
    c._sync_summary_context(100.0)  # 실제 시작 tick처럼 수집 전에 관측 조건 확정
    for _ in range(3): c.collector._read()
    assert c.frames and c.stream.snapshot(100.52)['fps']==pytest.approx(50)
    c.stop_frames()


@pytest.mark.parametrize('recovery',['corrupt','pending','restart','none'])
def test_embedded_creator_and_recovery_tabs_preserve_single_lifetime(window,monkeypatch,recovery):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog
    w,app=window;c=w.optimization_tools
    panel,engine,collector,timer=c.panel,c.engine,c.collector,c.timer
    timers=set(w.findChildren(QTimer))
    calls=[]
    monkeypatch.setattr(c.engine,'inspect',lambda:calls.append('inspect'))
    monkeypatch.setattr(c.engine,'start',lambda *a:calls.append('start'))
    monkeypatch.setattr(c,'start_frames',lambda:calls.append('frames'))
    monkeypatch.setattr(module,'is_creator',lambda:True)
    for _ in range(5):
        c.refresh_access();w._tabs.setCurrentWidget(panel);panel.tabs.setCurrentIndex(1)
        w._tabs.setCurrentWidget(w._settings_scroll);panel.tabs.setCurrentIndex(0)
    assert not isinstance(panel,QDialog) and panel.window() is w
    assert not calls and (c.panel,c.engine,c.collector,c.timer)==(panel,engine,collector,timer)
    assert set(w.findChildren(QTimer))==timers
    if recovery=='corrupt': c.recovery.corrupt=True
    elif recovery=='pending': c.recovery.items=[dict(kind='ack',target='12345678-1234-1234-1234-123456789abc',old=None,applied=1,state='failed')]
    elif recovery=='restart': c.recovery.restart_targets={'12345678-1234-1234-1234-123456789abc'}
    monkeypatch.setattr(module,'is_creator',lambda:False)
    c.refresh_access();c._tick()
    assert w._tabs.indexOf(panel)==-1
    assert not panel.start.isEnabled() and not panel.frames_start.isEnabled()
    # 접근이 없으면 네트워크 원복을 묻거나 실행하지 않는다(CPU 원복 경로만 남음).
    monkeypatch.setattr(c,'_network_confirmation',lambda:pytest.fail('hidden alpha must not prompt'))
    restores=[]
    monkeypatch.setattr(c.engine,'stop_and_restore',lambda **k:restores.append(k))
    c._restore_all()
    assert restores==[dict(network=False,accept_normalized=False)]
    c.engine.recovery_requested=True;c._tick()
    monkeypatch.setattr(module,'is_creator',lambda:True)
    c.refresh_access()
    assert w._tabs.indexOf(panel)==3 and w._tabs.widget(4) is w._settings_scroll
    # Avoid an actual recovery prompt/OS action in window fixture cleanup.
    c.recovery.items=[];c.recovery.restart_targets.clear();c.recovery.corrupt=False


def test_creator_tour_settings_target_is_stable_when_optimization_is_inserted(window,monkeypatch):
    w,app=window;c=w.optimization_tools
    monkeypatch.setattr(module,'is_creator',lambda:True);c.refresh_access()
    assert w._tabs.indexOf(w._settings_scroll)==4
    w._run_tour();tour=w._tour;tour._i=5;tour._show_step();app.processEvents()
    assert w._tabs.currentWidget() is w._settings_scroll
    assert tour._steps[5].target is w.settings_tab.setup_btn
    tour.dismiss()


def test_summary_collection_shares_parser_preserves_pause_and_exports_without_raw_events(window,monkeypatch,tmp_path):
    import json,time
    from mabinogi_addon.optimization.frame_summary_store import SummaryStore
    c=window[0].optimization_tools;c.timer.stop()
    monkeypatch.setattr(module,'is_creator',lambda:True)
    now=[100.0]
    monkeypatch.setattr(module.presentmon,'clock',lambda:(now[0],1000000))
    c.summary_store=SummaryStore(tmp_path/'summaries')
    c.frames=True;c.target={'pid':123,'birth':'run-1'};c.context=(True,(1,123))
    c.stream=FrameStream(123,1000000,c.summary)
    c._sync_summary_context(now[0])
    c._line('Application,ProcessID,SwapChainAddress,QPCTime,msBetweenPresents')
    c._toggle_summary_collection(True)
    c.set_paused(True)  # 전투 보조 일시정지는 표시만 숨기고 집계는 계속
    for n in range(201):
        now[0]=100.02+n*.02
        c._line(f'game,123,0x1,{round(now[0]*1000000)},20')
    assert c.summary.current()['valid_intervals']==200
    assert c.summary.current()['max_1s_fps']==50
    c._toggle_summary_collection(False)
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        c._poll_summary_store()
        if c._summary_saved:break
        time.sleep(.005)
    assert c._summary_saved==1
    saved,=list((tmp_path/'summaries').glob('*.json'))
    report=json.loads(saved.read_text())
    assert report['raw_events_saved'] is False
    assert report['segments'][0]['context']['target']==c.target
    assert report['segments'][0]['context']['qpc_frequency']==1000000
    assert report['segments'][0]['low_1pct_fps']==pytest.approx(50)
    c.stop_frames();c._poll_summary_store()
    assert c.summary.records and c.summary_store.close_ready()


@pytest.mark.parametrize('header', [
    'Application,ProcessID,SwapChainAddress,TimeInQPC,MsBetweenPresents',
    '\ufeffApplication,ProcessID,SwapChainAddress,QPCTime,msBetweenPresents',
])
def test_start_from_app_preserves_collector_header_before_game_focus(window, monkeypatch, header):
    """App-focused start must keep the one-time CSV header for later game frames."""
    c = window[0].optimization_tools
    c.timer.stop()
    now = [100.0]
    game = {'pid': 123, 'birth': '999'}
    active = [False]
    monkeypatch.setattr(module, 'is_creator', lambda: True)
    monkeypatch.setattr(module.config, 'load_game_exe', lambda: 'game.exe')
    monkeypatch.setattr(module.presentmon, 'clock', lambda: (now[0], 1000))
    monkeypatch.setattr(module.presentmon, 'executable', lambda: object())
    monkeypatch.setattr(module.presentmon, 'game_context', lambda *a: (active[0], (11, 123)))
    monkeypatch.setattr(c.backend, 'game', lambda: game)
    monkeypatch.setattr(c.collector, 'start', lambda pid: None)
    c.start_frames()
    c._line(header)
    c._line('game.exe,123,0xabc,100010,10')
    assert not c.stream.sources and not c.summary.samples
    active[0] = True
    now[0] = 101.0
    c._frame_tick(.25)
    for n in range(1, 28):
        now[0] = 101 + n * .02
        c._line(f'game.exe,123,0xabc,{round(now[0]*1000)},20')
    c._tick()
    assert c.frames, c.frame_status
    assert c.overlay.isVisible()
    assert not c.panel.frames_start.isEnabled() and c.panel.frames_stop.isEnabled()
    assert c.stream.snapshot(now[0])['fps'] == pytest.approx(50)
    c.stop_frames()


def test_rss_normalized_restore_asks_specific_confirmation(window, monkeypatch):
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    calls = []
    c.recovery.restart_targets = {'12345678-1234-1234-1234-123456789abc'}  # 네트워크 원복 대상 있음
    monkeypatch.setattr(c.engine, 'stop_and_restore', lambda **k: calls.append(k))
    monkeypatch.setattr(c, '_network_confirmation', lambda: calls.append('generic') or True)
    c._restore_all()
    assert calls == ['generic', {'network': True, 'accept_normalized': False}]
    calls.clear()
    old = dict(MaxProcessorNumber=14, MaxProcessors=8); cur = dict(MaxProcessorNumber=14, MaxProcessors=1)
    c.recovery.normalized_review = [dict(target='g', current=cur, old=old)]
    asked = []
    def question(parent, title, text, *a):
        asked.append(text); return module.QMessageBox.StandardButton.No
    monkeypatch.setattr(module.QMessageBox, 'question', question)
    c._restore_all()
    assert not calls and '14 · 1개' in asked[0] and '14 · 8개' in asked[0]  # 거절 → 아무것도 안 함
    monkeypatch.setattr(module.QMessageBox, 'question', lambda *a: module.QMessageBox.StandardButton.Yes)
    c._restore_all()
    assert calls == [{'network': True, 'accept_normalized': True}]
    c.recovery.normalized_review = []
    c.recovery.restart_targets.clear()


def test_rss_normalization_detected_asks_once_without_second_click(window, monkeypatch):
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    calls, asked = [], []
    monkeypatch.setattr(c.engine, 'restore_network', lambda **k: calls.append(k))
    monkeypatch.setattr(c, '_normalized_confirmation', lambda: asked.append(1) or True)
    c._tick()
    assert not asked  # 감지 전에는 묻지 않음
    c.recovery.normalized_review = [dict(target='g', current={}, old={})]
    c._tick(); c._tick()
    assert asked == [1] and calls == [{'accept_normalized': True}]
    c.recovery.normalized_review = [dict(target='g', current={}, old={})]  # 새 감지
    monkeypatch.setattr(c, '_normalized_confirmation', lambda: asked.append(2) or False)
    c._tick(); c._tick()
    assert asked == [1, 2] and len(calls) == 1  # 거절하면 같은 감지로 다시 묻지 않음
    c.recovery.normalized_review = []



def test_single_restore_button_restores_cpu_only_without_network_prompt(window, monkeypatch):
    """원버튼: 네트워크 변경이 없으면 확인 없이 CPU만, 있으면 확인 1회 후 함께 원복. 별도 버튼 없음."""
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    assert c.panel.stop.text() == '중단 · 원복' and not hasattr(c.panel, 'restore')
    calls = []
    monkeypatch.setattr(c.engine, 'stop_and_restore', lambda **k: calls.append(k))
    monkeypatch.setattr(c, '_network_confirmation', lambda: pytest.fail('CPU만 되돌릴 땐 묻지 않음'))
    c.recovery.items = [dict(kind='cpu', target={'pid': 1, 'birth': '1'}, old=15, applied=3, state='applied')]
    c._tick()
    assert c.panel.stop.isEnabled()
    c._restore_all()
    assert calls == [dict(network=False, accept_normalized=False)]
    calls.clear()
    monkeypatch.setattr(c, '_network_confirmation', lambda: False)  # 네트워크 포함, 확인 거절
    c.recovery.items.append(dict(kind='ack', target='12345678-1234-1234-1234-123456789abc', old=None, applied=1, state='applied'))
    c._restore_all()
    assert not calls
    c.recovery.items = []
