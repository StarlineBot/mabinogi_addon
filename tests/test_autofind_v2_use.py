"""자동 찾기 v2 사용 값(docs/autofind-v2-creator-spec.md 2.1절) — 영역 있음 ≠ 사용, 보스바 소비자, 기존 동작 유지."""
import json

import pytest

from mabinogi_addon import autofind_regions as afr, config, setup_state

BOX = {"x": 1, "y": 2, "w": 30, "h": 40}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"buffTracker": {"captureRegion": BOX}, "skillbar": {"anchor": {"x": 5, "y": 6}}}),
                    encoding="utf-8")
    monkeypatch.setattr(config, "_read_local_config", lambda p=path: json.loads(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(config, "_write_local_config",
                        lambda data, p=path: path.write_text(json.dumps(data), encoding="utf-8"))
    afr.reset_for_tests()
    yield path
    afr.reset_for_tests()


def test_v2_off_keeps_region_means_enabled_and_saved_region(isolated):
    assert setup_state.enabled("buff") and not setup_state.enabled("debuff")  # 지금 규칙(영역 = 사용)
    assert afr.region_for("buff", BOX) == BOX and afr.use_on("boss") and afr.wanted("boss")
    assert "autofindV2" not in json.loads(isolated.read_text(encoding="utf-8"))


def test_initial_use_values_filled_once_from_saved_regions(isolated):
    afr.activate(True)
    use = setup_state.autofind_v2_use_values()
    assert use == {"buff": True, "debuff": False, "boss": False, "halo_timer": False, "skillbar": True}
    raw = json.loads(isolated.read_text(encoding="utf-8"))
    raw["debuffTracker"] = {"captureRegion": BOX}  # 나중에 영역이 생겨도 이미 채운 값은 그대로
    isolated.write_text(json.dumps(raw), encoding="utf-8")
    assert setup_state.autofind_v2_use_values()["debuff"] is False


def test_use_off_stops_reading_but_keeps_region(isolated):
    afr.activate(True)
    afr.set_use_values(setup_state.autofind_v2_use_values())
    afr.set_region("buff", {"x": 9, "y": 9, "w": 9, "h": 9})
    assert afr.region_for("buff", BOX) == {"x": 9, "y": 9, "w": 9, "h": 9}
    events = []
    afr.subscribe(lambda key, user: events.append(key))
    before = json.loads(isolated.read_text(encoding="utf-8"))["buffTracker"]
    setup_state.save_enabled("buff", False)
    assert afr.region_for("buff", BOX) is None and not setup_state.enabled("buff")  # 읽기 멈춤(캡처 0)
    assert "buff" in events  # 기능 다시 시작(멈춤)
    raw = json.loads(isolated.read_text(encoding="utf-8"))
    assert raw["buffTracker"] == before and raw["autofindV2"]["use"]["buff"] is False  # 저장 영역은 그대로
    setup_state.save_enabled("buff", True)
    assert afr.region_for("buff", BOX) == {"x": 9, "y": 9, "w": 9, "h": 9}  # 다시 켜면 찾아 둔 자리로 바로


@pytest.mark.parametrize("use,extra,expected", [
    ({}, False, False),  # 모두 꺼짐 → 보스바 캡처 0
    ({"debuff": True}, False, True),
    ({"boss": True}, False, True),
    ({"halo_timer": True}, False, True),
    ({}, True, True),  # 체력바 보스전 알림·블랙박스
])
def test_boss_bar_read_only_when_some_consumer_is_on(use, extra, expected):
    afr.activate(True)
    afr.set_use_values(use, boss_extra=lambda: extra)
    afr.set_region("boss", BOX)
    assert afr.wanted("boss") is expected
    assert (afr.region_for("boss", None) is not None) is expected


def test_boss_pattern_off_while_bar_read_for_debuff():
    afr.activate(True)
    afr.set_use_values({"debuff": True, "boss": False})
    assert afr.wanted("boss") and not afr.use_on("boss")  # 바는 읽되 패턴 알림은 멈춤(보스 탭 pattern_on)


def test_home_rows_show_switch_and_location_only_with_v2():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace

    from mabinogi_addon import autofind_v2 as v2
    from mabinogi_addon.ui.main_window import MainWindow
    afr.activate(True)
    afr.set_use_values({"buff": True, "debuff": False, "boss": True, "halo_timer": False, "skillbar": True})
    engine = v2.Engine()
    engine.items["boss"].status = "found"
    engine.items["boss"].box = (1, 2, 3, 4)
    engine.items["halo_timer"].status = "waiting"
    engine.items["skillbar"].status = "missing"
    engine.phase = "stable"
    afr.set_region("boss", BOX)
    afr.set_state_source(lambda key: {"found": "found", "waiting": "waiting", "missing": "missing"}.get(
        engine.items[key].status, "searching"))
    afr.region_for("tuarim", {"x": 1, "y": 1, "w": 5, "h": 5})  # 투아림: 못 찾았지만 저장 영역(v1)
    engine.items["tuarim"].status = "missing"
    shown = {"stat_bars": False, "dorcha": True, "tuarim": True}
    me = SimpleNamespace(_HOME_V2_SWITCHES=MainWindow._HOME_V2_SWITCHES, _HOME_FEATURES=MainWindow._HOME_FEATURES,
                         _autofind_v2=SimpleNamespace(engine=engine))
    me._autofind_place = lambda key: MainWindow._autofind_place(me, key)
    me._home_place_row = lambda *a: MainWindow._home_place_row(me, *a)
    me._home_feature_on = lambda k: (afr.use_on(MainWindow._HOME_FEATURES[k]) if k in MainWindow._HOME_V2_SWITCHES
                                     else shown[k])
    rows = {"buff": ("추적 중", "ok"), "debuff": ("영역 지정 필요", "warn"), "boss": ("영역 지정 필요", "warn"),
            "halo": ("영역 지정 필요", "warn"), "skillbar": ("영역 지정 필요", "warn"),
            "stat_bars": ("꺼짐", "muted", False), "dorcha": ("표시 중", "ok", True), "tuarim": ("영역 지정 필요", "warn", True)}
    MainWindow._home_v2_rows(me, rows, False, True)
    assert rows["buff"] == ("켜짐 · 동작 중", "ok", True)
    assert rows["debuff"] == ("꺼짐 · 위치 찾음", "muted", False)  # 디버프 자리 = 보스바 위
    assert rows["boss"] == ("켜짐 · 위치 찾음", "muted", True)
    assert rows["halo"] == ("꺼짐 · 화면에 보이면 찾아요", "muted", False)
    assert rows["skillbar"] == ("켜짐 · 못 찾음 — 기능 화면에서 맞추기", "warn", True)
    assert rows["stat_bars"] == ("꺼짐 · 위치 찾는 중", "muted", False)
    assert rows["dorcha"] == ("켜짐 · 동작 중", "ok", True)
    assert rows["tuarim"] == ("켜짐 · 저장된 영역 사용", "muted", True)


@pytest.mark.parametrize("creator,disabled,attached,active", [
    (False, True, False, False),  # 비상 값으로 꺼짐(비제작자): 진단 구역 없음, 저장 영역 그대로
    (True, True, True, False),    # 비상 값으로 꺼짐(제작자): 진단 구역에 '꺼짐'만
])
def test_setup_off_only_with_emergency_value(monkeypatch, creator, disabled, attached, active):
    """0.45.0: 모든 사용자 항상 켬 — 숨은 비상 값 autofind.disabled일 때만 꺼짐(first-use-v3 4.1·6절 7)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from mabinogi_addon import feature_access
    from mabinogi_addon.ui.main_window import MainWindow
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(feature_access, "is_creator", lambda: creator)
    monkeypatch.setattr(config, "load_autofind_disabled", lambda *a: disabled)
    sections = []
    me = SimpleNamespace(settings_tab=SimpleNamespace(attach_autofind_v2=sections.append), _autofind_v2=None)
    MainWindow._setup_autofind_v2(me)
    assert bool(sections) is attached and afr.active() is active and me._autofind_v2 is None
    if sections:
        assert sections[0]._controller is None and not sections[0].again.isVisibleTo(sections[0])
        assert "autofind.disabled" in sections[0].phase.text()


def test_setup_on_for_non_creator_with_fixed_from_config(monkeypatch):
    """비제작자도 켜짐 + 지난 실행의 직접 지정 고정을 읽어 시작, 진단 구역은 만들지 않음."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from mabinogi_addon import feature_access
    from mabinogi_addon.ui import main_window
    from mabinogi_addon.ui.main_window import MainWindow
    monkeypatch.setattr(feature_access, "is_creator", lambda: False)
    monkeypatch.setattr(config, "load_autofind_disabled", lambda *a: False)
    monkeypatch.setattr(config, "load_autofind_fixed", lambda *a: ["buff"])
    started = []

    class Controller:
        def __init__(self, *a, **k):
            from types import SimpleNamespace
            self.changed = SimpleNamespace(connect=lambda fn: None)

        def start(self):
            started.append(True)

    monkeypatch.setattr("mabinogi_addon.ui.autofind_v2_controller.AutofindV2Controller", Controller)
    monkeypatch.setattr("mabinogi_addon.setup_state.autofind_v2_use_values", lambda *a: {k: True for k in afr.USE_KEYS})
    sections = []

    class Section:
        def __init__(self):
            self.calls = []

        def set_autofind_key(self, key):
            pass

        def set_autofind_keys(self, keys):
            pass

    from types import SimpleNamespace
    tab = lambda: SimpleNamespace(region_section=Section())  # noqa: E731
    boss = tab()
    boss.halo_capture = tab()
    me = SimpleNamespace(settings_tab=SimpleNamespace(attach_autofind_v2=sections.append), _autofind_v2=None,
                         buff_tab=tab(), debuff_tab=tab(), boss_tab=boss, skillbar_tab=tab(), stat_bars_tab=tab(),
                         resource_tab=tab(), _watcher=None, _autofind_wanted=lambda k: True,
                         _on_autofind_region=lambda *a: None, _on_autofind_changed=lambda: None)
    MainWindow._setup_autofind_v2(me)
    assert afr.active() and afr.is_fixed("buff") and started == [True] and sections == []
    assert main_window is not None


def test_dorcha_tuarim_autofind_line_on_top_of_common_tab(monkeypatch):
    """도르카·투아림 공통 탭 맨 위(접어도 보임)에 '자동(v2) · 도르카 … · 투아림 …' 한 줄(사용자 11-07) — v2 꺼짐이면 숨김·문구 그대로."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.dorcha_tab import DorchaTab
    from mabinogi_addon.ui.region_section import refresh_autofind
    from mabinogi_addon.ui.resource_tab import ResourceTab
    from mabinogi_addon.ui.tuarim_tab import TuarimTab
    QApplication.instance() or QApplication([])
    watcher = SimpleNamespace(is_game_active=lambda: False, is_self_active=lambda: False)
    d, t = DorchaTab(watcher), TuarimTab(watcher)
    r = ResourceTab(d, t)
    try:
        section = r.region_section
        section.set_autofind_keys({"dorcha": "도르카", "tuarim": "투아림"})
        assert section.auto_badge.isHidden()  # v2 꺼짐
        assert d.region_label.text() == "영역 미지정"
        afr.activate(True)
        afr.set_use_values({k: True for k in afr.USE_KEYS})
        afr.set_region("dorcha", {"x": 1180, "y": 96, "w": 120, "h": 30})
        refresh_autofind("dorcha")
        r.refresh_registration()
        d._update_region_label()
        t._update_region_label()
        assert section.auto_badge.text() == "자동으로 찾기 · 도르카 위치 찾음 · 투아림 찾는 중"
        assert not section.auto_badge.isHidden() and section.registered  # 접힌 상태에서도 맨 위
        assert d.region_label.text().startswith("찾은 자리  1180, 96") and t.region_label.text() == "위치 찾는 중이에요"
        afr.user_set("tuarim")
        refresh_autofind("tuarim")
        assert section.auto_badge.text() == "자동으로 찾기 · 도르카 위치 찾음 · 투아림 직접 지정"
    finally:
        r.shutdown()
        d.shutdown()
        t.shutdown()
