"""자동 찾기 모든 사용자 공개(docs/first-use-v3-spec.md 4.1·6절) — v1 대비책·직접 지정 고정·비상 끄기."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from mabinogi_addon import autofind_regions, config

SAVED = {"x": 1, "y": 2, "w": 30, "h": 40}
FOUND = {"x": 100, "y": 200, "w": 30, "h": 300}


@pytest.fixture(autouse=True)
def provider():
    autofind_regions.reset_for_tests()
    autofind_regions.activate(True)
    autofind_regions.set_use_values({k: True for k in autofind_regions.USE_KEYS})
    yield
    autofind_regions.reset_for_tests()


def test_order_found_then_saved_v1_then_none():
    assert autofind_regions.region_for("buff", SAVED) == SAVED and autofind_regions.source("buff") == "v1"
    assert autofind_regions.region_for("tuarim", None) is None and autofind_regions.source("tuarim") is None
    autofind_regions.set_region("buff", FOUND)  # v2가 찾음(확정·시험 중 포함) → 자동 자리로 바꿈
    assert autofind_regions.region_for("buff", SAVED) == FOUND and autofind_regions.source("buff") == "auto"
    autofind_regions.set_region("buff", None)  # 다시 못 찾음 → 저장 영역
    assert autofind_regions.region_for("buff", SAVED) == SAVED


def test_reads_from_v1_do_not_feed_engine_item_state():
    calls = []
    autofind_regions.set_reporter(lambda *a: calls.append(a))
    autofind_regions.region_for("buff", SAVED)
    autofind_regions.report("buff", True)
    autofind_regions.set_region("buff", FOUND)
    autofind_regions.region_for("buff", SAVED)
    autofind_regions.report("buff", True)
    assert calls == [("buff", True, None, False), ("buff", True, None, True)]


def test_direct_designation_is_fixed_and_persists():
    saved = []
    autofind_regions.set_fixed_saver(saved.append)
    autofind_regions.set_region("buff", FOUND)
    autofind_regions.user_set("buff")
    assert saved[-1] == ["buff"] and autofind_regions.is_fixed("buff")
    autofind_regions.set_region("buff", {"x": 5, "y": 5, "w": 5, "h": 5})  # 자동이 덮지 않음
    assert autofind_regions.region_for("buff", SAVED) == SAVED and autofind_regions.source("buff") == "user"
    # 다음 실행: 고정 목록을 읽어 시작
    autofind_regions.activate(True, saved[-1])
    assert autofind_regions.is_fixed("buff") and autofind_regions.region_for("buff", SAVED) == SAVED
    events = []
    autofind_regions.subscribe(lambda key, user: events.append((key, user)))
    autofind_regions.auto_return("buff")
    assert saved[-1] == [] and not autofind_regions.is_fixed("buff") and events == [("buff", False)]


def test_existing_saved_regions_are_not_fixed():
    """기존 사용자의 직접 지정 영역은 고정이 아니다(자동으로 바꿈 — D2·D3)."""
    autofind_regions.region_for("buff", SAVED)
    assert not autofind_regions.is_fixed("buff")
    autofind_regions.set_region("buff", FOUND)
    assert autofind_regions.region_for("buff", SAVED) == FOUND


def test_shared_boss_fix_drives_debuff_row():
    """보스바 고정 하나가 보스 패턴·디버프 보스 확인·보스바 오버레이 모두에 적용, 디버프 줄은 고정한 보스바에서 계산."""
    boss = {"x": 100, "y": 500, "w": 600, "h": 20}
    autofind_regions.set_region("boss", {"x": 1, "y": 1, "w": 2, "h": 2})
    autofind_regions.set_region("debuff", {"x": 1, "y": 0, "w": 2, "h": 3})
    autofind_regions.user_set("boss")
    assert autofind_regions.region_for("boss", boss) == boss
    autofind_regions.set_region("debuff", None)  # 컨트롤러는 고정된 보스바의 디버프 띠를 내지 않음
    assert autofind_regions.region_for("debuff", None) == {"x": 100, "y": 472, "w": 600, "h": 48}
    assert autofind_regions.source("debuff") == "user"
    autofind_regions.user_set("debuff")  # 디버프 줄을 따로 고정하면 그 영역
    own = {"x": 90, "y": 400, "w": 700, "h": 60}
    assert autofind_regions.region_for("debuff", own) == own


@pytest.mark.autofind_default
def test_emergency_disabled_value(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"autofind": {"disabled": True}}), encoding="utf-8")
    assert config.load_autofind_disabled(path)
    path.write_text("{}", encoding="utf-8")
    assert not config.load_autofind_disabled(path)
    config.save_autofind_fixed(["buff", "boss", "buff"], path)
    assert config.load_autofind_fixed(path) == ["boss", "buff"]
    autofind_regions.activate(False)
    assert autofind_regions.region_for("buff", SAVED) == SAVED and not autofind_regions.is_fixed("buff")


def test_engine_releases_fixed_item_and_searches_now():
    from mabinogi_addon import autofind_v2 as v2
    e = v2.Engine()
    e.reset(0.0)
    e.user_override("buff")
    e.user_override("boss")
    assert e.region("buff") is None
    e.user_release("buff", 5.0)
    e.user_release("boss", 5.0)
    assert e.items["buff"].status == v2.MISSING and e.items["buff"].next_try == 5.0 and not e.items["buff"].user
    assert e.items["boss"].status == v2.WAITING


@pytest.mark.autofind_default
def test_main_window_default_on_for_everyone(monkeypatch):
    """앱 기본: 비제작자도 자동 찾기 켜짐, 진단 구역 없음. 저장 영역은 v1 대비책으로, 버프 직접 지정은 고정 + 사용 켬(다음 실행에도)."""
    from PySide6.QtCore import QRect, QTimer
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "테스트"})
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen, "availableGeometry", lambda self: QRect(0, 0, 1600, 1100))
    from types import SimpleNamespace

    from mabinogi_addon.ui import main_window
    monkeypatch.setattr(main_window, "create_live_source", lambda *a, **k: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(main_window.MainWindow, "_start_debuff_tracking", lambda self: None)
    monkeypatch.setattr(main_window.MainWindow, "_start_buff_tracking", lambda self: None)
    raw = config._read_local_config()
    raw["debuffTracker"] = {"captureRegion": dict(SAVED)}
    config._write_local_config(raw)
    autofind_regions.reset_for_tests()
    w = MainWindow()
    try:
        for timer in w.findChildren(QTimer):
            timer.stop()
        assert autofind_regions.active() and w._autofind_v2 is not None
        assert getattr(w.settings_tab, "autofind_v2_section", None) is None and w.settings_tab.autofind_v2_toggle.isHidden()
        assert autofind_regions.use_on("debuff") and not autofind_regions.use_on("buff")  # 처음 값 = 영역 있으면 켬
        assert autofind_regions.region_for("debuff", SAVED) == SAVED and autofind_regions.source("debuff") == "v1"
        w.buff_tab._on_region_selected(5, 6, 70, 80)
        assert autofind_regions.is_fixed("buff") and autofind_regions.use_on("buff")
        saved = config._read_local_config()["autofindV2"]
        assert saved["fixed"] == ["buff"] and saved["use"]["buff"] is True
        assert w._autofind_v2.engine.items["buff"].user
        state = w._home_state()  # 홈: 설정 필요 상자 대신 위치 요약 + 줄 상태(first-use-v3 4.1)
        assert state["needs"] == [] and "locations" in state
        assert state["rows"]["debuff"][0] == "켜짐 · 저장된 영역 사용" and state["rows"]["buff"][1] != "warn"
        assert state["rows"]["halo"][0].startswith("꺼짐 · ")
        gen = w._autofind_v2.engine.generation
        w._home_refind()  # 위치 다시 찾기 = 처음 찾기 한 번 더
        assert w._autofind_v2.engine.generation == gen + 1
    finally:
        w._force_quit = True
        w.close()
        app.processEvents()


def test_inquiry_collects_region_in_use(monkeypatch):
    """문의 자료 모으기: 자동으로 찾은 자리 → 없으면 저장 영역(v1). 사용 값이 꺼져 있어도 지금 자리."""
    from mabinogi_addon import inquiry_session as inq
    monkeypatch.setattr(config, "load_capture_region", lambda name: dict(SAVED))
    assert inq.region_of("buff") == SAVED
    autofind_regions.set_region("buff", FOUND)
    autofind_regions.set_use("buff", False)
    assert inq.region_of("buff") == FOUND
