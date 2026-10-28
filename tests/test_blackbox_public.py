"""0.16.0 블랙박스 공개(디스코드 로그인 사용자)·기본 5분·단축키 변경."""
from types import SimpleNamespace as NS

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.blackbox import DEFAULT_RETENTION_US, MAX_RETENTION_MINUTES
from mabinogi_addon.blackbox_shortcut import ALT, CTRL, DEFAULT, SHIFT, WIN, check, hotkey_text

F10, PRINT = 0x79, 0x2C


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


# ---- 보관 시간 ----

def test_default_retention_is_five_minutes_and_saved_values_are_clamped(tmp_path):
    path = tmp_path / 'config.json'
    assert DEFAULT_RETENTION_US == 5 * 60 * 1_000_000 and MAX_RETENTION_MINUTES == 15
    assert 'retentionMinutes' not in config.load_blackbox_preferences(path)  # 저장값 없으면 기본 5분
    config._write_local_config({'blackbox': {'retentionMinutes': 30}}, path)  # 예전 자유 입력값
    assert config.load_blackbox_preferences(path)['retentionMinutes'] == 15
    config.save_blackbox_preference('retentionMinutes', 15, path)
    for bad in (0, 16, 30):
        with pytest.raises(ValueError):
            config.save_blackbox_preference('retentionMinutes', bad, path)
    assert config.load_blackbox_preferences(path)['retentionMinutes'] == 15


def test_tab_uses_spinbox_1_to_15_minutes(app):
    from mabinogi_addon.ui.blackbox_tab import BlackboxTab
    tab = BlackboxTab()
    try:
        assert (tab.retention.minimum(), tab.retention.maximum(), tab.retention.value()) == (1, 15, 5)
        assert tab.retention.suffix() == ' 분'
        tab.retention.setValue(99)
        assert tab.retention.value() == 15
    finally:
        tab.deleteLater()


# ---- 단축키 규칙·저장 ----

@pytest.mark.parametrize('modifiers, vk, state', [
    (CTRL | ALT, PRINT, 'ok'), (SHIFT, F10, 'ok'), (ALT, 0x41, 'ok'),
    (0, F10, 'invalid'),                 # 수식 키 없음
    (CTRL | WIN, F10, 'invalid'),        # Win 포함
    (WIN, F10, 'invalid'),
    (CTRL | ALT, None, 'incomplete'),    # 수식 키만
    (CTRL, 0xA2, 'incomplete'),          # 왼쪽 Ctrl 자체는 '나머지 키'가 아님
    (0, None, 'incomplete'),
])
def test_hotkey_rules(modifiers, vk, state):
    assert check(modifiers, vk)[0] == state


def test_hotkey_is_saved_loaded_and_invalid_saved_value_falls_back_to_default(tmp_path):
    path = tmp_path / 'config.json'
    config.save_blackbox_preference('hotkey', (CTRL | SHIFT, F10), path)
    assert config.load_blackbox_preferences(path)['hotkey'] == (CTRL | SHIFT, F10)
    assert config._read_local_config(path)['blackbox'] == {'hotkeyModifiers': CTRL | SHIFT, 'hotkeyVk': F10}
    for bad in ((0, F10), (WIN | CTRL, F10), (CTRL, None), (CTRL, 0x11)):
        with pytest.raises(ValueError):
            config.save_blackbox_preference('hotkey', bad, path)
    for modifiers, vk in ((0, F10), (WIN, F10), ('3', '44'), (CTRL, 0xA0)):
        config._write_local_config({'blackbox': {'hotkeyModifiers': modifiers, 'hotkeyVk': vk}}, path)
        assert 'hotkey' not in config.load_blackbox_preferences(path)  # 컨트롤러는 제품 기본값을 쓴다
    assert hotkey_text(*DEFAULT) == 'Ctrl+Alt+PrintScreen'


def test_change_dialog_judges_combinations_and_handles_release_only_printscreen(app):
    from mabinogi_addon.ui.blackbox_hotkey_dialog import ERROR_COLOR, OK_COLOR, HotkeyDialog
    dialog = HotkeyDialog(DEFAULT)
    try:
        assert dialog.field.text() == 'Ctrl+Alt+PrintScreen' and not dialog.save.isEnabled()
        dialog.feed(True, None, CTRL)
        dialog.feed(True, None, CTRL | ALT)
        assert dialog.field.text() == 'Ctrl+Alt+…' and dialog.state == 'incomplete' and not dialog.save.isEnabled()
        dialog.feed(True, F10, CTRL | ALT)
        assert dialog.field.text() == 'Ctrl+Alt+F10' and dialog.state == 'ok' and dialog.save.isEnabled()
        assert dialog.verdict.text() == '사용할 수 있는 조합이에요.' and OK_COLOR in dialog.verdict.styleSheet()
        dialog.feed(False, F10, ALT)  # Ctrl을 먼저 뗀 뒤 F10을 떼도 조합은 그대로
        assert dialog.field.text() == 'Ctrl+Alt+F10'
        dialog.feed(True, None, WIN)
        dialog.feed(True, F10, WIN)
        assert dialog.state == 'invalid' and not dialog.save.isEnabled() and ERROR_COLOR in dialog.verdict.styleSheet()
        dialog.feed(True, F10, 0)
        assert dialog.state == 'invalid' and not dialog.save.isEnabled()
        # Windows: PrintScreen은 누름 없이 뗌만 오는 경우가 있다
        dialog.feed(True, None, SHIFT)
        dialog.feed(False, PRINT, SHIFT)
        assert dialog.field.text() == 'Shift+PrintScreen' and dialog.save.isEnabled()
        dialog.save.click()
        assert dialog.result_hotkey == (SHIFT, PRINT)
    finally:
        dialog.deleteLater()


def test_change_dialog_reads_qt_key_events_default_and_escape(app):
    from PySide6.QtTest import QTest
    from mabinogi_addon.ui.blackbox_hotkey_dialog import HotkeyDialog
    dialog = HotkeyDialog((SHIFT, F10))
    try:
        dialog.show()
        QTest.keyPress(dialog, Qt.Key.Key_F9, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert dialog.field.text() == 'Ctrl+Shift+F9' and dialog.save.isEnabled()
        QTest.keyPress(dialog, Qt.Key.Key_Space, Qt.KeyboardModifier.AltModifier)
        assert dialog.field.text() == 'Alt+Space' and dialog.isVisible()  # Space가 버튼을 누르지 않음
        dialog.default.click()
        assert dialog.field.text() == 'Ctrl+Alt+PrintScreen' and dialog.save.isEnabled()
        QTest.keyPress(dialog, Qt.Key.Key_Escape)
        assert not dialog.isVisible() and dialog.result_hotkey is None
    finally:
        dialog.deleteLater()


def test_observer_swaps_chord_immediately_and_only_new_combination_fires():
    from collections import deque
    from threading import Event
    from mabinogi_addon.system.blackbox_hotkey import Chord, HotkeyObserver
    observer = HotkeyObserver.__new__(HotkeyObserver)
    observer.chord, observer.epoch, observer.chord_epoch = Chord(CTRL | ALT, PRINT), 0, 0
    observer.pending, observer.overflow, observer.error = deque(maxlen=2), None, None
    observer.stopping, observer.api = Event(), NS(foreground=lambda: 7, callback_error=None)

    def press(*keys):
        for vk in keys:
            observer._observe(vk, 0x100, 0)
        for vk in reversed(keys):
            observer._observe(vk, 0x101, 0)
        return observer.consume()

    assert press(0xA2, 0xA4, PRINT) is not None          # 기존 Ctrl+Alt+PrintScreen
    observer.set_chord(SHIFT, F10)
    assert press(0xA2, 0xA4, PRINT) is None               # 바꾼 뒤 예전 조합은 무시
    assert press(0xA0, F10) is not None                   # 새 Shift+F10만 반응


# ---- 컨트롤러: 즉시 적용·변경 창 동안 입력 무시 ----

def _controller(monkeypatch, tmp_path):
    from mabinogi_addon.ui import blackbox_controller as module
    from mabinogi_addon.ui.blackbox_tab import BlackboxTab
    path = tmp_path / 'config.json'
    real_save = config.save_blackbox_preference
    monkeypatch.setattr(config, 'save_blackbox_preference', lambda k, v, p=path: real_save(k, v, p))
    monkeypatch.setattr(module.feature_access, 'blackbox_available', lambda: True)
    c = module.BlackboxController.__new__(module.BlackboxController)
    QObjectInit = module.QObject.__init__
    QObjectInit(c)
    c.window, c.panel, c._hotkey, c._capturing_hotkey, c._logged_error = NS(_closing=False), BlackboxTab(), DEFAULT, False, None
    swapped = []
    c.events = NS(set_hotkey=lambda m, vk: swapped.append((m, vk)), observer=NS(discard=lambda: swapped.append('discard')))
    return c, swapped, path


def test_apply_hotkey_saves_and_swaps_without_restart(monkeypatch, tmp_path, app):
    c, swapped, path = _controller(monkeypatch, tmp_path)
    c._apply_hotkey((CTRL | SHIFT, F10))
    assert swapped == [(CTRL | SHIFT, F10)] and c._hotkey == (CTRL | SHIFT, F10)
    assert c.panel.hotkey.text() == 'Ctrl+Shift+F10'
    assert config.load_blackbox_preferences(path)['hotkey'] == (CTRL | SHIFT, F10)
    c.panel.deleteLater()


def test_old_hotkey_pressed_inside_change_dialog_does_not_react(monkeypatch, tmp_path, app):
    from mabinogi_addon.ui import blackbox_hotkey_dialog
    c, swapped, path = _controller(monkeypatch, tmp_path)
    reacted, pending = [], [(1, 99)]
    c._hotkey_pressed = lambda *a: reacted.append(a)
    c.events.consume_hotkey = lambda: pending.pop() if pending else None

    class Dialog:
        def __init__(self, current, parent=None):
            self.result_hotkey = None
        def exec(self):
            c._tick_hotkey_only()
            return 0
        def deleteLater(self):
            pass

    def tick_hotkey_only():
        shortcut = c.events.consume_hotkey()
        if shortcut is not None and not c._capturing_hotkey:
            c._hotkey_pressed(shortcut, None, False)
    c._tick_hotkey_only = tick_hotkey_only
    monkeypatch.setattr(blackbox_hotkey_dialog, 'HotkeyDialog', Dialog)
    c._change_hotkey()
    assert reacted == [] and swapped == ['discard'] and not c._capturing_hotkey
    assert 'hotkey' not in config.load_blackbox_preferences(path)  # 취소: 저장·교체 없음
    c.panel.deleteLater()


# ---- 공개 범위: 제작자가 아닌 디스코드 로그인 사용자 ----

def test_real_main_window_shows_blackbox_for_everyone(monkeypatch, app):
    from mabinogi_addon.system import autostart
    from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
    from mabinogi_addon.ui import main_window
    user = [None]
    monkeypatch.setattr(config, 'load_discord_user', lambda: user[0])
    monkeypatch.setattr(QApplication, 'quit', lambda: None)
    monkeypatch.setattr(autostart, 'is_enabled', lambda: False)
    monkeypatch.setattr(autostart, 'reconcile', lambda value: None)
    monkeypatch.setattr(main_window, 'create_window_watcher', lambda **kw: AlwaysActiveWatcher())
    monkeypatch.setattr(main_window.MainWindow, '_maybe_check_update', lambda self, *a: None)
    config._write_local_config({'general': {'skipSetup': True, 'tourShown': True, 'firstUseGuideShown': True}})
    host = main_window.MainWindow()
    try:
        for timer in host.findChildren(QTimer):
            timer.stop()
        names = lambda: [host._tabs.tabText(i) for i in range(host._tabs.count())]
        # 2026-10-28 기능 공개 정책 7절: 로그인하지 않아도 블랙박스 탭이 보인다
        assert '블랙박스' in names() and host.blackbox_tools._allowed()
        user[0] = {'id': '1234', 'name': '일반 사용자'}
        host.settings_tab.login_changed.emit()
        assert names().count('블랙박스') == 1 and host.blackbox_tools._allowed()
        assert '제작자' not in host._blackbox_badge.toolTip()
        panel = host.blackbox_tools.panel
        assert panel.findChild(type(panel.save), '') is not None
        user[0] = None  # 로그아웃해도 탭 유지(공개)
        host.settings_tab.login_changed.emit()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert '블랙박스' in names() and host.blackbox_tools._allowed()
        user[0] = {'id': '1234', 'name': '일반 사용자'}  # 다시 로그인 → 탭 복귀
        host.settings_tab.login_changed.emit()
        assert names().count('블랙박스') == 1
    finally:
        host._force_quit = True
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_blackbox_help_and_layout_have_no_alpha_wording(app):
    from mabinogi_addon.ui.blackbox_tab import BlackboxTab
    from mabinogi_addon.ui.feature_copy import HELP
    tab = BlackboxTab()
    try:
        text = ' '.join(w.text() for w in tab.findChildren(type(tab.status)))
        assert '제작자' not in text and '알파' not in text and '검증용' not in text and '실게임 미검증' not in text
        assert not hasattr(tab, 'preview_notice') and not hasattr(tab, 'save_result')
        assert tab.error.isHidden()
        for heading in ('저장 단축키', '녹화 방식', '저장 위치', '저장 내역·복구', '디스크 사용'):
            assert heading in HELP['블랙박스']
    finally:
        tab.deleteLater()


# ---- 상단 상태 표시: 눌러서 켜고 끄기(0.16.0 추가) ----

@pytest.fixture
def main(monkeypatch, app):
    from mabinogi_addon.system import autostart
    from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
    from mabinogi_addon.ui import main_window
    monkeypatch.setattr(config, 'load_discord_user', lambda: {'id': '1234', 'name': '일반 사용자'})
    monkeypatch.setattr(QApplication, 'quit', lambda: None)
    monkeypatch.setattr(autostart, 'is_enabled', lambda: False)
    monkeypatch.setattr(autostart, 'reconcile', lambda value: None)
    monkeypatch.setattr(main_window, 'create_window_watcher', lambda **kw: AlwaysActiveWatcher())
    monkeypatch.setattr(main_window.MainWindow, '_maybe_check_update', lambda self, *a: None)
    config._write_local_config({'general': {'skipSetup': True, 'tourShown': True, 'firstUseGuideShown': True}})
    host = main_window.MainWindow()
    for timer in host.findChildren(QTimer):
        timer.stop()
    yield host
    host.blackbox_tools.service = None  # 테스트용 가짜 서비스로 종료 경로를 타지 않게
    host._force_quit = True
    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_combat_status_button_toggles_pause_and_syncs_with_tray(main):
    from PySide6.QtWidgets import QPushButton
    button = main._combat_status
    assert isinstance(button, QPushButton) and button.isFlat()
    assert button.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert main._blackbox_badge.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert not hasattr(main, '_pause_btn') and not hasattr(main, '_status_label')
    assert button.text() == '● 전투 보조: 켜짐' and '#2ecc71' in button.styleSheet()
    assert 'underline' not in button.styleSheet() and '12px' in button.styleSheet()
    assert button.toolTip().startswith('누르면 전투 보조의 오버레이와 소리 알림을 잠시 멈춰요.')
    button.click()
    assert main._paused and button.text() == '● 전투 보조: 일시정지' and '#e74c3c' in button.styleSheet()
    assert button.toolTip() == '누르면 기존 설정에 따라 전투 보조의 표시와 알림을 다시 켜요.'
    if getattr(main, '_pause_act', None) is not None:
        assert main._pause_act.text() == '전투 보조 재개'
        main._pause_act.trigger()  # 트레이에서 재개 → 상단도 켜짐
        assert not main._paused and button.text() == '● 전투 보조: 켜짐'
        assert main._pause_act.text() == '전투 보조 일시정지'
    else:
        button.click()
        assert not main._paused


def test_first_run_tour_pause_step_targets_status_button(main):
    main._run_tour()
    try:
        step = next(step for step in main._tour._steps if step.title == '전체 일시정지')
        assert step.target is main._combat_status
        assert '「● 전투 보조: 켜짐」을 눌러주세요' in step.body
    finally:
        main._tour.close()


class _Service:
    def __init__(self, status='recording'):
        self.enabled, self.status, self.error = True, status, None
        self.calls = []
        self.current = NS(session=NS(_replay=NS(available_us=192_000_000)))
    def set_enabled(self, value):
        self.calls.append(value)
        self.enabled = value
        if not value:
            self.status = 'disabled'


def test_blackbox_badge_click_opens_tab_and_never_turns_off(main):
    # 0.17.2 사용자 결정: 상단 배지는 모든 상태에서 블랙박스 탭으로 이동(이전: 누르면 끄기). 끄기는 탭에서.
    tools = main.blackbox_tools
    tools._mode = 'always'  # 배지 문구만 본다(2026-10-25부터 기본은 전투 녹화)
    service = tools.service = _Service()
    tools.panel.enabled.toggled.connect(lambda value: tools._action(lambda: service.set_enabled(value)))
    tools.panel.enabled.setChecked(True)
    service.calls.clear()
    main._tabs.setCurrentIndex(0)
    tools._update_badge(192_000_000)
    badge = main._blackbox_badge
    assert not badge.isHidden() and badge.text() == '● 블랙박스: 보관 중 3:12' and '#2ecc71' in badge.styleSheet()
    assert 'underline' not in badge.styleSheet()
    assert badge.toolTip() == '누르면 블랙박스 탭으로 이동해요.'
    badge.click()
    assert service.calls == [] and service.enabled and tools.panel.enabled.isChecked()
    assert main._tabs.currentWidget() is tools._page
    assert not badge.isHidden()


def test_blackbox_badge_click_on_error_opens_tab_instead_of_turning_off(main):
    tools = main.blackbox_tools
    service = tools.service = _Service('error')
    main._tabs.setCurrentIndex(0)
    tools._update_badge(0)
    badge = main._blackbox_badge
    assert badge.text() == '● 블랙박스: 녹화 오류' and '#e74c3c' in badge.styleSheet()
    assert badge.toolTip() == '녹화 오류예요. 누르면 블랙박스 탭에서 내용을 볼 수 있어요.'
    badge.click()
    assert service.calls == [] and main._tabs.currentWidget() is tools._page


def test_blackbox_badge_muted_states_are_gray():
    from mabinogi_addon.blackbox_combat import CombatGate
    from mabinogi_addon.ui.blackbox_controller import BADGE_COLORS, blackbox_badge
    assert BADGE_COLORS == {'ok': '#2ecc71', 'muted': '#8a8f98', 'error': '#e74c3c'}
    for status in ('waiting', 'paused', 'preparing'):
        assert blackbox_badge(NS(enabled=True, status=status))[1] == 'muted'
    gate = CombatGate()
    gate.update(0, False, True)
    assert blackbox_badge(NS(enabled=True, status='recording'), 0, gate) == ('● 블랙박스: 전투 대기', 'muted')


# ---- 0.16.0 독립 QA(f0ce570) 회귀 ----

def test_retention_ignores_wheel_without_focus_so_scrolling_never_trims_video(app):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from mabinogi_addon.ui.blackbox_tab import BlackboxTab
    tab = BlackboxTab()
    try:
        tab.retention.setEnabled(True)
        tab.show()
        changes = []
        tab.retention.valueChanged.connect(changes.append)
        pos = QPointF(tab.retention.rect().center())
        def wheel():
            event = QWheelEvent(pos, QPointF(tab.retention.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, -120),
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(tab.retention, event)
            return event
        for _ in range(4):
            assert not wheel().isAccepted()  # 바깥 스크롤로 넘김
        assert tab.retention.value() == 5 and changes == []
        assert tab.retention.focusPolicy() == Qt.FocusPolicy.StrongFocus
    finally:
        tab.deleteLater()


def test_one_shot_error_notice_survives_ticks_and_recording_error_clears_when_resolved(monkeypatch, app):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('qa_0160', Path(__file__).resolve().parents[1] / 'scripts/qa_0160_blackbox_public.py')
    qa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qa)
    c = qa.controller()
    c._show_error('단축키를 바꾸지 못했어요: 설정 파일 쓰기 실패')
    for _ in range(3):
        c._tick()
    assert not c.panel.error.isHidden() and c.panel.error.text().startswith('단축키를 바꾸지 못했어요')
    c.service.error = 'encoder exited 1: nvenc'
    c._tick()
    assert c.panel.error.text() == '영상 인코더가 멈춰 녹화를 중단했어요 (자세한 내용: app.log)'
    c.service.error = None  # 녹화 오류가 풀리면 오류 줄을 비운다
    c._tick()
    assert c.panel.error.isHidden()
    c.panel.deleteLater()
