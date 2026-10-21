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
    assert c.window.settings_tab.optimization_button.isHidden()
    assert not c.frames and not c.collector.active and not c.engine.busy
    c.start_frames()
    assert not c.frames
    monkeypatch.setattr(module,'is_creator',lambda:True)
    c.refresh_access()
    assert not c.window.settings_tab.optimization_button.isHidden()
    c.open()
    assert c.dialog is not None and not c.frames
    assert not hasattr(c.dialog,'collector_path')
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
    c.dialog.scale.setValue(200)
    assert c.overlay.width()==420 and not c.frames and not c.overlay.isVisible()
    c.dialog.lock.setChecked(False)
    stored=module.config._read_local_config()['frameMeter']
    assert stored['scale']==200 and stored['overlay']['locked'] is False
    assert c.dialog.scale.value()==200
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
    c.frames=True;c.stream=FrameStream(123,1000);c.collector.active=True
    for _ in range(3): c.collector._read()
    assert c.frames and c.stream.snapshot(100.52)['fps']==pytest.approx(50)
    c.stop_frames()
