"""Independent dialogue visibility/data/lifecycle probes with no real network."""

from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, paths, setup_state, version
from mabinogi_addon.creator_dialogue import DialogueSession, parse
from mabinogi_addon.ui.dialogue_feed import DialogueFeed
from mabinogi_addon.ui.main_window import MainWindow
from test_support.boundaries import ExternalBoundaries

REAL_START = DialogueFeed.start


def payload(*texts):
    return json.dumps({"schemaVersion": 1, "language": "ko-KR", "format": "choice-parts-v1",
                       "entries": [{"id": str(i), "parts": [text]}
                                   for i, text in enumerate(texts)]}).encode()


class Reply(QObject):
    readyRead = Signal()
    finished = Signal()

    def __init__(self, body):
        super().__init__()
        self.body = body

    def read(self, limit):
        result, self.body = self.body[:limit], self.body[limit:]
        return result

    def setReadBufferSize(self, size):
        self.limit = size

    def attribute(self, _):
        return 200

    def error(self):
        return QNetworkReply.NetworkError.NoError

    def abort(self):
        self.finished.emit()


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    raw = {feature.section: {"enabled": False} for feature in setup_state.FEATURES}
    raw["general"] = {"skipSetup": True, "creatorDialogue": True}
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: deepcopy(raw))
    monkeypatch.setattr(config, "_write_local_config", lambda *a, **k: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(version, "__version__", "0.0.0")
    monkeypatch.setattr(MainWindow, "_maybe_check_update", lambda *a: None)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    with ExternalBoundaries() as boundary:
        w = MainWindow()
        d = w.creator_dialogue
        now = [0.0]
        d.clock = lambda: now[0]
        d.visibility = lambda *args: True
        w.show()
        app.processEvents()
        d.start()
        try:
            yield w, d, now
        finally:
            w._force_quit = True
            w.close()
            app.processEvents()
            assert d.closed and not any(timer.isActive() for timer in d.findChildren(QTimer))
            w.deleteLater()
            app.processEvents()
            assert not boundary.violations


def test_replacement_recheck_failure_cannot_change_a_visible_bubble(window):
    _w, d, _now = window
    d.session.entries = parse(payload("first message"))
    assert d.request()
    assert d.bubble.text.text() == d.session.last_text == "first message"
    d.session.entries = parse(payload("second message"))
    visibility = iter([True, False])
    d.visibility = lambda *args: next(visibility)
    result = d.request()
    assert not result
    assert not d.bubble.isVisible() or d.bubble.text.text() == d.session.last_text, {
        "visible": d.bubble.isVisible(), "visible_text": d.bubble.text.text(),
        "recorded_last_text": d.session.last_text, "deadline": d.deadline,
    }


def test_unrenderable_remote_list_preserves_usable_last_good_data(window):
    _w, d, _now = window
    good = payload("safe cached message")
    d.feed.entries = d.session.entries = parse(good)
    d.feed.cache.write_bytes(good)
    assert d.session.choose(lambda text: d.bubble.measure(text)[2]) == "safe cached message"
    bad = payload("W" * 60)
    assert parse(bad)  # Valid wire format and length, but cannot fit in two lines.
    assert not d.bubble.measure("W" * 60)[2]
    reply = Reply(bad)
    d.feed.network = Mock(get=Mock(return_value=reply))
    REAL_START(d.feed)
    reply.finished.emit()
    displayed = d.request()
    assert displayed and d.feed.cache.read_bytes() == good, {
        "displayed": displayed, "cache_preserved": d.feed.cache.read_bytes() == good,
        "all_entries_renderable": [d.bubble.measure("".join(p[0] for p in parts))[2]
                                   for parts in d.session.entries],
    }


def test_no_overlap_with_setup_or_modal_and_resume_has_no_queue(window, app):
    w, d, now = window
    d.session.rng.random = lambda: 0
    d.tick()
    assert d.bubble.isVisible() and list(d.session.shown) == [0]
    w._pages.setCurrentWidget(w.setup_guide)
    app.processEvents()
    assert not d.bubble.isVisible() and not d.request()
    now[0] = 10000
    d.tick()
    w._pages.setCurrentWidget(w._tabs)
    app.processEvents()
    now[0] = 10001
    d.tick()
    assert list(d.session.shown) == [10001]
    assert d.session.last_draw == 10001


def test_click_and_tab_stress_keeps_bounded_timer_and_no_extra_top_level(window, app):
    w, d, _now = window
    before = set(app.topLevelWidgets())
    count = len(d.findChildren(QTimer))
    for index in range(120):
        w._tabs.setCurrentIndex(index % 3)
        assert d.request()
        d.dismiss()
    assert len(d.findChildren(QTimer)) == count == 3
    assert set(app.topLevelWidgets()) == before
    assert not d.feed.started  # Boundary suppressed the original startup transport.


def test_probability_and_relaunch_state_are_local_to_session():
    entries = parse(payload("A", "B"))
    rng = Mock(random=Mock(return_value=0.3))
    state = DialogueSession(entries, rng)
    for now in (0, 120, 240):
        assert state.draw(now)
        state.displayed(str(now), now, automatic=True)
    assert not state.draw(360)
    assert not state.draw(361)
    assert rng.random.call_count == 4
    assert state.draw(600)
    assert list(state.shown) == [120, 240]
    assert DialogueSession(entries, rng).draw(601)


def test_single_sentence_exhaustion_is_bounded_and_silent(window):
    _w, d, _now = window
    d.session.entries = parse(payload("only one"))
    assert d.request()
    d.dismiss()
    before = d.deadline
    for _ in range(100):
        assert not d.request()
    assert not d.bubble.isVisible() and d.deadline is before is None
