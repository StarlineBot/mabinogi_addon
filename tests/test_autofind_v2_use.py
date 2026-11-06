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
    afr.set_region("boss", BOX)
    me = SimpleNamespace(_HOME_V2_SWITCHES=MainWindow._HOME_V2_SWITCHES, _HOME_FEATURES=MainWindow._HOME_FEATURES,
                         _autofind_v2=SimpleNamespace(engine=engine))
    me._autofind_place = lambda key: MainWindow._autofind_place(me, key)
    rows = {"buff": ("추적 중", "ok"), "debuff": ("영역 지정 필요", "warn"), "boss": ("영역 지정 필요", "warn"),
            "halo": ("영역 지정 필요", "warn"), "skillbar": ("영역 지정 필요", "warn"),
            "stat_bars": ("꺼짐", "muted", False), "dorcha": ("표시 중", "ok", True), "tuarim": ("영역 지정 필요", "warn", True)}
    MainWindow._home_v2_rows(me, rows, False, True)
    assert rows["buff"] == ("추적 중", "ok", True)
    assert rows["debuff"] == ("꺼짐 · 위치 찾음", "muted", False)  # 디버프 자리 = 보스바 위
    assert rows["boss"] == ("대기 중 · 위치 찾음", "muted", True)
    assert rows["halo"] == ("꺼짐 · 나타나면 찾음", "muted", False)
    assert rows["skillbar"] == ("대기 중 · 위치 찾는 중", "muted", True)
    assert rows["stat_bars"] == ("꺼짐 · 위치 찾는 중", "muted", False) and rows["dorcha"] == ("표시 중", "ok", True)
    assert rows["tuarim"] == ("대기 중 · 위치 찾는 중", "muted", True)


@pytest.mark.parametrize("creator,enabled,attached,active", [
    (False, True, False, False),  # 비제작자: 설정 화면·동작 변화 0
    (True, False, True, False),   # 제작자 + 꺼짐: 스위치만(다음 실행부터)
])
def test_setup_gating_for_non_creator_and_v2_off(monkeypatch, creator, enabled, attached, active):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from mabinogi_addon import feature_access
    from mabinogi_addon.ui.main_window import MainWindow
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(feature_access, "is_creator", lambda: creator)
    monkeypatch.setattr(config, "load_autofind_v2_enabled", lambda *a: enabled)
    sections = []
    me = SimpleNamespace(settings_tab=SimpleNamespace(attach_autofind_v2=sections.append), _autofind_v2=None)
    MainWindow._setup_autofind_v2(me)
    assert bool(sections) is attached and afr.active() is active and me._autofind_v2 is None
    if sections:
        assert sections[0]._controller is None and not sections[0].again.isVisibleTo(sections[0])


def test_dorcha_tuarim_autofind_line_and_region_label(monkeypatch):
    """도르카·투아림 영역 문구 위 '자동(v2)' 한 줄(QA 1a42a58) — v2 꺼짐이면 숨김·문구 그대로."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.dorcha_tab import DorchaTab
    from mabinogi_addon.ui.region_section import refresh_autofind
    from mabinogi_addon.ui.tuarim_tab import TuarimTab
    QApplication.instance() or QApplication([])
    watcher = SimpleNamespace(is_game_active=lambda: False, is_self_active=lambda: False)
    d, t = DorchaTab(watcher), TuarimTab(watcher)
    try:
        d.auto_line.set_autofind_key("dorcha")
        t.auto_line.set_autofind_key("tuarim")
        assert d.auto_line.isHidden() and t.auto_line.isHidden()  # v2 꺼짐
        assert d.region_label.text() == "영역 미지정"
        afr.activate(True)
        afr.set_use_values({k: True for k in afr.USE_KEYS})
        afr.set_region("dorcha", {"x": 1180, "y": 96, "w": 120, "h": 30})
        refresh_autofind()
        d._update_region_label()
        t._update_region_label()
        assert not d.auto_line.isHidden() and "찾은 자리로 읽어요" in d.auto_line.text()
        assert d.region_label.text().startswith("찾은 자리  1180, 96")
        assert "찾는 중이에요" in t.auto_line.text() and t.region_label.text() == "자동(v2) 자리 찾는 중"
        afr.user_set("tuarim")
        refresh_autofind()
        assert "직접 지정한 영역으로 읽어요" in t.auto_line.text()
    finally:
        d.shutdown()
        t.shutdown()
