"""Navigation changes must preserve editors, configuration and lifecycle."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QApplication, QTabWidget
from shiboken6 import isValid

from mabinogi_addon import config
from mabinogi_addon.ui.main_window import MainWindow


KEYS = ('buff', 'debuff', 'tuarim', 'boss', 'stat_bars', 'dorcha', 'custom', 'skillbar', 'memo')
LABELS = ['버프', '디버프', '보스 패턴 알림', '체력바', '도르카·투아림', '커스텀 오버레이', '단축바', '메모']


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, 'quit', lambda: None)
    monkeypatch.setattr(config, 'load_discord_user', lambda: {'id': 'test', 'name': '테스트'})
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen, 'availableGeometry', lambda self: QRect(0,0,1600,1100))
    monkeypatch.setattr(screen, 'geometry', lambda self: QRect(0,0,1600,1100))
    window = MainWindow()
    window._post_show_done = True
    window.show()
    window._leave_setup()
    window._booting = False
    for timer in window.findChildren(QTimer):
        timer.stop()
    app.processEvents()
    yield window, app
    window._force_quit = True
    window.close()
    app.processEvents()


def test_structure_and_default_editor_space(window):
    w, app = window
    # 0.16.0: 로그인 사용자(픽스처)는 블랙박스 탭, 0.22.0(13.15): 최적화 탭도 공개. 0.22.1: 순서 최적화 · 블랙박스(사용자 결정)
    assert [w._tabs.tabText(i) for i in range(w._tabs.count())] == ['전투 보조','파티 모집','편의기능','최적화','블랙박스','설정']
    assert [w._tracker_tabs.tabText(i) for i in range(w._tracker_tabs.count())] == LABELS
    # 0.37.0 명세 변경(사용자 결정 안 A): 편의기능 2단 한 줄(탭 이름 = 화면 제목), 마우스 커서는 최적화 2단 세 번째
    assert [w._convenience_tabs.tabText(i) for i in range(w._convenience_tabs.count())] == [
        '분배 계산기','구슬 분배 계산기','환전비율 계산기','던전 입장 계산기','그림대화 만들기']
    panel_tabs = w.optimization_tools.panel.tabs
    # 0.42.0 사용자 결정: 서버별 채널 상태(옛 하프 채널 연결) 모두에게 공개 → 최적화 2단 네 번째
    assert [panel_tabs.tabText(i) for i in range(panel_tabs.count())] == ['최적화','FPS 측정','마우스 커서','서버별 채널 상태']
    bar = w._tracker_tabs.tabBar()
    assert all(bar.rect().contains(bar.tabRect(i)) for i in range(8))
    assert w._combat_pages['tuarim'] is w._combat_pages['dorcha']
    for key, conf in (('buff','buffTracker'),('debuff','debuffTracker')):
        # 영역 지정 후(평소) 기본 크기에서 스크롤 없음. 지정 전 큰 '영역 지정' 상자는 위 전체 폭이라(명세 17절) 한 번 하는 설정 동안 아래로 밀 수 있다.
        config.save_capture_region(10, 20, 300, 80, conf)
        w._open_setup_feature(key)
        panel = getattr(w,key+'_tab')
        panel._update_region_hint()
        panel.region_section._set_open(False)  # 방금 지정해 펼친 묶음은 탭을 다시 열면 접힘
        for _ in range(4):
            app.processEvents()
        assert not panel._columns.stacked
        assert w.width() == 790
        assert w._combat_pages[key].horizontalScrollBar().maximum() == 0
        assert w._combat_pages[key].verticalScrollBar().maximum() == 0


@pytest.mark.parametrize('key', KEYS)
def test_feature_entry_selects_exact_page_without_enabling_it(window, key):
    w, app = window
    before = deepcopy(config._read_local_config())
    assert w._open_setup_feature(key)
    app.processEvents()
    assert w._tabs.currentWidget() is w._tracker_tabs
    assert w._tracker_tabs.currentWidget() is w._combat_pages[key]
    w._tabs.setCurrentIndex(2)
    w._tabs.setCurrentIndex(0)
    assert w._tracker_tabs.currentWidget() is w._combat_pages[key]
    assert config._read_local_config() == before


def test_invalid_or_late_entry_preserves_selection(window):
    w, _ = window
    w._open_setup_feature('memo')
    before = w._tracker_tabs.currentWidget()
    assert not w._open_setup_feature('missing-feature')
    assert w._tracker_tabs.currentWidget() is before
    w._config_pending_restart = True
    assert not w._open_setup_feature('buff')
    assert w._tracker_tabs.currentWidget() is before
    w._config_pending_restart = False


def test_selection_drives_only_the_visible_editing_feature(window, monkeypatch):
    w, app = window
    watcher = type('Watcher', (), {'is_game_active': lambda self: False, 'is_self_active': lambda self: True})()
    tabs = {'dorcha':w.dorcha_tab, 'stat_bars':w.stat_bars_tab, 'skillbar':w.skillbar_tab}
    for tab in tabs.values():
        monkeypatch.setattr(tab, '_watcher', watcher)
    for key in KEYS:
        w._open_setup_feature(key)
        app.processEvents()
        for candidate, tab in tabs.items():
            assert tab._active() == (candidate == key or (candidate == 'dorcha' and key == 'tuarim'))
    w._tabs.setCurrentIndex(2)
    assert not any(tab._active() for tab in tabs.values())


@pytest.mark.parametrize('from_guide', [False, True])
@pytest.mark.parametrize('finish', ['complete', 'skip'])
def test_tour_both_directions_and_approved_return(window, from_guide, finish):
    w, app = window
    w._open_setup_feature('dorcha')
    w._convenience_tabs.setCurrentIndex(1)  # 0.35.0 편의기능 B안(마우스 커서 명세 1절): 2단 계산기·그림대화 — 예전 3번째 계산기 탭 대신 그림대화(1)
    w._tabs.setCurrentIndex(2)
    before = deepcopy(config._read_local_config())
    paused = w._paused
    w._run_tour(from_guide=from_guide)
    tour = w._tour
    assert len(tour._steps) == 8  # 둘러보기 8단계(first-use-v3 3절)
    from mabinogi_addon.ui.first_use import TOUR
    assert [step.title for step in tour._steps] == [title for title, _ in TOUR]  # 첫 사용 3단계 목록과 같은 순서·같은 말
    assert tour._section_title == ''
    home, tracker, settings = 'home', w._tracker_tabs, w._settings_scroll
    expected = [home, home, tracker, tracker, tracker, tracker, tracker, settings]
    for index in list(range(8)) + list(reversed(range(8))) + list(range(8)):
        tour._i = index
        tour._show_step()
        app.processEvents()
        assert tour._step_lbl.text() == f'{index + 1} / {len(tour._steps)}'
        if expected[index] == 'home':
            assert w.home_visible()
        else:
            assert not w.home_visible() and w._tabs.currentWidget() is expected[index]
        if tour._steps[index].target is not None:
            rect = tour._target_rect()
            assert rect is not None and not rect.isEmpty(), index
            assert tour.rect().contains(rect)
            assert not rect.intersects(tour._card.geometry())
        assert not w.creator_dialogue._eligible()
    assert w._tracker_tabs.currentWidget() is not None
    if finish == 'complete':
        tour._i = 7
        tour._go_next()
    else:
        tour._skip.click()
    app.processEvents()
    assert w._tour is None and not tour.isVisible()
    if from_guide:
        assert w._tabs.currentWidget() is w._tracker_tabs
        assert w._tracker_tabs.currentWidget() is w._combat_pages['buff']
    else:
        assert w._tabs.currentWidget() is w._convenience_tabs
        assert w._convenience_tabs.currentIndex() == 1  # 0.35.0 편의기능 B안(마우스 커서 명세 1절): 2단 계산기·그림대화 — 예전 3번째 계산기 탭 대신 그림대화(1)
        assert w._tracker_tabs.currentWidget() is w._combat_pages['dorcha']
    after = config._read_local_config()
    before.setdefault('general', {})['tourShown'] = True
    assert after == before and w._paused == paused


def test_hide_dismisses_tour_without_marking_done_or_reopening(window):
    w, app = window
    before = deepcopy(config._read_local_config())
    w._run_tour()
    tour = w._tour
    w.hide()
    app.processEvents()
    assert not w.isVisible()
    assert not isValid(tour) or not tour.isVisible()
    assert w._tour is None
    assert config._read_local_config() == before
    w.show()
    assert w._tour is None


def test_logged_out_dorcha_and_tour_settings_keep_access_rules(window, monkeypatch):
    w, app = window
    monkeypatch.setattr(config,'load_discord_user',lambda:None)
    w.dorcha_tab._apply_gate()
    w._open_setup_feature('dorcha')
    assert w.dorcha_tab.enable.isEnabled()
    assert w.dorcha_tab.auto_find_btn.isEnabled()  # 일반 자동 찾기는 로그아웃 상태에서도 제공
    w._run_tour(from_guide=True)
    assert getattr(w,'_tour',None) is not None
    w._run_tour()
    tour = w._tour
    tour._i = 7
    tour._show_step()
    app.processEvents()
    assert tour._steps[7].target is w.settings_tab.setup_btn
    assert tour._target_rect() is not None


def test_repeated_navigation_does_not_create_timers_or_pages(window):
    w, app = window
    before = deepcopy(config._read_local_config())
    timers = set(w.findChildren(QTimer))
    pages = set(w.findChildren(QTabWidget))
    for _ in range(15):
        for key in KEYS:
            w._open_setup_feature(key)
            app.processEvents()
        w._tabs.setCurrentIndex(1)
        w._tabs.setCurrentIndex(2)
    assert set(w.findChildren(QTimer)) == timers
    assert set(w.findChildren(QTabWidget)) == pages
    assert config._read_local_config() == before


def test_embedded_dorcha_preview_clears_background_but_game_overlay_stays_transparent(window):
    from mabinogi_addon.ui.dorcha_overlay import DorchaOverlay
    w, _ = window
    preview = w.dorcha_tab.preview
    assert not preview.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert not preview.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
    assert preview.autoFillBackground()
    overlay = DorchaOverlay()
    try:
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert not overlay.autoFillBackground()
        assert overlay.locked
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    finally:
        overlay.close()
        overlay.deleteLater()
