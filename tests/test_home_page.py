"""홈 화면(탐색 구조 명세 12절, 0.28.0): 진입·나가기, 설정 필요 상자, 스위치 동기화, 판독 값 없는 상태."""
import re

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from mabinogi_addon import config, setup_state
from mabinogi_addon.ui.home_page import COMBAT_ROWS, HomePage
from test_navigation import window  # noqa: F401  (픽스처)

BOX = {"x": 10, "y": 10, "w": 100, "h": 40}


def _pump(app, times=4):
    for _ in range(times):
        app.processEvents()


def _refresh(w):
    w.home_page.update_state(w._home_state())


def _all_regions():
    raw = config._read_local_config()
    raw["buffTracker"] = {"captureRegion": dict(BOX)}
    raw["debuffTracker"] = {"captureRegion": dict(BOX)}
    raw["bossPattern"] = {"box": dict(BOX)}
    raw["haloTimer"] = {"box": dict(BOX)}
    raw["statBars"] = {"box": dict(BOX)}
    raw["skillbar"] = {"anchor": {"x": 1, "y": 2}}
    raw["memoTracker"] = {"captureRegion": dict(BOX)}
    config._write_local_config(raw)


def test_home_button_covers_window_and_menu_returns_to_last_tab(window):
    w, app = window
    w._tabs.setCurrentWidget(w._party_scroll)
    w._home_btn.click()
    _pump(app)
    assert w.home_visible()
    assert w.home_page.geometry() == w.centralWidget().rect()  # 상태 줄·탭까지 덮는다
    w.home_page.menu_btn.click()
    _pump(app)
    assert not w.home_visible() and w._tabs.currentWidget() is w._party_scroll


def test_needs_box_lists_only_selected_features_without_region(window):
    w, app = window
    _all_regions()
    setup_state.save_selection("buff", True)
    w._show_home()
    _pump(app)
    state = w._home_state()
    assert state["needs"] == [] and w.home_page.warn_box.isHidden()  # 0개면 상자 자체를 숨긴다
    assert "설정 필요" not in w.home_page.summary.text()
    raw = config._read_local_config()
    raw.pop("haloTimer")
    raw.pop("skillbar")
    config._write_local_config(raw)
    setup_state.save_selection("skillbar", True)
    _refresh(w)  # 0.7초 상태 타이머의 홈 갱신(캡처 재시도 없이)
    _pump(app)
    assert w._home_state()["needs"] == [("skillbar", "단축바")]  # 헤일로는 고르지 않아 줄만 노랑
    assert not w.home_page.warn_box.isHidden()
    assert w.home_page.warn_title.text() == "설정이 필요한 기능 1개"
    assert w.home_page.summary.text().endswith(" · 1개 설정 필요")
    assert w._home_state()["rows"]["halo"] == ("영역 지정 필요", "warn")


def test_home_rows_show_no_read_values(window):
    w, app = window
    _all_regions()
    w._show_home()
    for text, *_ in w._home_state()["rows"].values():
        assert not re.search(r"\d", text)  # 판독 값(개수·%·시간)을 홈에 노출하지 않는다(명세 12.3)


def test_combat_switch_and_header_pause_stay_in_sync(window):
    w, app = window
    w._show_home()
    w.home_page.combat_switch.click()
    assert w._paused
    _refresh(w)  # 0.7초 상태 타이머의 홈 갱신(캡처 재시도 없이)
    assert w.home_page.title.text() == "전투 보조 일시정지"
    w._combat_status.click()  # 상단 '● 전투 보조'로 다시 켜면 홈 스위치도 따라온다
    _refresh(w)  # 0.7초 상태 타이머의 홈 갱신(캡처 재시도 없이)
    assert not w._paused and w.home_page.combat_switch.isChecked()


def test_switches_are_the_same_settings_as_each_screen(window):
    w, app = window
    w._show_home()
    rows = w.home_page.rows
    for key, tab in (("dorcha", w.dorcha_tab), ("tuarim", w.tuarim_tab), ("custom", w.custom_overlay_tab)):
        before = tab.enable.isChecked()
        rows[key].switch.click()
        assert tab.enable.isChecked() is (not before)
        tab.enable.setChecked(before)  # 화면 쪽에서 바꾸면 홈 스위치가 따라온다
        _refresh(w)  # 0.7초 상태 타이머의 홈 갱신(캡처 재시도 없이)
        assert rows[key].switch.isChecked() is before
    stat = w.stat_bars_tab
    stat._show_checks["mp"].setChecked(False)
    rows["stat_bars"].switch.click()  # 끄기: 모든 바 표시 끔
    assert not stat.any_shown()
    rows["stat_bars"].switch.click()  # 켜기: 꺼 두었던 마나는 그대로
    assert [sid for sid, chk in stat._show_checks.items() if chk.isChecked()] == ["hp", "sta"]


def test_optimization_switch_is_auto_apply_and_restore(window, monkeypatch):
    w, app = window
    tools = w.optimization_tools
    restores = []
    tcp = tools.panel.tcp.isChecked()
    monkeypatch.setattr(tools, "_auto_start", lambda: False)
    monkeypatch.setattr(tools, "_toggle_optimization", lambda *a: restores.append(True))
    tools.set_home_enabled(True)
    assert tools.panel.auto.isChecked()
    monkeypatch.setattr(tools, "_optimization_on", lambda: True)
    tools.set_home_enabled(False)
    assert not tools.panel.auto.isChecked() and restores == [True]  # 끄면 자동 적용 끄기 + 지금 적용분 원복
    assert tools.panel.tcp.isChecked() is tcp  # 패스트핑(네트워크)은 홈 스위치로 바꾸지 않는다


def test_row_and_region_buttons_open_the_screen(window):
    w, app = window
    w._show_home()
    w.home_page.rows["halo"].clicked.emit()
    _pump(app)
    assert not w.home_visible()
    assert w._tracker_tabs.currentWidget() is w._combat_pages["boss"] and w.boss_tab.pattern_tabs.currentIndex() == 1
    w._show_home()
    w.home_page.open_feature.emit("keywords")
    assert not w.home_visible() and w._tabs.currentWidget() is w._party_scroll
    w._show_home()
    w.home_page.open_region.emit("stat_bars")
    assert not w.home_visible() and w._tracker_tabs.currentWidget() is w._combat_pages["stat_bars"]
    w._show_home()
    w.home_page.combat_link.click()
    assert not w.home_visible() and w._tabs.currentWidget() is w._tracker_tabs


def test_creator_stays_on_home_and_window_height_follows_dialogue(window):
    w, app = window
    dialogue = w.creator_dialogue
    w.settings_tab.dialogue_enabled.setChecked(True)
    w._show_home()
    _pump(app)
    assert w.height() == 864 and dialogue.footer.isVisible()
    footer = dialogue.footer.geometry()
    assert footer.bottom() == w.centralWidget().rect().bottom() and footer.right() == w.centralWidget().rect().right()
    face = dialogue.face
    assert face.visibleRegion().contains(face.rect())  # 홈 위에 떠서 가려지지 않는다(잡담 말풍선 조건)
    w.settings_tab.dialogue_enabled.setChecked(False)
    _pump(app)
    assert w.height() == 800 and not dialogue.footer.isVisible()
    w.settings_tab.dialogue_enabled.setChecked(True)


def test_app_starts_on_home_unless_guide_comes_first(window, monkeypatch):
    from mabinogi_addon.ui.main_window import MainWindow
    w, app = window
    config.save_general_flag("skipSetup", True)
    second = MainWindow()
    try:
        assert second.home_visible()
    finally:
        second._force_quit = True
        second.close()
    config.save_general_flag("skipSetup", False)
    third = MainWindow()
    try:
        assert not third.home_visible() and third._pages.currentWidget() is third.setup_guide
    finally:
        third._force_quit = True
        third.close()


def test_rows_layout_and_painted_switch_only_where_settings_exist():
    page = HomePage()
    with_switch = {key for key, row in page.rows.items() if row.switch is not None}
    assert with_switch == {"stat_bars", "dorcha", "tuarim", "custom", "opt", "fps", "blackbox"}
    assert [key for key, *_ in COMBAT_ROWS] == ["buff", "debuff", "boss", "halo", "stat_bars", "dorcha",
                                                "tuarim", "custom", "skillbar", "memo"]
    page.resize(790, 800)
    page.update_state({"needs": [("halo", "1분 헤일로"), ("skillbar", "단축바")], "title": "running", "working": 7})
    page.show()
    QTest.qWait(1)
    assert page.scroll.verticalScrollBar().maximum() == 0  # 기준 창 790×800에서 스크롤 없음
    # 0.28.0 QA(#153): 글꼴(Noto Sans CJK KR·맑은 고딕)에 따라 줄이 높아져도 넘치지 않게 최소 15px 여유
    assert page.scroll.widget().sizeHint().height() <= 800 - 15
    clicks = []
    page.open_feature.connect(clicks.append)
    QTest.mouseClick(page.rows["memo"], Qt.MouseButton.LeftButton)
    assert clicks == ["memo"]
    page.close()


def test_moving_to_another_screen_from_code_closes_home(window):
    w, app = window
    w._show_home()
    w._focus_party_tab()  # 파티 알림 토스트 클릭
    assert not w.home_visible() and w._tabs.currentWidget() is w._party_scroll
    w._show_home()
    w._open_guide()  # 설정 > 안내 다시 보기 등
    assert not w.home_visible() and w._pages.currentWidget() is w.setup_guide


def test_many_needs_scroll_with_dark_scrollbar():
    page = HomePage()
    page.resize(790, 800)
    page.update_state({"needs": [(str(i), "기능") for i in range(10)], "title": "running"})
    page.show()
    QTest.qWait(1)
    bar = page.scroll.verticalScrollBar()
    assert bar.maximum() > 0  # 아주 많을 때만 스크롤
    assert "QScrollBar::handle:vertical" in page.styleSheet()  # 밝은 기본 스크롤바 대신 어두운 모양
    page.close()
