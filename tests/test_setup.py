"""사용 준비의 저장 상태·선택 순서·새 사용자 초기화(일괄 자동설정 화면은 첫 사용 v3와 함께 없앰)."""

from copy import deepcopy

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, setup_state as state


BOX = {"x": -1200, "y": 400, "w": 42, "h": 16}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(monkeypatch, tmp_path):
    from mabinogi_addon.ui.boss_tab import BossTab
    from mabinogi_addon.ui.stat_bars_tab import StatBarsTab
    from mabinogi_addon.ui.skillbar_tab import SkillbarTab
    for cls in (BossTab, StatBarsTab, SkillbarTab):
        monkeypatch.setattr(cls, "_grab_rect", lambda *args: None)
    from mabinogi_addon.ui import main_window

    class NoFrames:
        def grab(self):
            return None

        def close(self):
            pass

    monkeypatch.setattr(main_window, "create_live_source", lambda region: NoFrames())
    path = tmp_path / "한글 경로" / "설정.json"
    path.parent.mkdir()
    read, write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: write(data, path))
    raw = {f.section: {"enabled": False} for f in state.FEATURES}
    raw["general"] = {"gameExe": "Client.exe"}
    config._write_local_config(raw)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "테스트"})
    return path




def update(section, **values):
    raw = config._read_local_config()
    raw.setdefault(section, {}).update(values)
    config._write_local_config(raw)


@pytest.mark.parametrize("bad", [None, {}, {"x": 0, "y": 0, "w": 0, "h": 10},
                                {"x": True, "y": 0, "w": 10, "h": 10},
                                {"x": 1, "y": 2, "w": 3, "h": "4"}])
def test_broken_region_is_unregistered(bad):
    assert state.missing("tuarim", {"tuarim": {"box": bad}}) == ["tuarim"]






@pytest.mark.parametrize("value", [True, False, None, "false", 0, 1, []])
def test_enabled_interpretation_matches_existing_tabs(settings, value):
    for key, loader in (("tuarim", config.load_tuarim), ("boss", config.load_boss_pattern),
                        ("skillbar", config.load_skillbar), ("stat_bars", config.load_stat_bars)):
        update(state.BY_KEY[key].section, enabled=value)
        if key == "tuarim":
            assert state.enabled(key) == loader()["enabled"]
        else:
            assert not state.enabled(key)
            update(state.BY_KEY[key].section, box=BOX, anchor={"x": 1, "y": 2})
            assert state.enabled(key)


def test_selection_order_and_disabled_items(settings):
    for key in ("skillbar", "tuarim", "buff"):
        state.save_selection(key, True)
        state.remember_order(key, True)
    assert state.pending(automatic_only=True) == ["skillbar", "tuarim", "buff"]
    state.save_selection("tuarim", False)
    state.remember_order("tuarim", False)
    state.save_selection("tuarim", True)
    state.remember_order("tuarim", True)
    assert state.pending(automatic_only=True) == ["skillbar", "buff", "tuarim"]
    update("skillbar", anchor={"x": -1000, "y": 20})
    assert state.pending(automatic_only=True) == ["buff", "tuarim"]


def test_manual_areas_and_shared_prerequisites(settings):
    for key in ("debuff",):
        state.save_selection(key, True)
    update("debuffTracker", enabled=True, captureRegion=BOX)
    update("general", debuffAutoGate=False, debuffGateMode="percent")
    assert state.pending(automatic_only=True) == ["boss"]
    update("bossPattern", box=BOX)
    assert state.pending() == []
    update("customOverlay", enabled=True, overlays=[BOX])
    update("memo", enabled=True)
    state.save_selection("custom", True)
    state.save_selection("memo", True)
    assert state.pending() == ["memo"]
    assert state.pending(automatic_only=True) == []
    update("memoTracker", captureRegion=BOX)
    assert state.pending() == []
    update("statBars", enabled=True, box=BOX, bars={"hp": {"alert": {"on": True}}})
    state.save_selection("stat_bars", True)
    update("bossPattern", box=None)
    assert state.missing("stat_bars") == ["boss"]


@pytest.mark.parametrize("flag", [None, True, False, 0, "false"])
@pytest.mark.parametrize("legacy", ["off", "band", "percent"])
def test_debuff_setup_uses_runtime_mode_from_supplied_settings(settings, monkeypatch, flag, legacy):
    raw = config._read_local_config()
    raw["general"]["debuffGateMode"] = legacy
    if flag is not None:
        raw["general"]["debuffAutoGate"] = flag
    raw["debuffTracker"].update(enabled=True, captureRegion=BOX)
    raw["general"]["setupSelection"] = {"debuff": True}
    config._write_local_config(raw)
    mode = config.load_debuff_runtime_mode()
    before = deepcopy(raw)

    def unexpected_read(*args, **kwargs):
        pytest.fail("supplied setup state must not read a different configuration")

    monkeypatch.setattr(config, "_read_local_config", unexpected_read)
    expected = ["boss"] if mode == "percent" else []
    assert state.missing("debuff", raw) == expected
    assert state.pending(raw, automatic_only=True, feature_keys=("debuff",)) == expected
    assert raw == before
    raw["bossPattern"]["box"] = BOX
    assert state.missing("debuff", raw) == []


































@pytest.mark.parametrize("raw", [{}, {"general": {"theme": "dark"}},
                                {"memo": {"text": "기존 메모", "locked": True}},
                                {"buffTracker": {"captureRegion": BOX}}])
def test_existing_file_without_enabled_keeps_legacy_defaults(settings, raw):
    config._write_local_config(raw)
    before = settings.read_bytes()
    state.initialize_new_user(settings)
    assert settings.read_bytes() == before
    assert state.enabled("buff") == state.valid_box(state.section(raw, "buffTracker").get("captureRegion"))
    assert state.enabled("debuff") == state.valid_box(state.section(raw, "debuffTracker").get("captureRegion"))
    assert not state.enabled("memo") and state.enabled("custom")


def test_new_user_initialization_uses_supplied_path_only(tmp_path):
    path = tmp_path / "한글 새 설정" / "설정.json"
    state.initialize_new_user(path)
    raw = config._read_local_config(path)
    assert set(raw) == {feature.section for feature in state.FEATURES} | {"general"}
    assert raw["general"] == {"firstUse": "pending"} and state.needs_start_screen(raw)  # 첫 사용 안내 v3는 새 설치에만
    assert all(not state.enabled(feature.key, raw) for feature in state.FEATURES)


@pytest.mark.parametrize("backup_only", [False, True])
def test_corrupt_or_backup_config_is_not_treated_as_new(settings, backup_only):
    backup = settings.with_name(settings.name + ".bak")
    settings.rename(backup)
    if not backup_only:
        settings.write_text("{broken", encoding="utf-8")
    before = backup.read_bytes()
    state.initialize_new_user(settings)
    assert backup.read_bytes() == before
    assert settings.exists() is (not backup_only)
    assert not state.enabled("buff")




























































@pytest.mark.parametrize('selected,boxes,expected', [
    (('debuff',), (), True), (('boss',), (), True), (('halo_timer',), (), True),
    (('buff',), (), False), ((), (), False),
    (('debuff',), ('bossPattern',), False),
    (('debuff',), ('debuffTracker',), False),
    (('boss',), ('bossPattern',), False),
])
def test_boss_preparation_follows_actual_pending_regions(settings, selected, boxes, expected):
    for key in selected:
        state.save_selection(key, True)
    for name in boxes:
        update(name, **{'captureRegion' if name == 'debuffTracker' else 'box': BOX})
    assert state.needs_boss_preparation() is expected





@pytest.mark.parametrize("value,expected", [("pending", True), ("done", False), ("later", False), (None, False)])
def test_start_screen_only_for_new_install(settings, value, expected):
    """첫 사용 안내 v3(first-use-v3 4절): 새 설치(firstUse=pending)에만 — 기존 사용자(값 없음)·끝냄·나중에 하기는 다시 띄우지 않는다."""
    update("general", firstUse=value, skipSetup=False)
    assert state.needs_start_screen() is expected
