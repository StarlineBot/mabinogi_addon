"""배포 기본값(자동 찾기 켜짐)으로 띄운 창 — 새 설치·업데이트 직후 예전 설정(QA 0429c66 1·5).

conftest는 예전 창 테스트를 비상 값(자동 찾기 꺼짐)으로 돌린다. 여기는 `autofind_default`로 실제 배포 동작을 본다.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication

from mabinogi_addon import autofind_regions, config

pytestmark = pytest.mark.autofind_default

BOX = {"x": 100, "y": 900, "w": 300, "h": 60}
FOUND = {"x": 120, "y": 910, "w": 300, "h": 60}


@pytest.fixture
def make_window(monkeypatch):
    from mabinogi_addon.ui import main_window
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "테스트"})
    monkeypatch.setattr(main_window, "create_live_source", lambda *a, **k: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(main_window.MainWindow, "_start_buff_tracking", lambda self: None)
    monkeypatch.setattr(main_window.MainWindow, "_start_debuff_tracking", lambda self: None)
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen, "availableGeometry", lambda self: QRect(0, 0, 1600, 1100))
    made = []

    def make(raw=None):
        if raw is not None:  # 업데이트 직후: 예전 설정 파일이 있다(자동 찾기 사용 값은 아직 없음)
            config._write_local_config(raw)
        autofind_regions.reset_for_tests()
        w = main_window.MainWindow()
        for timer in w.findChildren(QTimer):
            timer.stop()
        made.append(w)
        return w
    yield make
    for w in made:
        w._force_quit = True
        w.close()
    app.processEvents()


def _stat_bars_tick(w, monkeypatch):
    grabs = []
    tab = w.stat_bars_tab
    monkeypatch.setattr(tab, "_grab_rect", lambda *a: grabs.append(a))
    monkeypatch.setattr(tab._watcher, "is_game_active", lambda: True)
    tab._tick()
    return grabs, [ov for ov in tab._overlays.values() if ov.isVisible()]


def test_new_install_stat_bars_off_even_when_found(make_window, monkeypatch):
    """새 설치: 체력바 사용 값 꺼짐(명세 2.2 '기본 모두 꺼짐') — 자리를 찾아도 읽기·오버레이 없음."""
    w = make_window()
    assert not autofind_regions.use_on("stat_bars")
    w.first_use.refresh()
    assert not w.first_use.rows["stat_bars"].switch.isChecked()
    autofind_regions.set_region("stat_bars", FOUND)
    assert w.stat_bars_tab._region is None
    grabs, shown = _stat_bars_tick(w, monkeypatch)
    assert grabs == [] and shown == []
    assert w._home_state()["rows"]["stat_bars"][2] is False


def test_update_without_stat_bar_region_stays_off(make_window, monkeypatch):
    """예전 설정(체력바 영역 없음 — 안 쓰던 사람): 업데이트 뒤에도 꺼짐, 자리를 찾아도 오버레이 없음."""
    w = make_window({"general": {"gameExe": "Client.exe"}, "statBars": {"enabled": False}})
    assert not autofind_regions.use_on("stat_bars") and w._pages.currentWidget() is not w.first_use
    autofind_regions.set_region("stat_bars", FOUND)
    grabs, shown = _stat_bars_tick(w, monkeypatch)
    assert grabs == [] and shown == []


def test_update_with_stat_bar_region_stays_on(make_window, monkeypatch):
    """예전 설정(체력바 영역 있음 + 표시 바 켬): 업데이트 뒤 켜짐 — 못 찾는 동안 저장 영역(v1)으로 읽음."""
    w = make_window({"statBars": {"box": dict(BOX), "bars": {"hp": {"show": True}}}})
    assert autofind_regions.use_on("stat_bars")
    assert w.stat_bars_tab._region == BOX and autofind_regions.source("stat_bars") == "v1"
    grabs, _ = _stat_bars_tick(w, monkeypatch)
    assert len(grabs) == 1
    autofind_regions.set_region("stat_bars", FOUND)  # 자동으로 찾으면 그 자리로
    assert w.stat_bars_tab._region == FOUND


def test_update_with_stat_bar_region_but_all_bars_hidden_stays_off(make_window):
    raw = {"statBars": {"box": dict(BOX), "bars": {s: {"show": False} for s in ("hp", "mp", "sta")}}}
    make_window(raw)
    assert not autofind_regions.use_on("stat_bars")


def test_home_stat_bars_switch_is_the_use_value(make_window):
    """홈·첫 사용 스위치 = 체력바 사용 값(바별 표시 선택은 그대로)."""
    w = make_window({"statBars": {"box": dict(BOX), "bars": {"hp": {"show": True}, "mp": {"show": False}}}})
    w._home_switch("stat_bars", False)
    assert not autofind_regions.use_on("stat_bars") and w.stat_bars_tab._region is None
    assert config._read_local_config()["autofindV2"]["use"]["stat_bars"] is False
    assert w.stat_bars_tab._show_checks["hp"].isChecked() and not w.stat_bars_tab._show_checks["mp"].isChecked()
    w._home_switch("stat_bars", True)
    assert autofind_regions.use_on("stat_bars") and w.stat_bars_tab._region == BOX


@pytest.mark.parametrize("key,section,field", [("buff", "buffTracker", "captureRegion"),
                                               ("debuff", "debuffTracker", "captureRegion")])
def test_update_keeps_working_features_on_with_saved_region(make_window, key, section, field):
    """업데이트 직후: 저장 영역이 있던 기능은 켜진 채로, 자동으로 못 찾는 동안 저장 영역(v1)으로 동작(D2·D3)."""
    w = make_window({section: {field: dict(BOX)}})
    assert autofind_regions.use_on(key)
    assert autofind_regions.region_for(key, dict(BOX)) == BOX and autofind_regions.source(key) == "v1"
    state = w._home_state()
    home_key = key
    assert state["rows"][home_key][2] is True and state["needs"] == []


def test_update_with_boss_region_shares_one_spot(make_window):
    w = make_window({"bossPattern": {"box": dict(BOX)}})
    assert autofind_regions.use_on("boss") and w.boss_tab._region == BOX
    autofind_regions.set_region("boss", FOUND)
    assert w.boss_tab._region == FOUND


def test_update_without_any_region_starts_on_home_with_everything_off(make_window):
    w = make_window({"general": {"gameExe": "Client.exe"}})
    assert all(not autofind_regions.use_on(k) for k in autofind_regions.USE_KEYS)
    assert w._pages.currentWidget() is not w.first_use  # 기존 사용자에게 첫 사용 안내를 띄우지 않음
    rows = w._home_state()["rows"]
    assert all(rows[k][0].startswith("꺼짐 · ") for k in ("buff", "debuff", "boss", "halo", "skillbar", "stat_bars"))


def test_skillbar_saved_anchor_used_until_found(make_window):
    w = make_window({"skillbar": {"anchor": {"x": 30, "y": 1300}}})
    assert autofind_regions.use_on("skillbar") and w.skillbar_tab._anchor == {"x": 30, "y": 1300}
    autofind_regions.set_region("skillbar", {"x": 40, "y": 1310})
    assert w.skillbar_tab._anchor == {"x": 40, "y": 1310}


def test_new_user_region_boxes_use_v3_guidance(make_window):
    """영역 미지정 새 사용자: 기능 화면 '영역 지정' 상자 안내가 v3 톤('앱이 알아서 찾아요 · 틀리면 직접 지정하면 고정') — QA 0429c66 4."""
    w = make_window()
    tabs = {"buff": w.buff_tab, "debuff": w.debuff_tab, "boss": w.boss_tab, "halo": w.boss_tab.halo_capture,
            "stat_bars": w.stat_bars_tab, "skillbar": w.skillbar_tab, "resources": w.resource_tab}
    for name, tab in tabs.items():
        section = tab.region_section
        assert not section.registered, name
        guide = tab.region_guide.text()
        assert "앱이 알아서 찾아요" in guide and "고정돼요" in guide, (name, guide)
        assert "아직 지정 안 됨" not in section.unset_label.text(), name
    autofind_regions.activate(False)  # 비상 값(자동 찾기 꺼짐): 예전 안내 그대로
    w.buff_tab.region_section.refresh_autofind()
    assert w.buff_tab.region_guide.text().startswith("상태목록창을 맨 위")
