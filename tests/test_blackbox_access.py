import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from mabinogi_addon import config
from mabinogi_addon.blackbox import BufferFullError, ReplayBuffer, Segment
from mabinogi_addon.blackbox_session import BlackboxSession, CaptureContext, State
from mabinogi_addon.feature_access import CREATOR_DISCORD_ID
from mabinogi_addon.ui.blackbox_controller import BlackboxController


def window():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host._tabs = QTabWidget(host)
    for label in ('전투 보조', '편의기능', '설정'):
        page = QWidget()
        host._tabs.addTab(page, label)
    host._settings_scroll = page
    return app, host


@pytest.mark.parametrize('user', [None, {}, {'id': 'ordinary'}, {'id': CREATOR_DISCORD_ID}])
def test_top_level_tab_and_direct_commands_obey_creator_access(monkeypatch, user):
    monkeypatch.setattr(config, 'load_discord_user', lambda: user)
    app, host = window()
    tools = BlackboxController(host)
    creator = user == {'id': CREATOR_DISCORD_ID}
    assert ('블랙박스' in [host._tabs.tabText(i) for i in range(host._tabs.count())]) is creator
    assert (tools.panel is not None) is creator
    expected = RuntimeError if creator else PermissionError
    with pytest.raises(expected):
        tools.request_save(10)
    with pytest.raises(expected):
        tools.set_enabled(True)
    if creator:
        assert all(not c.isEnabled() for c in (tools.panel.enabled, tools.panel.retention,
            tools.panel.save, tools.panel.change_folder, tools.panel.open_folder))
    host.close()


def test_access_transitions_preserve_pending_save_but_invalidate_capture(monkeypatch):
    user = [None]
    monkeypatch.setattr(config, 'load_discord_user', lambda: user[0])
    app, host = window()
    replay = ReplayBuffer('run', max_bytes=100, max_segments=10, max_saves=2)
    session = BlackboxSession(replay, enabled=True, persist_enabled=lambda value: None)
    session.update_context(CaptureContext('run', foreground=True, ready=True))
    tools = BlackboxController(host, session=session)
    assert tools.panel is None
    user[0] = {'id': CREATOR_DISCORD_ID}
    tools.refresh_access()
    permit = session.capture_permit()
    session.append(permit, Segment('run', 'one', 0, 10, 10, 'test'))
    plan = tools.request_save(10)
    user[0] = {'id': 'ordinary'}
    tools.refresh_access()
    assert tools.panel is None and session.enabled and session.state == State.ACCESS_DENIED
    with pytest.raises(PermissionError):
        tools.request_save(20)
    with pytest.raises(PermissionError):
        session.capture_permit()
    with pytest.raises(BufferFullError):
        replay.clear()
    user[0] = {'id': CREATOR_DISCORD_ID}
    tools.refresh_access()
    with pytest.raises(PermissionError):
        session.append(permit, Segment('run', 'two', 10, 20, 10, 'test'))
    user[0] = None
    tools.refresh_access()
    session.release_save(plan)  # cleanup remains independent of UI access
    assert len(replay.clear()) == 1
    host.close()


def test_repeated_access_changes_do_not_leave_duplicate_tabs(monkeypatch):
    user = [None]
    monkeypatch.setattr(config, 'load_discord_user', lambda: user[0])
    app, host = window()
    tools = BlackboxController(host)
    for _ in range(100):
        user[0] = {'id': CREATOR_DISCORD_ID}
        tools.refresh_access()
        tools.refresh_access()
        assert host._tabs.count() == 4
        user[0] = None
        tools.refresh_access()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert host._tabs.count() == 3
    host.close()


def test_real_main_window_uses_top_level_tab_only_for_creator(monkeypatch):
    from mabinogi_addon.system import autostart
    from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
    from mabinogi_addon.ui import main_window
    app = QApplication.instance() or QApplication([])
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
        assert host.blackbox_tools.panel is None
        user[0] = {'id': CREATOR_DISCORD_ID}
        host.settings_tab.login_changed.emit()
        page = host.blackbox_tools._page
        assert host._tabs.indexOf(page) >= 0
        assert host._convenience_tabs.indexOf(page) == -1
        assert host.blackbox_tools.session is None
        user[0] = None
        host.settings_tab.login_changed.emit()
        assert host.blackbox_tools.panel is None
        assert all(host._tabs.tabText(i) != '블랙박스' for i in range(host._tabs.count()))
    finally:
        host._force_quit = True
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('active, received_hwnd, allowed, expected', [
    (True, 42, True, [123456]), (False, 42, True, []),
    (True, 99, True, []), (True, 42, False, []),
])
def test_hook_request_keeps_received_endpoint_and_requires_game_and_access(
        monkeypatch, active, received_hwnd, allowed, expected):
    from types import SimpleNamespace
    monkeypatch.setattr(config, 'load_discord_user', lambda: None)
    app, host = window()
    tools = BlackboxController(host)
    saved = []
    tools.service = SimpleNamespace(tick=lambda *a, **kw: None,
        request_save=saved.append, completed=[], error=None)
    pending = [(123456, received_hwnd)]
    tools.events = SimpleNamespace(sample=lambda: (SimpleNamespace(hwnd=42), active),
        consume_hotkey=lambda: pending.pop() if pending else None)
    monkeypatch.setattr(tools, '_allowed', lambda: allowed)
    tools._tick()
    tools._tick()
    assert saved == expected
    host.close()


def test_hook_failure_is_visible_without_submitting_a_save(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(config, 'load_discord_user', lambda: None)
    app, host = window()
    tools = BlackboxController(host)
    saved = []
    tools.service = SimpleNamespace(tick=lambda *a, **kw: None,
        request_save=saved.append, completed=[], error=None)
    def failed():
        raise OSError('keyboard hook message loop failed')
    tools.events = SimpleNamespace(sample=lambda: (SimpleNamespace(hwnd=42), True),
        consume_hotkey=failed)
    tools._tick()
    assert not saved
    assert 'message loop failed' in tools.service.error
    host.close()


@pytest.mark.parametrize('modifiers, vk, text', [
    (3, 0x79, 'Ctrl+Alt+F10'), (2, 0x41, 'Ctrl+A'), (4, 0x31, 'Shift+1'), (8, 0x70, 'Win+F1'),
    (0, 0x87, 'F24'), (1, 0x2E, 'Alt+Delete'), (0, 0xFF, '키 코드 0xFF')])
def test_hotkey_is_shown_with_key_names_not_vk_codes(modifiers, vk, text):
    from mabinogi_addon.ui.blackbox_controller import hotkey_text
    assert hotkey_text(modifiers, vk) == text


@pytest.mark.parametrize('active, received_hwnd, refuse, expected', [
    (True, 42, True, '지금은 저장할 수 없어요: video buffer limit'),
    (False, 42, False, '게임 창이 앞에 있을 때만'),
    (True, 42, False, '저장 요청을 접수했어요'),
])
def test_hotkey_feedback_stays_visible_over_recording_error(monkeypatch, active, received_hwnd, refuse, expected):
    """녹화 오류 중에도 단축키를 누른 결과가 매 틱 오류 문구에 덮이지 않고 보인다."""
    from types import SimpleNamespace
    from mabinogi_addon.ui import blackbox_controller as module
    from mabinogi_addon.ui.blackbox_tab import BlackboxTab
    monkeypatch.setattr(config, 'load_discord_user', lambda: None)
    app, host = window()
    tools = BlackboxController(host)
    tools.panel = BlackboxTab()
    error = 'video buffer limit' if refuse else None
    def request_save(us):
        if refuse:
            raise PermissionError('save unavailable')
    def tick(*a, **kw):
        tools.service.error = error  # 실제 서비스처럼 매 틱 오류를 다시 기록
    tools.service = SimpleNamespace(tick=tick, request_save=request_save, completed=[], error=error,
        status='error' if refuse else 'recording', current=None, _retention=600_000_000,
        settings=SimpleNamespace(output_folder='out'), recoveries=lambda: [])
    pending = [(123456, received_hwnd)]
    tools.events = SimpleNamespace(sample=lambda: (SimpleNamespace(hwnd=42), active),
        consume_hotkey=lambda: pending.pop() if pending else None)
    monkeypatch.setattr(tools, '_allowed', lambda: True)
    for _ in range(3):
        tools._tick()
        assert expected in tools.panel.save_result.text()
    clock = [module._HOTKEY_NOTE_SEC + 10**6]
    monkeypatch.setattr('time.monotonic', lambda: clock[0])
    tools._tick()
    if refuse:  # 표시 시간이 지나면 다시 녹화 오류 문구가 보인다.
        assert tools.panel.save_result.text() == error
    # 강조가 사라져도 마지막 단축키 입력 시각·결과는 계속 남는다(게임→앱 전환 대비).
    import re
    tools._hotkey_base = '검증용 단축키: Ctrl+Alt+F10 · 실게임 미검증'
    tools._show_hotkey()
    lines = tools.panel.hotkey.text().split('\n')
    assert lines[0] == tools._hotkey_base
    assert re.fullmatch(r'마지막 단축키 입력 \d\d:\d\d:\d\d · .+', lines[1])
    assert {'지금은 저장할 수 없어요': '저장 불가: video buffer limit', '게임 창이 앞에': '게임 창이 앞에 있지 않아',
            '접수했어요': '저장 요청 접수'}[next(k for k in ('지금은 저장할 수 없어요', '게임 창이 앞에', '접수했어요')
                                          if k in expected)] in lines[1]
    tools.panel.deleteLater()
    host.close()
