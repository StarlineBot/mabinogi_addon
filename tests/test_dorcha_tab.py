from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from mabinogi_addon import config, image_io
from mabinogi_addon.ui.dorcha_tab import DorchaTab
from test_dorcha_reader import crop


@pytest.fixture
def runtime(monkeypatch):
    app = QApplication.instance() or QApplication([])
    other = {"tuarim":{"enabled":False,"thresholds":[95,98],"box":dict(x=1,y=2,w=42,h=16)},
             "statBars":{"enabled":False},"bossPattern":{"enabled":False}}
    config._write_local_config({**other,"dorcha":{"box":dict(x=941,y=948,w=28,h=23),
                                                 "pos":dict(x=-800,y=200)}})
    state = SimpleNamespace(game=True,own=False,logged=True,frame=crop("2026-10-16 211456"),captures=0)
    monkeypatch.setattr(config,"load_discord_user",lambda: {"id":"qa"} if state.logged else None)
    watcher = SimpleNamespace(is_game_active=lambda: state.game,is_self_active=lambda: state.own)
    tab = DorchaTab(watcher)
    tab._timer.stop()
    def capture(*args):
        state.captures += 1
        return state.frame
    monkeypatch.setattr(tab,"_grab_rect",capture)
    try:
        yield tab,state,other
    finally:
        tab.shutdown()
        if tab._overlay is not None:
            tab._overlay.deleteLater()
        tab.close()
        tab.deleteLater()
        app.processEvents()


def test_default_off_no_capture_and_independent_settings(runtime):
    tab,state,other = runtime
    tab._tick()
    assert state.captures == 0 and tab._overlay is None
    tab.enable.setChecked(True)
    tab._tick()
    assert tab._overlay.value == 13 and tab._overlay.isVisible()
    assert tab._overlay.pos().x() == -800
    tab._on_scale(200)
    tab.lock_chk.setChecked(False)
    saved = config._read_local_config()
    assert {key:saved[key] for key in other} == other
    assert "value" not in saved["dorcha"]
    assert saved["dorcha"]["pos"] == dict(x=-800,y=200)
    assert config.load_dorcha()["enabled"]


@pytest.mark.parametrize("failure", [None,"black","partial"])
def test_failure_is_unknown_not_zero_and_recovery_is_immediate(runtime,failure):
    tab,state,_ = runtime
    tab.enable.setChecked(True)
    tab._tick()
    original = state.frame.copy()
    state.frame = None if failure is None else np.zeros_like(original)
    if failure == "partial":
        state.frame = original.copy()
        state.frame[:,:14] = 0
    tab._tick()
    assert tab._overlay.isVisible() and tab._overlay.value is None and tab.preview.value is None
    assert tab.value_label.text().endswith("--/15")
    state.frame = crop("2026-10-09 185117",708,875)
    tab._tick()
    assert tab._overlay.value == 0 and tab.value_label.text().endswith("0/15")
    state.frame = original
    tab._tick()
    assert tab._overlay.value == 13


@pytest.mark.parametrize("reason", ["pause","disable","logout","inactive","region","shutdown"])
def test_interruption_drops_value_and_reuses_one_window(runtime,reason):
    tab,state,_ = runtime
    tab.enable.setChecked(True)
    tab._tick()
    overlay = tab._overlay
    if reason == "pause": tab.set_paused(True)
    elif reason == "disable": tab.enable.setChecked(False)
    elif reason == "logout": state.logged = False
    elif reason == "inactive": state.game = False
    elif reason == "region": tab._region = None
    else: tab.shutdown()
    tab._tick()
    if reason == "logout":
        assert overlay.isVisible() and overlay.value == 13
        assert tab.enable.isEnabled() and tab.region_btn.isEnabled()
        assert not tab.auto_find_btn.isEnabled()
        return
    assert not overlay.isVisible() and overlay.value is None
    if reason != "shutdown":
        tab.set_paused(False)
        tab.enable.setChecked(True)
        state.logged,state.game = True,True
        tab._region = tab._cfg["box"]
        tab._tick()
        assert tab._overlay is overlay and overlay.value == 13


def test_self_focus_only_shows_when_editing_this_tab(runtime):
    tab,state,_ = runtime
    tab.enable.setChecked(True)
    state.game,state.own = False,True
    tab._tick()
    assert state.captures == 0
    tab.show()
    tab._tick()
    assert tab._overlay.isVisible()
    tab.hide()
    tab._tick()
    assert not tab._overlay.isVisible()
    state.game = True
    tab._tick()
    assert tab._overlay.isVisible()


def test_region_save_failure_does_not_replace_registration(runtime,monkeypatch):
    tab,_,_ = runtime
    previous = dict(tab._region)
    def failure(*args):
        raise PermissionError("controlled")
    monkeypatch.setattr(config,"save_dorcha",failure)
    with pytest.raises(PermissionError):
        tab._apply_region(0,0,28,23)
    assert tab._region == previous


def test_settings_save_errors_are_coalesced(runtime,monkeypatch):
    tab,_,_ = runtime
    errors=[]
    monkeypatch.setattr(QMessageBox,"warning",lambda *a:errors.append(1))
    def failure(*args):
        raise PermissionError("controlled")
    monkeypatch.setattr(config,"save_dorcha",failure)
    tab.enable.setChecked(True)
    tab.scale_spin.setValue(200)
    tab.lock_chk.setChecked(False)
    assert len(errors) == 1


def test_repeated_toggle_has_one_capture_per_tick_and_bounded_resources(runtime):
    tab,state,_ = runtime
    tab.enable.setChecked(True)
    tab._tick()
    overlay = tab._overlay
    for _ in range(200):
        tab.set_paused(True)
        tab._tick()
        tab.set_paused(False)
        tab._tick()
    assert state.captures == 201 and tab._overlay is overlay
    tab.shutdown()
    tab._tick()
    assert state.captures == 201 and not tab._timer.isActive()


@pytest.mark.parametrize("bad", [None,[],{"scale":"150","enabled":"true","pos":{"x":True,"y":2}},
                                {"scale":float('nan'),"box":{"x":0,"y":0,"w":-1,"h":23}}])
def test_malformed_settings_use_only_own_defaults(bad,tmp_path):
    path = tmp_path/"한글 경로"/"설정.json"
    raw = {"tuarim":{"enabled":True},"dorcha":bad}
    config._write_local_config(raw,path)
    before = path.read_bytes()
    assert config.load_dorcha(path) == dict(enabled=False,showTuarim=False,box=None,pos=None,scale=150,locked=True)
    assert path.read_bytes() == before


def test_eye_asset_is_native_boss_crop_and_matches_center():
    from pathlib import Path
    from mabinogi_addon.detect.icon_matcher import match_icon
    from mabinogi_addon.tracker.debuff_engine import DebuffEngine
    root = Path(__file__).resolve().parents[1]
    name = "이면을 보는 눈"
    template = image_io.imread(root/"src/mabinogi_addon/assets/debuff/icon"/f"{name}.png")
    native = image_io.imread(root/"docs/qa/assets/eye_native_20261016/boss.png")
    center = image_io.imread(root/"docs/qa/assets/eye_native_20261016/center.png")
    np.testing.assert_array_equal(template,native)
    assert template.shape == (16,16,3)
    assert match_icon(center,template).score >= .96
    for mode in ("off","auto"):
        engine = DebuffEngine({name:template},[name],gate_mode=mode)
        for tick in range(8):
            result = engine.tick(native,tick*.2)
        assert result.entries == []
