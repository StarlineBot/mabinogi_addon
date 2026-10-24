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
def test_top_level_tab_and_direct_commands_obey_login_access(monkeypatch, user):
    # 0.16.0: 블랙박스는 제작자 전용 → 디스코드 로그인 사용자(베타). 제작자가 아닌 로그인 사용자도 사용 가능.
    monkeypatch.setattr(config, 'load_discord_user', lambda: user)
    app, host = window()
    tools = BlackboxController(host)
    creator = bool(user and user.get('id'))  # 로그인 여부
    assert ('블랙박스' in [host._tabs.tabText(i) for i in range(host._tabs.count())]) is creator
    assert (tools.panel is not None) is creator
    expected = RuntimeError if creator else PermissionError
    with pytest.raises(expected):
        tools.request_save(10)
    with pytest.raises(expected):
        tools.set_enabled(True)
    if creator:
        assert all(not c.isEnabled() for c in tools.panel.controls())
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
    user[0] = {'id': 'ordinary'}
    tools.refresh_access()
    permit = session.capture_permit()
    session.append(permit, Segment('run', 'one', 0, 10, 10, 'test'))
    plan = tools.request_save(10)
    user[0] = None  # 로그아웃
    tools.refresh_access()
    assert tools.panel is None and session.enabled and session.state == State.ACCESS_DENIED
    with pytest.raises(PermissionError):
        tools.request_save(20)
    with pytest.raises(PermissionError):
        session.capture_permit()
    with pytest.raises(BufferFullError):
        replay.clear()
    user[0] = {'id': 'ordinary'}
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
    (True, 42, True, '최근 저장: 저장 안 함 · 확보한 영상 없음'),
    (False, 42, False, '최근 저장: 아직 없어요'),  # 게임이 앞에 없으면 게임 화면 알림만(탭 줄은 그대로)
    (True, 42, False, '최근 저장: 저장 요청을 접수했어요'),
])
def test_hotkey_result_status_and_error_use_separate_lines(monkeypatch, active, received_hwnd, refuse, expected):
    """0.16.0: 상태·오류·최근 저장이 각각 다른 위젯이라 0.1초 틱이 서로 덮어쓰지 않는다. 오류는 한국어 요약 + app.log 안내."""
    from types import SimpleNamespace
    from mabinogi_addon.ui.blackbox_tab import BlackboxTab
    monkeypatch.setattr(config, 'load_discord_user', lambda: None)
    app, host = window()
    tools = BlackboxController(host)
    tools.panel = BlackboxTab()
    error = 'encoder exited 1: h264_nvenc: OpenEncodeSessionEx failed' if refuse else None
    def request_save(us):
        if refuse:
            raise PermissionError('save unavailable')
    def tick(*a, **kw):
        tools.service.error = error  # 실제 서비스처럼 매 틱 오류를 다시 기록
    tools.service = SimpleNamespace(tick=tick, request_save=request_save, completed=[], error=error,
        status='error' if refuse else 'recording', current=None, _retention=300_000_000,
        settings=SimpleNamespace(output_folder='out'), recoveries=lambda: [])
    pending = [(123456, received_hwnd)]
    tools.events = SimpleNamespace(sample=lambda: (SimpleNamespace(hwnd=42), active),
        consume_hotkey=lambda: pending.pop() if pending else None)
    toasts = []
    monkeypatch.setattr(tools, '_allowed', lambda: True)
    monkeypatch.setattr(tools, '_react', lambda text, kind, target=None: toasts.append(text))
    for _ in range(3):
        tools._tick()
        assert tools.panel.recent.text() == expected
        assert tools.panel.status.text() == ('녹화 오류' if refuse else '보관 중')
        if refuse:
            assert tools.panel.error.text() == '영상 인코더가 멈춰 녹화를 중단했어요 (자세한 내용: app.log)'
            assert not tools.panel.error.isHidden() and 'encoder exited' not in tools.panel.error.text()
        else:
            assert tools.panel.error.isHidden()
    assert len(toasts) == 1 and toasts[0].startswith('저장 실패' if (refuse or not active) else '저장 중 0%')
    assert not hasattr(tools.panel, 'save_result')
    tools.panel.deleteLater()
    host.close()


def test_hotkey_is_ignored_while_game_records_in_background(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(config, 'load_discord_user', lambda: None)
    app, host = window()
    tools = BlackboxController(host)
    saved = []
    tools.service = SimpleNamespace(tick=lambda *a, **kw: None, request_save=saved.append, completed=[], error=None)
    pending = [(123456, 42)]
    tools.events = SimpleNamespace(sample=lambda: (SimpleNamespace(hwnd=42), True), foreground=False,
                                   consume_hotkey=lambda: pending.pop() if pending else None)
    monkeypatch.setattr(tools, '_allowed', lambda: True)
    tools._tick()
    assert saved == []  # 뒤에서 녹화 중(active)이어도 게임이 앞에 없으면 단축키로 저장하지 않음
    host.close()
