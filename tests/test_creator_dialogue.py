import json
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QPushButton

from mabinogi_addon import config, paths
from mabinogi_addon.creator_dialogue import DialogueSession, MAX_BYTES, parse, read
from mabinogi_addon.system.dialogue_visibility import subtract, exposed
from mabinogi_addon.ui.dialogue_feed import DialogueFeed

START_FEED = DialogueFeed.start


def data(*parts):
    return {"schemaVersion": 1, "language": "ko-KR", "format": "choice-parts-v1",
            "entries": [{"id": str(i), "parts": [text]} for i, text in enumerate(parts or ("안녕", "반가워"))]}


def encode(raw):
    return json.dumps(raw, ensure_ascii=False).encode()


def test_bundled_is_exact_initial_twelve():
    assert (paths.resource_dir() / "dialogues.json").read_bytes() == (
        paths.project_root() / "docs/examples/creator-dialogues/dialogues.json").read_bytes()
    assert len(read(paths.resource_dir() / "dialogues.json")) == 12


@pytest.mark.parametrize("modify", [
    lambda d: d.update(schemaVersion=True), lambda d: d.update(format="python"),
    lambda d: d.update(language="en"), lambda d: d.update(entries=[]),
    lambda d: d["entries"].append(d["entries"][0]),
    lambda d: d["entries"][0].update(parts=[]),
    lambda d: d["entries"][0].update(parts=[[]]),
    lambda d: d["entries"][0].update(parts=[[3]]),
    lambda d: d["entries"][0].update(parts=["x" * 61]),
    lambda d: d["entries"][0].update(parts=["a\nb"]),
    lambda d: d["entries"][0].update(parts=[{"eval": "code"}]),
])
def test_invalid_data_rejected(modify):
    raw = data()
    modify(raw)
    with pytest.raises(ValueError):
        parse(encode(raw))


@pytest.mark.parametrize("raw", [b"broken", b"x" * (MAX_BYTES + 1), b"[" * 10000 + b"]" * 10000])
def test_bad_encoding_size_nesting(raw):
    with pytest.raises(ValueError):
        parse(raw)


def test_probability_interval_and_exact_rolling_boundary():
    rng = Mock()
    rng.random.return_value = .3
    session = DialogueSession(parse(encode(data())), rng)
    assert session.draw(0)
    assert not session.draw(119.99)
    assert rng.random.call_count == 1
    session.displayed("a", 0, automatic=True)
    session.displayed("b", 120, automatic=True)
    session.displayed("c", 240, automatic=True)
    assert not session.draw(360)  # 3회이면 20%
    assert not session.draw(479)
    assert session.draw(600)  # 정확히 600초 전 기록 제외, 40% 복귀
    assert list(session.shown) == [120, 240]
    assert session.draw(100000)  # 숨겨진 주기를 누적하지 않음
    assert not session.draw(100001)
    assert not session.shown


def test_failed_draw_still_waits_and_restart_resets():
    session = DialogueSession(parse(encode(data())), Mock(random=lambda: .99))
    assert not session.draw(0)
    session.rng.random = Mock(return_value=0)
    assert not session.draw(119)
    assert session.rng.random.call_count == 0
    assert DialogueSession(session.entries, session.rng).draw(119)


def test_no_repeat_or_infinite_retry_and_click_not_counted():
    session = DialogueSession(parse(encode(data("고정"))))
    assert session.choose() == "고정"
    session.displayed("고정", 0, automatic=False)
    assert not session.shown
    assert session.choose() is None
    session.entries = parse(encode(data("다름")))
    assert session.choose() == "다름"
    assert session.choose(lambda text: False) is None


def test_choice_parts_are_literal_not_execution():
    raw = data()
    raw["entries"] = [{"id": "a", "parts": ["${danger}", ["A", "B"], "!"]}]
    session = DialogueSession(parse(encode(raw)))
    assert session.choose() in {"${danger}A!", "${danger}B!"}


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class Reply(QObject):
    readyRead = Signal()
    finished = Signal()

    def __init__(self, body, status=200, error=QNetworkReply.NetworkError.NoError):
        super().__init__()
        self.body, self.status, self.err = body, status, error
        self.aborted = False

    def read(self, size):
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk

    def setReadBufferSize(self, size):
        self.buffer_limit = size

    def attribute(self, attr):
        return self.status

    def error(self):
        return self.err

    def abort(self):
        self.aborted = True
        self.err = QNetworkReply.NetworkError.OperationCanceledError
        self.finished.emit()


def feed_with(reply):
    feed = DialogueFeed()
    feed.network = Mock(get=Mock(return_value=reply))
    START_FEED(feed)
    return feed


def test_receive_once_and_atomic_cache(app):
    payload = encode(data("외부 대사"))
    reply = Reply(payload)
    feed = feed_with(reply)
    try:
        START_FEED(feed)
        assert feed.network.get.call_count == 1
        request = feed.network.get.call_args.args[0]
        assert request.url().scheme() == "https"
        assert request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute) == QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
        reply.finished.emit()
        assert feed.entries == parse(payload)
        assert feed.cache.read_bytes() == payload
        assert not feed.timer.isActive()
        assert feed.reply is None
    finally:
        feed.shutdown()


@pytest.mark.parametrize("payload,status,error", [
    (b"broken", 200, QNetworkReply.NetworkError.NoError),
    (encode(data()), 404, QNetworkReply.NetworkError.NoError),
    (encode(data()), 302, QNetworkReply.NetworkError.NoError),
    (b"x" * (MAX_BYTES + 1), 200, QNetworkReply.NetworkError.NoError),
    (encode(data()), 200, QNetworkReply.NetworkError.TimeoutError),
])
def test_receive_failure_keeps_last_good(app, payload, status, error):
    cache = paths.user_data_dir() / "creator-dialogues.json"
    good = encode(data("저장된 대사"))
    cache.write_bytes(good)
    reply = Reply(payload, status, error)
    feed = feed_with(reply)
    try:
        reply.finished.emit()
        assert feed.entries == parse(good)
        assert cache.read_bytes() == good
        assert len(feed.buffer) == 0
    finally:
        feed.shutdown()


def test_bad_cache_falls_back_and_shutdown_aborts(app):
    cache = paths.user_data_dir() / "creator-dialogues.json"
    cache.write_bytes(b"broken")
    reply = Reply(encode(data()))
    feed = feed_with(reply)
    feed.shutdown()
    assert reply.aborted
    assert feed.entries == read(paths.resource_dir() / "dialogues.json")
    assert not feed.timer.isActive()
    assert cache.read_bytes() == b"broken"


def test_transport_start_failure_is_nonfatal(app):
    feed = DialogueFeed()
    feed.network = Mock(get=Mock(side_effect=OSError("network unavailable")))
    START_FEED(feed)
    assert feed.entries
    assert feed.reply is None
    assert not feed.timer.isActive()
    feed.shutdown()


def test_missing_all_data_is_silent_not_an_app_failure(app, monkeypatch):
    from mabinogi_addon.ui import dialogue_feed
    monkeypatch.setattr(dialogue_feed, "read", Mock(side_effect=PermissionError("unreadable")))
    feed = DialogueFeed()
    try:
        session = DialogueSession(feed.entries)
        assert session.choose() is None
        assert not feed.timer.isActive()
    finally:
        feed.shutdown()


def test_save_failure_keeps_in_memory_list(app, monkeypatch):
    from mabinogi_addon.ui import dialogue_feed
    payload = encode(data("새로운 대사"))
    writer = Mock(open=Mock(return_value=False))
    monkeypatch.setattr(dialogue_feed, "QSaveFile", lambda path: writer)
    feed = feed_with(Reply(payload))
    try:
        feed.reply.finished.emit()
        assert feed.entries == parse(payload)
    finally:
        feed.shutdown()


@pytest.fixture
def window(app, monkeypatch):
    from mabinogi_addon.ui.main_window import MainWindow
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    w = MainWindow()
    w.show()
    app.processEvents()
    w.creator_dialogue.visibility = lambda *args: True
    yield w
    w._force_quit = True
    w.close()


def test_approved_geometry_and_tail_and_no_focus(window, app):
    d = window.creator_dialogue
    before = QApplication.focusWidget()
    assert d.request()
    assert d.bubble.isVisible()
    assert d.bubble.width() == d.bubble.text.width() + 20
    assert d.bubble.height() == d.bubble.text.height() + 24
    assert QApplication.focusWidget() is before
    assert d.bubble.geometry().bottom() < d.face.mapTo(window.centralWidget(), d.face.rect().topLeft()).y()
    assert d.footer.isVisible()
    window._tabs.setCurrentIndex(3)
    app.processEvents()
    assert not d.footer.isVisible()
    assert not d.bubble.isVisible()
    assert d.request()
    assert d.bubble.side == "left"
    window._tabs.widget(3).verticalScrollBar().setValue(100)
    app.processEvents()
    assert not d.bubble.isVisible()
    assert not d.request()


@pytest.mark.parametrize("sound", [None, Mock(), Mock(side_effect=FileNotFoundError), Mock(side_effect=RuntimeError)])
def test_optional_sound_never_required(window, sound):
    d = window.creator_dialogue
    d.sound = sound
    assert d.request()
    assert d.bubble.isVisible()
    if sound is not None:
        sound.assert_called_once_with(d.session.last_text)


def test_click_replaces_and_option_stops_all(window):
    d = window.creator_dialogue
    d.face.click()
    assert d.bubble.isVisible()
    first = d.session.last_text
    d.face.click()
    assert d.session.last_text != first
    assert not d.session.shown
    assert d.expiry.isActive()
    window.settings_tab.dialogue_enabled.setChecked(False)
    assert not d.bubble.isVisible()
    assert not d.request()
    assert not config.load_general_flag("creatorDialogue", True)


def test_expiry_occlusion_gap_and_no_backlog(window):
    d = window.creator_dialogue
    now = [0.0]
    d.clock = lambda: now[0]
    d.session.rng.random = lambda: 0.0
    d.tick()
    assert d.bubble.isVisible()
    assert len(d.session.shown) == 1
    now[0] = 2
    d.tick()
    assert len(d.session.shown) == 1
    now[0] = 3
    d.tick()
    assert not d.bubble.isVisible()
    assert d.request()
    d.visibility = lambda *args: False
    d.tick()
    assert not d.bubble.isVisible()
    now[0] = 10000
    d.tick()
    d.visibility = lambda *args: True
    now[0] += 1
    d.tick()
    assert len(d.session.shown) == 1  # 오래된 기록은 제외하고 새 표시 1회만 남는다.
    assert d.session.last_draw == 10001
    assert d.bubble.isVisible()


def test_recheck_before_display_and_excluded_screens(window):
    d = window.creator_dialogue
    values = iter([True, False])
    d.visibility = lambda *args: next(values)
    assert not d.request(automatic=True)
    assert not d.session.shown
    d.visibility = lambda *args: True
    window._pages.setCurrentWidget(window.setup_guide)
    assert not d.request()
    assert not d.footer.isVisible()


def test_bubble_click_consumes_and_repetition_does_not_leak(window, app):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    d = window.creator_dialogue
    button = QPushButton(window.centralWidget())
    calls = Mock()
    button.clicked.connect(calls)
    for _ in range(50):
        assert d.request()
        button.setGeometry(d.bubble.geometry())
        button.show()
        d.bubble.raise_()
        QTest.mouseClick(d.bubble, Qt.MouseButton.LeftButton)
        assert not d.bubble.isVisible()
    calls.assert_not_called()
    assert len(d.findChildren(QTimer)) == 3  # poll, expiry, one receive deadline
    d.shutdown()
    assert not any(t.isActive() for t in d.findChildren(QTimer))


def test_region_subtraction_and_fail_closed():
    assert subtract((0, 0, 10, 10), (10, 0, 20, 10)) == [(0, 0, 10, 10)]
    assert subtract((0, 0, 10, 10), (0, 0, 10, 10)) == []
    assert subtract((0, 0, 10, 10), (5, 0, 10, 10)) == [(0, 0, 5, 10)]
    assert not exposed(0, [(0, 0, 10, 10)], (100, 100))


@pytest.mark.parametrize("message,value,blocked", [
    (0x02B1, 7, True), (0x02B1, 4, True), (0x0218, 4, True),
    (0x02B1, 8, False), (0x0218, 18, False),
])
def test_session_and_power_closes_without_restoring(window, message, value, blocked):
    d = window.creator_dialogue
    assert d.request()
    d.system_message(message, value)
    assert not d.bubble.isVisible()
    assert d.request() is not blocked


@pytest.mark.parametrize("cover,cloaked,expected", [
    ((100, 100, 110, 110), False, True),
    ((-980, 20, -960, 40), False, False),
    ((-980, 20, -960, 40), True, True),
])
def test_windows_physical_coords_z_order_not_focus(monkeypatch, cover, cloaked, expected):
    import ctypes
    import sys
    from types import SimpleNamespace
    from mabinogi_addon.system import dialogue_visibility as visibility

    def attribute(hwnd, key, pointer, size):
        if key == 14:
            pointer._obj.value = int(cloaked)
        else:
            pointer._obj.left, pointer._obj.top, pointer._obj.right, pointer._obj.bottom = cover
        return 0

    gui = SimpleNamespace(IsWindowVisible=lambda hwnd: True, IsIconic=lambda hwnd: False,
                          GetClientRect=lambda hwnd: (0, 0, 800, 800),
                          ClientToScreen=lambda hwnd, point: (-1000, 0),
                          EnumWindows=lambda callback, arg: [callback(hwnd, arg) for hwnd in (22, 11, 33)])
    monkeypatch.setattr(visibility, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(visibility, "desktop_unlocked", lambda: True)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(dwmapi=SimpleNamespace(DwmGetWindowAttribute=attribute)), raising=False)
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(EnumDisplayMonitors=lambda: [(1, None, (-1000, 0, 0, 1000))]))
    assert visibility.exposed(11, [(10, 10, 10, 10)], (400, 400)) is expected
    monkeypatch.setattr(visibility, "desktop_unlocked", lambda: False)
    assert not visibility.exposed(11, [(10, 10, 10, 10)], (400, 400))


def test_two_line_wrapping_has_no_clipping(window):
    bubble = window.creator_dialogue.bubble
    message = "지금은 잠깐 생각 중입니다. 조금만 더 생각해 보겠습니다."
    assert bubble.set_message(message)
    assert bubble.text.height() >= bubble.text.fontMetrics().height()
    assert bubble.body_height == bubble.text.height() + 14
    assert not bubble.set_message("가" * 200)


def test_first_show_clamps_restored_position_and_tour_dismisses(window, app):
    d = window.creator_dialogue
    area = window.screen().availableGeometry()
    window.hide()
    window.move(window.x(), area.bottom())
    window.show()
    app.processEvents()
    assert window.y() + window.height() <= area.bottom() + 1
    assert d.request()
    window._run_tour()
    assert not d.bubble.isVisible()
    assert not d.request()
