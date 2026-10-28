"""Independent combinations, retained settings and one shared percent observation."""

from copy import deepcopy
from itertools import product
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.feature_access import CREATOR_DISCORD_ID
from mabinogi_addon.ui import dorcha_tab, tuarim_tab
from mabinogi_addon.ui.dorcha_tab import DorchaTab
from mabinogi_addon.ui.tuarim_tab import TuarimTab
from mabinogi_addon.ui.resource_tab import ResourceTab
from mabinogi_addon.ui import region_registration as registration
from test_navigation import window


@pytest.fixture
def runtime(window,monkeypatch):
    w,app = window
    t,d = w.tuarim_tab,w.dorcha_tab
    state = SimpleNamespace(raw=95,dorcha=13,logged=True,game=True,own=False,
                            percent_captures=0,dorcha_captures=0,frame=True,fired=[])
    watcher = SimpleNamespace(is_game_active=lambda:state.game,is_self_active=lambda:state.own)
    t._watcher = d._watcher = watcher
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':CREATOR_DISCORD_ID} if state.logged else None)
    monkeypatch.setattr(tuarim_tab,'read_percent',lambda frame:state.raw)
    monkeypatch.setattr(dorcha_tab,'read_dorcha',lambda frame,*_:state.dorcha if frame is not None else None)
    monkeypatch.setattr(t,'_play',state.fired.append)
    monkeypatch.setattr(d,'_search_target',lambda:None)
    def percent_capture(*args):
        state.percent_captures += 1
        return np.zeros((16,42,3),np.uint8) if state.frame else None
    def dorcha_capture(*args):
        state.dorcha_captures += 1
        return np.zeros((23,28,3),np.uint8)
    monkeypatch.setattr(t,'_grab_rect',percent_capture)
    monkeypatch.setattr(d,'_grab_rect',dorcha_capture)
    boxes = {"dorcha": (534,122,28,23), "tuarim": (560,150,42,16)}
    assert registration.save_boxes(d, boxes)
    d._accept_region(*boxes["dorcha"])
    t._accept_region(*boxes["tuarim"])
    def pump(count=3):
        for _ in range(count):
            t._tick_enabled()
            d._tick()
    return w,state,pump


def test_runtime_registration_matches_persisted_regions_and_ui(runtime):
    w, _, _ = runtime
    for key, controller in (("dorcha", w.dorcha_tab), ("tuarim", w.tuarim_tab)):
        assert controller._region == config._read_local_config()[key]["box"]
        assert controller.clear_region_btn.isEnabled()


@pytest.mark.parametrize('dorcha,percent,alert',list(product((False,True),repeat=3)))
def test_all_eight_independent_combinations(runtime,dorcha,percent,alert):
    w,s,pump = runtime
    d,t,r = w.dorcha_tab,w.tuarim_tab,w.resource_tab
    d.enable.setChecked(dorcha)
    r.percent_chk.setChecked(percent)
    t.enable.setChecked(alert)
    pump()
    assert s.percent_captures == (3 if percent or alert else 0)
    assert s.dorcha_captures == (3 if dorcha else 0)
    assert s.fired == ([90,95] if alert else [])
    assert (d._overlay is not None and d._overlay.isVisible()) == (dorcha or percent)
    if dorcha or percent:
        assert (d._overlay._show_dorcha,d._overlay._show_tuarim) == (dorcha,percent)
        assert d._overlay.percent == (95 if percent else None)
        assert d._overlay.value == (13 if dorcha else None)
    assert (d.enable.isChecked(),r.percent_chk.isChecked(),t.enable.isChecked()) == (dorcha,percent,alert)


@pytest.mark.parametrize('dorcha_value,percent_value',[(None,95),(13,None),(None,None),(0,0)])
def test_failures_clear_only_the_failed_element(runtime,dorcha_value,percent_value):
    w,s,pump = runtime
    d,t,r = w.dorcha_tab,w.tuarim_tab,w.resource_tab
    d.enable.setChecked(True);r.percent_chk.setChecked(True)
    pump()
    s.raw,s.dorcha = percent_value,dorcha_value
    pump()
    assert d._overlay.value == dorcha_value
    assert d._overlay.percent == percent_value
    assert d._overlay.isVisible()
    assert '--%' in d.value_label.text() if percent_value is None else f'{percent_value}%' in d.value_label.text()


def test_percent_toggle_and_navigation_do_not_repeat_alerts(runtime):
    w,s,pump = runtime
    d,t,r = w.dorcha_tab,w.tuarim_tab,w.resource_tab
    t.enable.setChecked(True)
    pump()
    assert s.fired == [90,95]
    timers = set(w.findChildren(QTimer))
    for _ in range(30):
        r.percent_chk.setChecked(True)
        w._open_setup_feature('tuarim')
        pump()
        r.percent_chk.setChecked(False)
        w._open_setup_feature('buff')
        pump()
    pump()
    assert s.fired == [90,95]
    assert set(w.findChildren(QTimer)) == timers
    from mabinogi_addon.tracker.tuarim import REARM_FRAMES
    s.raw = 0
    pump(REARM_FRAMES+2)
    s.raw = 95
    pump()
    assert s.fired == [90,95,90,95]


def test_logout_keeps_percent_display_and_pause_hides_until_resumed(runtime):
    # 2026-10-28 기능 공개 정책 7절: 투아림 % 표시도 로그인 없이(이전: 로그아웃하면 % 표시가 꺼짐)
    w,s,pump = runtime
    d,t,r = w.dorcha_tab,w.tuarim_tab,w.resource_tab
    d.set_paused(True)
    r.percent_chk.setChecked(True)
    t.enable.setChecked(True)
    pump()
    assert s.fired == [90,95] and d._overlay is None
    d.set_paused(False)
    pump()
    assert d._overlay.isVisible()
    s.logged = False
    pump()
    assert d._overlay.isVisible() and d._overlay.percent == 95
    assert r.percent_chk.isEnabled() and r.percent_chk.isChecked()
    assert t.enable.isEnabled() and t.enable.isChecked()
    assert config.load_dorcha()['showTuarim']
    assert s.fired == [90,95]


def test_percent_only_needs_no_dorcha_region_and_keeps_placement(runtime):
    w,s,pump = runtime
    d,t,r = w.dorcha_tab,w.tuarim_tab,w.resource_tab
    d._region = None
    r.percent_chk.setChecked(True)
    pump()
    overlay = d._overlay
    overlay.move(QPoint(-900,180))
    overlay.moved.emit()
    d.scale_spin.setValue(200)
    d.lock_chk.setChecked(False)
    before = deepcopy(config.load_dorcha())
    for _ in range(10):
        d.enable.setChecked(True);pump()
        d.enable.setChecked(False);pump()
    after = config.load_dorcha()
    for key in ('pos','scale','locked'):
        assert after[key] == before[key]
    assert d._overlay is overlay and overlay.pos() == QPoint(-900,180)
    assert not overlay.locked and overlay.percent == 95
    assert s.dorcha_captures == 0


@pytest.mark.parametrize('reason',['capture','inactive','hundred','shutdown','busy'])
def test_percent_cannot_keep_stale_value(runtime,reason):
    w,s,pump = runtime
    d,t,r = w.dorcha_tab,w.tuarim_tab,w.resource_tab
    r.percent_chk.setChecked(True)
    pump()
    assert d._overlay.percent == 95
    if reason == 'capture': s.frame = False
    elif reason == 'inactive': s.game = False
    elif reason == 'hundred': s.raw = None
    elif reason == 'shutdown': t.shutdown()
    else: t._autofind_busy = True
    pump()
    assert d._overlay.percent is None
    if reason in ('inactive','shutdown','busy'):
        assert not d._overlay.isVisible()


@pytest.mark.parametrize('existing_percent',[None,False,True])
def test_construction_and_recreation_preserve_all_existing_settings(existing_percent,monkeypatch):
    app = QApplication.instance() or QApplication([])
    raw = {'tuarim':dict(enabled=True,box=dict(x=-100,y=40,w=58,h=28),thresholds=[92,98],sounds=[False,True]),
           'dorcha':dict(enabled=True,box=dict(x=50,y=70,w=28,h=23),pos=dict(x=-900,y=180),scale=175,locked=False,tuarimAlphaReset=1),
           'unknown':{'preserve':[1,2,3]}}
    if existing_percent is not None:
        raw['dorcha']['showTuarim'] = existing_percent
    config._write_local_config(raw)
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':'test'})
    watcher = SimpleNamespace(is_game_active=lambda:False,is_self_active=lambda:False)
    for _ in range(3):
        t,d = TuarimTab(watcher),DorchaTab(watcher)
        r = ResourceTab(d,t)
        t._timer.stop();d._timer.stop()
        try:
            assert r.percent_chk.isChecked() == bool(existing_percent)
            assert t.enable.isChecked() and d.enable.isChecked()
            assert t._thresholds == [92,98] and t._sounds == [False,True]
            assert d._cfg['scale'] == 175 and not d._cfg['locked']
            assert config._read_local_config() == raw
        finally:
            t.shutdown();d.shutdown();r.close();r.deleteLater();app.processEvents()


def test_percent_save_error_is_reported_without_overwriting_settings(runtime,monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    w,s,pump = runtime
    before = deepcopy(config._read_local_config())
    errors = []
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:errors.append(args[1]))
    def denied(*args):
        raise PermissionError('controlled')
    monkeypatch.setattr(config,'save_dorcha',denied)
    w.resource_tab.percent_chk.setChecked(True)
    assert errors == ['설정 저장 실패']
    assert config._read_local_config() == before
