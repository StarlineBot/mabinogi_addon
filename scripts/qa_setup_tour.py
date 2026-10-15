"""First-run coachmarks must follow the visible setup page and beta access."""

from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, version
from mabinogi_addon.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(monkeypatch, tmp_path):
    data = {}
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: deepcopy(data))
    def save(value, *a, **k):
        data.clear()
        data.update(deepcopy(value))
    monkeypatch.setattr(config, "_write_local_config", save)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(MainWindow, "_maybe_check_update", lambda *a, **k: None)
    monkeypatch.setattr(version, "__version__", "0.0.0")
    return data


def close(window):
    tour = getattr(window, "_tour", None)
    if tour is not None:
        tour._finish()
    window._force_quit = True
    window.close()
    window.deleteLater()


@pytest.mark.parametrize("logged_in", [False, True])
def test_first_visible_window_uses_setup_tour(app, settings, monkeypatch, logged_in):
    monkeypatch.setattr(config, "load_discord_user", lambda:
                        {"id": "qa", "name": "QA"} if logged_in else None)
    window = MainWindow()
    window._booting = False
    try:
        window.move(0, 0)
        window.show()
        app.processEvents()
        tour = window._tour
        assert tour.isVisible()
        assert window._pages.currentWidget() is window.setup_page
        assert tour._steps[0].target is window.setup_page.selection
        assert len(tour._steps) == (6 if logged_in else 5)
        targets = [step.target for step in tour._steps]
        assert (window.setup_page.run_btn in targets) is logged_in
        assert window.buff_tab.region_btn not in targets
        before = deepcopy(settings)
        out = Path("/tmp/setup-tour-qa")
        out.mkdir(exist_ok=True)
        for index, step in enumerate(tour._steps):
            assert tour._title.text() == step.title
            assert window._pages.currentWidget() is window.setup_page
            assert not window.setup_page.busy
            if index in (0, 2):
                scene = QImage(tour.size(), QImage.Format.Format_ARGB32)
                scene.fill(QColor("#666666"))
                painter = QPainter(scene)
                origin = window.mapToGlobal(QPoint(0, 0)) - tour.geometry().topLeft()
                painter.drawPixmap(origin, window.grab())
                painter.drawPixmap(0, 0, tour.grab())
                painter.end()
                scene.save(str(out / f"{'beta' if logged_in else 'general'}_{index}.png"))
            tour._go_next()
            app.processEvents()
        assert config.load_general_flag("tourShown")
        expected = deepcopy(before)
        expected.setdefault("general", {})["tourShown"] = True
        assert settings == expected
        assert not tour.isVisible()
        assert window._pages.currentWidget() is window.setup_page
    finally:
        close(window)


def test_seen_tour_does_not_repeat_but_can_be_replayed(app, settings, monkeypatch):
    settings["general"] = {"tourShown": True}
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    window = MainWindow()
    window._booting = False
    try:
        window.show()
        app.processEvents()
        assert window._pages.currentWidget() is window.setup_page
        assert getattr(window, "_tour", None) is None
        window._run_tour()
        assert window._tour.isVisible()
        assert window._tour._steps[0].target is window.setup_page.selection
    finally:
        close(window)


def test_skip_setup_uses_existing_buff_tour(app, settings, monkeypatch):
    settings["general"] = {"skipSetup": True}
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    window = MainWindow()
    window._booting = False
    try:
        window.show()
        app.processEvents()
        assert window._pages.currentWidget() is window._tabs
        assert window._tour._steps[0].target is window.buff_tab.region_btn
        assert len(window._tour._steps) == 4
    finally:
        close(window)


def test_settings_replay_can_revisit_new_first_run_setup_guide(app, settings, monkeypatch):
    settings["general"] = {"tourShown": True}
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    window = MainWindow()
    window._booting = False
    try:
        window.show()
        app.processEvents()
        assert window._pages.currentWidget() is window.setup_page
        assert getattr(window, "_tour", None) is None
        window._leave_setup()
        window._tabs.setCurrentIndex(3)
        window.settings_tab.replay_tour.emit()
        assert window._tour.isVisible()
        assert window._tour._steps[0].target is window.setup_page.selection
        assert window._pages.currentWidget() is window.setup_page
    finally:
        close(window)


def test_release_notes_close_before_tour_starts(app, settings, monkeypatch):
    from mabinogi_addon.ui import release_notes

    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    monkeypatch.setattr(version, "__version__", "0.4.67")
    events = []

    class NotesDialog:
        def __init__(self, body, current, parent):
            assert body and current == "0.4.67"
            assert getattr(parent, "_tour", None) is None
            events.append("notes")

        def exec(self):
            events.append("notes_closed")

    monkeypatch.setattr(release_notes, "ReleaseNotesDialog", NotesDialog)
    window = MainWindow()
    original = window._run_tour
    def run():
        assert events == ["notes", "notes_closed"]
        events.append("tour")
        original()
    monkeypatch.setattr(window, "_run_tour", run)
    window._booting = False
    try:
        window.show()
        app.processEvents()
        assert events == ["notes", "notes_closed", "tour"]
        assert window._tour.isVisible()
        assert config.load_last_seen_version() == "0.4.67"
    finally:
        close(window)
