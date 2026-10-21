from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, feature_access
from mabinogi_addon.ui.dorcha_tab import DorchaTab
from test_navigation import window
from test_stat_bars_stability import pipeline


@pytest.fixture(scope="module", autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.mark.parametrize('user,expected', [(None,False), ({'id':'other'},False),
    ({'id':'other','name':'HP Starline'},False), ({'id':feature_access.CREATOR_DISCORD_ID},True)])
def test_numeric_creator_identity(monkeypatch, user, expected):
    monkeypatch.setattr(config,'load_discord_user',lambda:user)
    assert feature_access.is_creator() is expected


def test_one_time_reset_preserves_every_other_setting(tmp_path):
    path = tmp_path / '한글 경로' / '설정.json'
    raw = {'dorcha':{'showTuarim':True,'enabled':True,'scale':175,'locked':False,
                   'box':dict(x=-100,y=50,w=28,h=23),'pos':dict(x=-500,y=300)},
           'tuarim':{'enabled':True,'thresholds':[90,95],'sounds':[True,False]},'unknown':[1,2]}
    config._write_local_config(raw,path)
    config.migrate_tuarim_alpha(path)
    saved = config._read_local_config(path)
    expected = deepcopy(raw)
    expected['dorcha'].update(showTuarim=False,tuarimAlphaReset=1)
    assert saved == expected
    saved['dorcha']['showTuarim'] = True
    config._write_local_config(saved,path)
    config.migrate_tuarim_alpha(path)
    assert config._read_local_config(path) == saved


def test_failed_migration_never_marks_complete(monkeypatch):
    raw = {'dorcha':{'showTuarim':True,'scale':175},'tuarim':{'enabled':True}}
    config._write_local_config(raw)
    original = config._write_local_config
    def denied(*a,**k):
        raise PermissionError('test')
    monkeypatch.setattr(config,'_write_local_config',denied)
    with pytest.raises(PermissionError):
        config.migrate_tuarim_alpha()
    assert config._read_local_config() == raw
    tab = DorchaTab(SimpleNamespace(is_game_active=lambda:False,is_self_active=lambda:False))
    try:
        assert not tab._alpha_ready
        assert not tab.percent_requested()
        assert config._read_local_config() == raw
    finally:
        tab.shutdown()
        tab.close()
    monkeypatch.setattr(config,'_write_local_config',original)
    config.migrate_tuarim_alpha()
    assert config._read_local_config()['dorcha']['tuarimAlphaReset'] == 1


@pytest.mark.parametrize('user',[None, {'id':'regular'}, {'id':feature_access.CREATOR_DISCORD_ID}])
def test_basic_controls_and_alpha_are_independent(window,monkeypatch,user):
    w,app = window
    monkeypatch.setattr(config,'load_discord_user',lambda:user)
    w._open_setup_feature('dorcha')
    d = w.dorcha_tab
    d._apply_gate()
    w.stat_bars_tab._apply_login_gate()
    w.skillbar_tab._apply_login_gate()
    app.processEvents()
    assert d.enable.isEnabled() and d.region_btn.isEnabled()
    assert w.stat_bars_tab.region_btn.isEnabled() and w.stat_bars_tab.alert_sound_chk.isEnabled()
    assert w.skillbar_tab.anchor_btn.isEnabled() and w.skillbar_tab.scale_spin.isEnabled()
    assert w.resource_tab.percent_chk.isHidden() is (not feature_access.is_creator())
    assert d.auto_find_btn.isEnabled()
    assert w.stat_bars_tab.collect_chk.isEnabled() is (user is not None)
    assert w.skillbar_tab.auto_find_btn.isEnabled()


def test_account_revocation_removes_only_percent(runtime_policy):
    w,state,pump = runtime_policy
    w.dorcha_tab.enable.setChecked(True)
    w.resource_tab.percent_chk.setChecked(True)
    w.tuarim_tab.enable.setChecked(True)
    pump()
    assert w.dorcha_tab._overlay._show_tuarim
    state.logged = False
    pump()
    assert w.dorcha_tab._overlay.isVisible()
    assert w.dorcha_tab._overlay.value == 13
    assert not w.dorcha_tab._overlay._show_tuarim
    assert w.dorcha_tab._overlay.percent is None
    assert w.resource_tab.percent_chk.isHidden()
    assert config.load_dorcha()['showTuarim']
    assert state.fired == [90,95]


from test_resource_integration import runtime as runtime_policy


def test_logged_out_stat_capture_sound_and_shake_continue(pipeline,monkeypatch):
    tab,state,_ = pipeline
    monkeypatch.setattr(config,'load_discord_user',lambda:None)
    tab._tick()
    state.now = .41
    tab._tick()
    assert all(overlay.isVisible() for overlay in tab._overlays.values())
    assert tab._overlays['hp'].warning_active
    assert state.sounds == [.41]
    assert tab.has_active_alert()
    assert not tab.collect_chk.isEnabled()
    assert tab.auto_find_btn.isEnabled()
    monkeypatch.setattr(tab, '_write_shot', lambda *a:pytest.fail('unauthorized snapshot'))
    tab._save_snapshot()
    from mabinogi_addon import autofind_diagnostics
    calls=[]
    from PySide6.QtWidgets import QMessageBox
    warnings=[]
    monkeypatch.setattr(QMessageBox,'warning',lambda *a,**k:warnings.append(a))
    monkeypatch.setattr(autofind_diagnostics,'perform_autofind',lambda *a,**k:(calls.append(a) or (None,0,0,None)))
    tab._on_auto_find()
    assert len(calls)==1 and len(warnings)==1  # Capture failure is reported; snapshots remain gated.


def test_logged_out_skillbar_still_slices_twelve_groups(window,monkeypatch):
    import numpy as np
    from mabinogi_addon.ui.skillbar_mirror import SRC_H,SRC_W
    w,_ = window
    monkeypatch.setattr(config,'load_discord_user',lambda:None)
    tab = w.skillbar_tab
    tab._watcher = SimpleNamespace(is_game_active=lambda:True,is_self_active=lambda:False)
    tab._anchor = dict(x=0,y=0)
    monkeypatch.setattr(tab,'_grab_rect',lambda *a:np.full((SRC_H,SRC_W,3),100,np.uint8))
    tab._tick()
    assert len(tab._overlays) == 12
    assert all(overlay.isVisible() for overlay in tab._overlays.values())
    assert all(len(overlay._cells) == 4 and all(cell is not None for cell in overlay._cells)
               for overlay in tab._overlays.values())
    assert tab.auto_find_btn.isEnabled()
