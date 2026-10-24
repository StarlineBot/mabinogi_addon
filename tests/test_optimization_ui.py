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
    base=c.overlay.width()
    c.panel.scale.setValue(200)
    # 전용 그리기 오버레이(FPS 8.1): 크기는 내용에 맞춰지고 배율에 비례한다.
    assert abs(c.overlay.width()-2*base)<=4 and not c.frames and not c.overlay.isVisible()
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
    # 명세 13.1: 처음 열 때 읽기 전용 환경 확인만 1회 자동 실행. 적용·측정은 자동으로 시작하지 않는다.
    assert calls in ([], ['inspect']) and 'start' not in calls and 'frames' not in calls
    assert (c.panel,c.engine,c.collector,c.timer)==(panel,engine,collector,timer)
    assert set(w.findChildren(QTimer))==timers
    if recovery=='corrupt': c.recovery.corrupt=True
    elif recovery=='pending': c.recovery.items=[dict(kind='ack',target='12345678-1234-1234-1234-123456789abc',old=None,applied=1,state='failed')]
    elif recovery=='restart': c.recovery.restart_targets={'12345678-1234-1234-1234-123456789abc'}
    monkeypatch.setattr(module,'is_creator',lambda:False)
    c.refresh_access();c._tick()
    assert w._tabs.indexOf(panel)==-1
    # 새 시작은 막는다. 되돌릴 기록이 남아 있으면 토글은 켜짐(원복 경로)으로 남는다(13.5, 이전 '중단 · 원복'과 같음).
    assert not panel.frames_toggle.isEnabled()
    assert panel.toggle.isEnabled() == (recovery in ('pending','restart')) and panel.toggle.isChecked() == (recovery in ('pending','restart'))
    # 접근이 없으면 네트워크 원복을 묻거나 실행하지 않는다(CPU 원복 경로만 남음).
    monkeypatch.setattr(c,'_network_confirmation',lambda:pytest.fail('hidden alpha must not prompt'))
    restores=[]
    monkeypatch.setattr(c.engine,'stop_and_restore',lambda **k:restores.append(k))
    c._restore_all()
    assert restores==[dict(network=False,accept_normalized=False,network_deferred=False)]
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
    report=json.loads(saved.read_text(encoding="utf-8"))
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
    assert c.panel.frames_toggle.isEnabled() and c.panel.frames_toggle.isChecked()
    assert c.panel.frames_toggle.text() == 'FPS 표시 중' and c.frame_status.startswith('표시 중 · ')
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
    assert calls == ['generic', {'network': True, 'accept_normalized': False, 'network_deferred': False}]
    calls.clear()
    old = dict(MaxProcessorNumber=14, MaxProcessors=8); cur = dict(MaxProcessorNumber=14, MaxProcessors=1)
    c.recovery.normalized_review = [dict(target='g', current=cur, old=old)]
    asked = []
    def question(parent, title, text, *a):
        asked.append(text); return module.QMessageBox.StandardButton.No
    monkeypatch.setattr(module.QMessageBox, 'question', question)
    c._restore_all()
    assert '14 · 1개' in asked[0] and '14 · 8개' in asked[0]
    assert calls == [{'network': False, 'accept_normalized': False, 'network_deferred': True}]  # 거절 → CPU만
    calls.clear()
    monkeypatch.setattr(module.QMessageBox, 'question', lambda *a: module.QMessageBox.StandardButton.Yes)
    c._restore_all()
    assert calls == [{'network': True, 'accept_normalized': True, 'network_deferred': False}]
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
    assert not hasattr(c.panel, 'stop') and not hasattr(c.panel, 'restore')  # 13.5: 토글 하나
    calls = []
    monkeypatch.setattr(c.engine, 'stop_and_restore', lambda **k: calls.append(k))
    monkeypatch.setattr(c, '_network_confirmation', lambda: pytest.fail('CPU만 되돌릴 땐 묻지 않음'))
    c.recovery.items = [dict(kind='cpu', target={'pid': 1, 'birth': '1'}, old=15, applied=3, state='applied')]
    c._tick()
    assert c.panel.toggle.isEnabled() and c.panel.toggle.isChecked() and c.panel.toggle.text() == '최적화 적용 중'
    c.panel.toggle.click()  # 켜진 상태에서 누르면 중단·원복
    assert calls == [dict(network=False, accept_normalized=False, network_deferred=False)]
    c.recovery.items = []


def test_declining_network_prompt_restores_cpu_only(window, monkeypatch):
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    calls = []
    monkeypatch.setattr(c.engine, 'stop_and_restore', lambda **k: calls.append(k))
    monkeypatch.setattr(c, '_network_confirmation', lambda: False)
    c.recovery.items = [dict(kind='ack', target='12345678-1234-1234-1234-123456789abc', old=None, applied=1, state='applied')]
    c._restore_all()
    assert calls == [dict(network=False, accept_normalized=False, network_deferred=True)]
    c.recovery.items = []


# --- 명세 13.1: 선택값 저장·환경 확인 자동 실행 ----------------------------------------------------
def test_selection_is_machine_local_and_not_exported(tmp_path):
    import json as _json
    from mabinogi_addon import config
    path = tmp_path / 'c.json'
    config.save_optimization_selection(dict(cpu=True, count=6, adapter='ABC-1', tcp=True, rss=False), path)
    assert config.load_optimization_selection(path) == dict(cpu=True, tcp=True, rss=False, count=6, adapter='ABC-1')
    assert 'optimizationSelection' not in _json.loads(config.config_json_for_export(path))
    incoming = tmp_path / 'other.json'
    incoming.write_text(_json.dumps({'optimizationSelection': {'count': 1, 'adapter': 'OTHER-PC'}}), encoding='utf-8')
    config.import_config(incoming, path)  # 다른 PC 설정을 가져와도 이 PC 장치 값은 유지
    assert config.load_optimization_selection(path)['adapter'] == 'ABC-1'


def test_first_open_runs_inspection_once_in_background(window, monkeypatch):
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    calls = []
    monkeypatch.setattr(c.engine, 'inspect', lambda: calls.append(1) or True)
    c._auto_inspected = False
    w._tabs.setCurrentWidget(w._settings_scroll); w._tabs.setCurrentWidget(c.panel)
    w._tabs.setCurrentWidget(w._settings_scroll); w._tabs.setCurrentWidget(c.panel)
    assert calls == [1] and c.panel.inspect.text() == '다시 확인'


def test_saved_selection_is_restored_and_unusable_values_are_explained(window, monkeypatch):
    from mabinogi_addon import config
    from mabinogi_addon.optimization.session import Core, Topology
    w, app = window; c = w.optimization_tools
    topology = Topology('AMD Ryzen 7 9800X3D', tuple(Core(i, (i * 2, i * 2 + 1)) for i in range(8)))
    adapters = [dict(Name='Realtek 2.5GbE', InterfaceGuid='{AAAA-1}'), dict(Name='Wi-Fi', InterfaceGuid='{BBBB-2}')]
    config.save_optimization_selection(dict(cpu=False, count=6, adapter='bbbb-2', tcp=True, rss=False))
    c._restore_selection()
    assert not c.panel.cpu.isChecked() and c.panel.tcp.isChecked()
    c._apply_inspection(topology, adapters)
    assert c.panel.split.currentData() == 6 and c.panel.adapter.currentText() == 'Wi-Fi'
    config.save_optimization_selection(dict(cpu=True, count=20, adapter='GONE', tcp=False, rss=False))
    c._apply_inspection(topology, adapters)
    assert c.panel.split.currentData() == 7  # 9800X3D 구조별 기본 7+1
    assert c.panel.adapter.currentData() is None
    assert '저장한 배분(게임 20개)' in c.panel.cpu_info.text() and '저장한 네트워크 어댑터를 찾지 못해' in c.panel.cpu_info.text()
    # 사용자가 다시 고르면 저장된다(자동 적용은 하지 않음).
    c.panel.adapter.setCurrentIndex(1)
    assert config.load_optimization_selection()['adapter'] == 'AAAA-1'


def test_top_badge_is_creator_only_hidden_when_idle_and_opens_tab(window, monkeypatch):
    # 최적화 명세 13.2: 상단 상태는 제작자 전용, 작업이 없으면 숨김, 누르면 최적화 탭.
    from types import SimpleNamespace as NS
    w, app = window; c = w.optimization_tools
    badge = w._optimization_badge
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    c._update_badge()
    assert badge.isHidden()  # 작업 없음
    c.recovery.items.append(dict(kind='ack', state='applied', target='x', old=1, applied=0))
    try:
        c._update_badge()
        assert not badge.isHidden() and badge.text() == '최적화: 적용 중'  # 13.5 보정: 원복 요청 전은 정상 적용
        w._tabs.setCurrentWidget(w._settings_scroll)
        badge.click()
        assert w._tabs.currentWidget() is c.panel
        monkeypatch.setattr(module, 'is_creator', lambda: False)
        c._update_badge()
        assert badge.isHidden()
    finally:
        c.recovery.items.clear()
    # 상태 문구: 세션 중 CPU 적용 / 게임 대기 / 환경 확인은 표시 안 함 / 손상은 오류
    def engine(task, busy=True, cancel=False):
        return NS(busy=busy, task=task, cancel=NS(is_set=lambda: cancel))
    cpu = [dict(kind='cpu', state='applied')]
    rec = lambda pending, corrupt=False: NS(pending=pending, restart_targets=set(), corrupt=corrupt)
    assert module.optimization_badge(rec(cpu), engine('session'), '7+1') == ('최적화: 적용 중 7+1', 'neutral')
    assert module.optimization_badge(rec([]), engine('session'))[0] == '최적화: 게임 대기'
    assert module.optimization_badge(rec(cpu), engine('session', cancel=True))[0] == '최적화: 원복 중'
    assert module.optimization_badge(rec([]), engine('inspect')) is None
    assert module.optimization_badge(rec([], corrupt=True), engine(None, busy=False))[0] == '최적화: 오류'
    assert module.optimization_badge(rec([dict(kind='rss', state='failed')]), engine(None, busy=False))[0] == '최적화: 오류'


def test_condition_name_measurement_view_and_condition_summary(window, monkeypatch, tmp_path):
    # FPS 명세 7절: 측정 조건 이름, 측정 단위 비교, 조건별 정리(구간 중앙값·범위).
    import json
    from mabinogi_addon.optimization.frame_summary import FrameSummary
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()

    def measure(gap_every, condition):
        book = FrameSummary(); book.set_condition(condition); book.activate('a', 0); t = 0
        for n in range(3000):
            value = .04 if n % gap_every == 0 else .01
            t += value; book.interval('a', t, value)
        book.boundary(t + .001, 'measurement_stop')
        return book

    c.panel.condition.setText('7+1 SMT끔')
    assert c.summary.condition == '7+1 SMT끔'
    before, after = measure(50, '기본'), measure(500, '7+1 SMT끔')
    c.summary, c._previous_measurement = after, before.measurement()
    c.panel._summary_signature = None
    c._render_summary(force=True)
    index = c.panel.summary_select.findData('measurement')
    assert index >= 0
    c.panel.summary_select.setCurrentIndex(index)
    text = c.panel.summary_result.text()
    assert '측정 전체 · 7+1 SMT끔' in text and '직전 측정(기본) 대비' in text and '긴 간격 분당' in text
    monkeypatch.setattr(c.summary_store, 'folder', tmp_path)
    for n, book in enumerate((before, after)):
        (tmp_path / f'frames-{n}.json').write_text(json.dumps(book.report()), encoding='utf-8')
    c.panel.summary_conditions.click()
    shown = c.panel.condition_result.text()
    assert not c.panel.condition_result.isHidden()
    assert '■ 기본' in shown and '■ 7+1 SMT끔' in shown and '평균해 조건 전체 1% low로 쓰지 않아요' in shown


def test_condition_change_during_measurement_applies_to_next_measurement(window, monkeypatch):
    # 0.12.0 QA 선택 2: 측정 중 조건 이름을 바꿔도 한 측정에 이름이 섞이지 않는다.
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    c.panel.condition.setText('기본')
    assert c.summary.condition == '기본'
    c.frames = True
    try:
        c.panel.condition.setText('7+1')
        assert c.summary.condition == '기본' and '다음 측정부터' in c._summary_message
    finally:
        c.frames = False


def test_fps_display_toggle_starts_and_stops_measurement(window, monkeypatch):
    # FPS 탭 표시/수집 분리: 'FPS 표시' 토글 하나가 기존 측정 시작·중단과 같은 동작.
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    calls = []
    monkeypatch.setattr(c, 'start_frames', lambda: calls.append('start') or setattr(c, 'frames', True))
    monkeypatch.setattr(c, 'stop_frames', lambda message=None: calls.append('stop') or setattr(c, 'frames', False))
    toggle = c.panel.frames_toggle
    assert toggle.text() == 'FPS 표시' and not toggle.isChecked()
    toggle.click()
    assert calls == ['start'] and toggle.isChecked() and toggle.text() == 'FPS 표시 중'
    toggle.click()
    assert calls == ['start', 'stop'] and not toggle.isChecked() and toggle.text() == 'FPS 표시'
    # 시작이 실패하면(게임 미등록 등) 토글은 다시 꺼짐으로 돌아간다.
    monkeypatch.setattr(c, 'start_frames', lambda: calls.append('start-failed'))
    toggle.click()
    assert not toggle.isChecked() and toggle.text() == 'FPS 표시'


def test_collection_mode_does_not_start_display_or_write_files_when_display_is_off(window, monkeypatch, tmp_path):
    from mabinogi_addon.optimization.frame_summary_store import SummaryStore
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    monkeypatch.setattr(c, 'start_frames', lambda: pytest.fail('collection must not start the display'))
    c.summary_store = SummaryStore(tmp_path / 'summaries')
    c.panel.summary_collect.setChecked(True)
    assert c._summary_collecting and not c.frames
    assert 'FPS 표시가 꺼져 있어 수집하지 않아요' in c.panel.summary_path.text()
    c._tick()
    assert not (tmp_path / 'summaries').exists() or not any((tmp_path / 'summaries').iterdir())
    c.panel.summary_collect.setChecked(False)


def test_fps_display_setting_is_restored_after_restart_but_collection_is_not(window, monkeypatch):
    # 0.13.3: 'FPS 표시' 켜짐은 재실행 후 유지, 수집 모드는 매번 꺼짐. 이전 세션 정리가 남으면 켜지 않음.
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    calls = []
    monkeypatch.setattr(c, 'start_frames', lambda: calls.append('start') or setattr(c, 'frames', True))
    monkeypatch.setattr(c, 'stop_frames', lambda message=None: calls.append('stop') or setattr(c, 'frames', False))
    c.panel.frames_toggle.click()
    assert module.config._read_local_config()['frameMeter']['display'] is True
    c.panel.frames_toggle.click()
    assert module.config._read_local_config()['frameMeter']['display'] is False
    # 재실행: 저장값이 켜짐이면 접근이 확인된 첫 틱에 한 번 켠다.
    calls.clear(); c._restore_display = True
    c._tick(); c._tick()
    assert calls == ['start'] and not c.panel.summary_collect.isChecked()
    # 끔 저장 → 켜지 않음
    calls.clear(); c.frames = False; c._restore_display = False
    c._tick()
    assert calls == []
    # 0.14.1: 이전 FPS 세션 정리(pending)가 남으면 정리 → 성공 시 바로 켜고, 실패하면 5초 간격 3회 시도 뒤 포기.
    state = {'pending': True}
    monkeypatch.setattr(type(c.collector), 'pending', property(lambda self: state['pending']), raising=False)
    clock = [5000.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    c._restore_display, c._restore_retry_at, c._restore_tries = True, 0.0, 0
    for n in range(4):
        clock[0] += 6; c._tick()
    assert calls.count('start') == 0 and calls.count('stop') == 3 and not c._restore_display
    calls.clear(); c._restore_display, c._restore_retry_at, c._restore_tries = True, 0.0, 0
    monkeypatch.setattr(c, 'stop_frames', lambda message=None: calls.append('stop') or state.update(pending=False))
    clock[0] += 6; c._tick()
    assert calls == ['stop', 'start'] and not c._restore_display  # 업데이트 뒤: 한 번에 정리하고 켜짐



def test_single_optimization_toggle_follows_spec_13_5(window, monkeypatch):
    # 13.5: 꺼짐 '최적화 시작' → 켜짐 '최적화 적용 중'. 바꾼 것이 없어도 켜짐, 되돌릴 게 없으면 바로 꺼짐+안내.
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    toggle = c.panel.toggle
    started, restored = [], []
    def start():
        started.append(1); c._kept_on = True; c.engine.session_end = 'network_only'
    monkeypatch.setattr(c, '_start_optimization', start)
    monkeypatch.setattr(c, '_restore_all', lambda: restored.append(1))
    c._tick()
    assert toggle.text() == '최적화 시작' and not toggle.isChecked()
    toggle.click()  # 네트워크만, 모든 항목이 이미 목표값 → 바꾼 기록 없음
    c._tick()
    assert started == [1] and toggle.isChecked() and toggle.text() == '최적화 적용 중'
    toggle.click()  # 되돌릴 변경 없음 → 원복 호출 없이 바로 꺼짐
    assert restored == [] and not toggle.isChecked() and '되돌릴 것이 없어요' in c.engine.status
    # 게임 종료로 끝난 세션은 남은 변경이 없으면 꺼지고, 네트워크 변경이 남으면 원복 대기로 켜짐 유지.
    c._kept_on, c.engine.session_end = True, 'game_exit'
    c._tick()
    assert not toggle.isChecked()
    c.recovery.items = [dict(kind='ack', target='12345678-1234-1234-1234-123456789abc', old=0, applied=1, state='applied')]
    try:
        c._tick()
        # 13.5 보정: 원복을 요청하지 않은 네트워크 변경은 정상 '적용 중'(경고 아님)
        assert toggle.isChecked() and toggle.text() == '최적화 적용 중'
        assert w._optimization_badge.text() == '최적화: 적용 중'
        toggle.click()  # 원복 요청(가짜 _restore_all) → 끝났는데 남음 = 거절·실패 → 원복 대기
        c._restore_requested = True
        c._tick()
        assert restored == [1] and toggle.text() == '최적화 적용 중 · 네트워크 원복 대기'
        assert w._optimization_badge.text() == '최적화: 원복 대기'
    finally:
        c.recovery.items = []
    c._tick()
    assert not toggle.isChecked()  # 재실행 시와 같이 기록이 없으면 꺼짐


def test_result_wording_states_facts_not_performance():
    from mabinogi_addon.optimization.engine import result_headline
    assert result_headline([], set()) == '최적화 적용 완료 · 설정이 목표 상태로 맞춰졌어요'
    assert '일부 미적용' in result_headline(['x'], {'x'})
    assert '좋아' not in result_headline([], set()) and '줄었' not in result_headline([], set())



def test_badge_separates_applied_from_restore_wait():
    from types import SimpleNamespace as NS
    idle = NS(busy=False, task=None, cancel=NS(is_set=lambda: False))
    net = NS(pending=[dict(kind='ack', state='applied')], restart_targets=set(), corrupt=False)
    none = NS(pending=[], restart_targets=set(), corrupt=False)
    assert module.optimization_badge(net, idle) == ('최적화: 적용 중', 'neutral')
    assert module.optimization_badge(net, idle, restore_wait=True) == ('최적화: 원복 대기', 'warn')
    assert module.optimization_badge(none, idle, kept_on=True) == ('최적화: 적용 중', 'neutral')  # 바꾼 것 없이 켜짐
    assert module.optimization_badge(none, idle) is None


def test_previous_run_records_start_as_restore_wait_and_session_end_is_not_alarming():
    from mabinogi_addon.optimization.engine import Engine, NETWORK_APPLIED
    from types import SimpleNamespace as NS
    import threading
    recovery = NS(pending=[dict(kind='ack', state='applied')], restart_targets=set(), corrupt=False,
                  restore=lambda *a, **k: [])
    engine = Engine(NS(), recovery, lambda: True)
    engine._launch(lambda: setattr(engine, 'status', '최적화 적용 완료'), restore_cpu=True, task='session')
    engine.thread.join(2)
    assert engine.status.endswith(NETWORK_APPLIED) and '복구 기록이 남아' not in engine.status


def test_pending_cleanup_and_start_in_one_click(window, monkeypatch):
    # 0.13.5: 이전 세션 정리가 남아 있으면 첫 클릭은 정리만 하고 두 번째에 켜지던 문제.
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    state = {'pending': True}
    monkeypatch.setattr(type(c.collector), 'pending', property(lambda self: state['pending']), raising=False)
    monkeypatch.setattr(c.collector, 'stop', lambda: state.update(pending=False) or True)
    started = []
    monkeypatch.setattr(c, 'start_frames', lambda: started.append(1) or setattr(c, 'frames', True))
    c.panel.frames_toggle.click()
    assert started == [1] and c.panel.frames_toggle.isChecked()
    # 정리에 실패하면 꺼진 채 안내만
    c.frames = False; state['pending'] = True; started.clear()
    monkeypatch.setattr(c.collector, 'stop', lambda: False)
    c._toggle_frames(True)
    assert started == [] and not c.panel.frames_toggle.isChecked()


def test_collector_error_is_logged_and_restarted_at_most_three_times(window, monkeypatch, caplog):
    import logging
    caplog.set_level(logging.INFO)
    w, app = window; c = w.optimization_tools
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    clock = [1000.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(c.collector, 'stop', lambda: True)
    started = []
    monkeypatch.setattr(c, 'start_frames', lambda: started.append(clock[0]) or setattr(c, 'frames', True))
    for n in range(4):
        c.frames = True
        c._failed('FPS 수집기가 종료됐어요.')
        assert not c.frames
        clock[0] += c.RESTART_DELAY + .1
        c._tick()
    assert len(started) == 3  # 10분에 3회까지
    assert '자동 재시작 한도' in c.frame_status and c._restart_at is None
    assert sum('FPS 표시 중단' in r.getMessage() for r in caplog.records) == 4
    assert sum('자동 재시작' in r.getMessage() for r in caplog.records if r.levelno == logging.INFO) == 3
    # 사용자가 끄면 재시작하지 않는다. 저장된 표시 설정도 바꾸지 않는다(오류 경로는 저장하지 않음).
    c._restarts = []; c.frames = True
    c._failed('수집 오류')
    c._toggle_frames(False)
    clock[0] += 10; started.clear(); c._tick()
    assert started == []
    # 시작 자체가 실패(게임 미등록 등)하면 재시작 예약을 하지 않는다.
    c.frames = False; c._failed('설정에서 게임창을 먼저 등록해 주세요.')
    assert c._restart_at is None
