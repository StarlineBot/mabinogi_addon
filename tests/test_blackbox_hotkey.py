"""Synthetic messages only: never install an OS hook."""
from queue import Queue
import pytest
from mabinogi_addon.system.blackbox_hotkey import Chord, HotkeyObserver


def test_chord_repeat_keyup_injection_and_exact_modifiers():
    chord = Chord(3, 0x79)
    assert not chord.feed(0xA2, 0x100, 0)
    assert not chord.feed(0xA4, 0x104, 0)
    assert chord.feed(0x79, 0x104, 0)
    assert not chord.feed(0x79, 0x104, 0)
    assert not chord.feed(0x79, 0x105, 0)
    assert not chord.feed(0x79, 0x104, 0x10)
    assert not chord.feed(0x79, 0x104, 0x02)
    assert chord.feed(0x79, 0x104, 0)
    chord.feed(0x79, 0x105, 0)
    chord.feed(0xA0, 0x100, 0)
    assert not chord.feed(0x79, 0x104, 0)
    assert not chord.feed(0x41, 0x100, 0)
    assert 0x41 not in chord.down


class API:
    def __init__(self, failure=None):
        self.messages = Queue()
        self.failure = failure
        self.unhooked = []
        self.quit_ids = []
        self.hwnd = 123
    def prepare(self):
        return 42
    def install(self, observe):
        if self.failure == 'install':
            raise OSError('SetWindowsHookExW failed')
        self.observe = observe
        return 77
    def foreground(self):
        return self.hwnd
    def pump(self):
        item = self.messages.get(timeout=2)
        if isinstance(item, Exception):
            raise item
        return item
    def quit(self, thread_id):
        self.quit_ids.append(thread_id)
        self.messages.put(False)
    def uninstall(self, handle):
        self.unhooked.append(handle)
        if self.failure == 'unhook':
            raise OSError('UnhookWindowsHookEx failed')


def press(api):
    for key in (0xA2, 0xA4, 0x79):
        api.observe(key, 0x100, 0)
    api.observe(0x79, 0x101, 0)


def test_pending_timestamp_hwnd_bounded_queue_and_shutdown(monkeypatch):
    monkeypatch.setattr('mabinogi_addon.system.blackbox_hotkey.perf_counter_ns', lambda: 1234567000)
    api = API()
    observer = HotkeyObserver(3, 0x79, api_factory=lambda: api)
    try:
        press(api)
        api.hwnd = 456
        press(api)
        press(api)
        assert observer.consume() == (1234567, 123)
        assert observer.consume() == (1234567, 456)
        with pytest.raises(OSError, match='대기 한도 초과'):
            observer.consume()
        assert observer.consume() is None
        press(api)
        observer.discard()
        assert observer.consume() is None
    finally:
        observer.close()
    observer.close()
    assert api.unhooked == [77]
    assert not observer.thread.is_alive()


def test_install_failure_diagnostic_and_thread_exit():
    api = API('install')
    with pytest.raises(OSError, match='SetWindowsHookExW'):
        HotkeyObserver(3, 0x79, api_factory=lambda: api)
    assert api.unhooked == []


def test_message_loop_error_unhooks_and_reports():
    api = API()
    observer = HotkeyObserver(3, 0x79, api_factory=lambda: api)
    api.messages.put(OSError('GetMessageW failed'))
    observer.thread.join(2)
    with pytest.raises(OSError, match='GetMessageW'):
        observer.consume()
    assert api.unhooked == [77]
    assert not observer.thread.is_alive()


def test_unhook_failure_reported():
    api = API('unhook')
    observer = HotkeyObserver(3, 0x79, api_factory=lambda: api)
    with pytest.raises(OSError, match='UnhookWindowsHookEx'):
        observer.close()
    assert not observer.thread.is_alive()


def test_hook_callback_always_forwards_negative_injected_and_exception_paths():
    import ctypes as C
    from types import SimpleNamespace
    from mabinogi_addon.system.blackbox_hotkey import WinHookAPI
    class Key(C.Structure):
        _fields_ = [('vkCode', C.c_uint32), ('flags', C.c_uint32)]
    forwarded = []
    api = WinHookAPI.__new__(WinHookAPI)
    api.Key = Key
    api.callback_type = lambda fn: fn
    api.kernel = SimpleNamespace(GetModuleHandleW=lambda _: 1)
    api.user = SimpleNamespace(
        SetWindowsHookExW=lambda *args: 7,
        CallNextHookEx=lambda *args: forwarded.append(args) or 321)
    def broken_observer(*args):
        raise ValueError('synthetic callback failure')
    assert api.install(broken_observer) == 7
    assert api.callback(-1, 0x100, 0) == 321
    key = Key(0x79, 0x10)
    assert api.callback(0, 0x100, C.addressof(key)) == 321
    assert isinstance(api.callback_error, ValueError)
    assert len(forwarded) == 2


def test_session_and_suspend_messages_discard_pending_without_wm_hotkey():
    from mabinogi_addon.system.blackbox_events import WindowsEvents
    api = API()
    events = WindowsEvents.__new__(WindowsEvents)
    events.locked = events.suspended = False
    events.observer = HotkeyObserver(3, 0x79, api_factory=lambda: api)
    try:
        press(api)
        assert not events.message(0x2B1, 7)
        assert events.locked and events.consume_hotkey() is None
        press(api)
        events.message(0x2B1, 8)
        assert not events.locked and events.consume_hotkey() is None
        press(api)
        events.message(0x218, 4)
        assert events.suspended and events.consume_hotkey() is None
        events.message(0x218, 18)
        assert not events.suspended
        assert not events.message(0x312, events.ID)
    finally:
        events.observer.close()


def test_unexpected_quit_is_reported_but_successful_cleanup_allows_close():
    api = API()
    observer = HotkeyObserver(3, 0x79, api_factory=lambda: api)
    api.messages.put(False)
    observer.thread.join(2)
    with pytest.raises(OSError, match='예기치 않게'):
        observer.consume()
    observer.close()
    assert api.unhooked == [77]


def test_callback_error_visible_while_message_loop_waits():
    api = API()
    observer = HotkeyObserver(3, 0x79, api_factory=lambda: api)
    try:
        api.callback_error = ValueError('observation failed')
        with pytest.raises(OSError, match='observation failed'):
            observer.consume()
    finally:
        observer.close()


@pytest.mark.parametrize('pause,resume', [((0x2B1, 7), (0x2B1, 8)),
                                        ((0x218, 4), (0x218, 18))])
def test_session_boundary_invalidates_modifier_state_when_keyup_was_not_delivered(pause, resume):
    from mabinogi_addon.system.blackbox_events import WindowsEvents
    api = API()
    events = WindowsEvents.__new__(WindowsEvents)
    events.locked = events.suspended = False
    events.observer = HotkeyObserver(3, 0x79, api_factory=lambda: api)
    try:
        api.observe(0xA2, 0x100, 0)
        api.observe(0xA4, 0x104, 0)
        events.message(*pause)
        # Secure desktop/suspend can prevent delivery of the modifier releases.
        events.message(*resume)
        api.observe(0x79, 0x100, 0)
        assert events.consume_hotkey() is None
        api.observe(0x79, 0x101, 0)
        press(api)
        assert events.consume_hotkey()[1] == 123
    finally:
        events.observer.close()


def test_inflight_pre_boundary_chord_cannot_append_a_valid_request():
    api = API()
    observer = HotkeyObserver(3, 0x79, api_factory=lambda: api)
    try:
        def boundary_during_callback():
            observer.discard()
            return 123
        api.foreground = boundary_during_callback
        press(api)
        assert observer.consume() is None
        api.foreground = lambda: 123
        api.observe(0x79, 0x100, 0)
        assert observer.consume() is None
    finally:
        observer.close()
