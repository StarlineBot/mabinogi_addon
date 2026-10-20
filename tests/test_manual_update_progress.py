"""Exercise the actual manual download screen through MainWindow callbacks."""

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressBar

from mabinogi_addon.system import updater
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui import splash, update_splash


class Owner(QObject):
    _update_progress = Signal(int)
    _update_result = Signal(bool, str)
    _on_update_progress = MainWindow._on_update_progress
    _on_update_result = MainWindow._on_update_result

    def __init__(self):
        super().__init__()
        self._pending_update = {"version": "0.8.0"}
        self.events = []
        self._update_splash = None
        self._force_quit = False

    def hide(self):
        self.events.append("hide")

    def show(self):
        self.events.append("show")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("outcome", ["success", "download_failure", "apply_failure"])
def test_manual_update_keeps_bar_numbers_and_existing_success_failure_lifetime(
    app, monkeypatch, outcome
):
    import threading

    jobs, warnings, quits, applications = [], [], [], []
    monkeypatch.setattr(
        splash,
        "Splash",
        lambda: pytest.fail("manual update used startup dialogue screen"),
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    monkeypatch.setattr(QApplication, "quit", lambda: quits.append(True))

    class Worker:
        def __init__(self, *, target, daemon):
            assert daemon
            jobs.append(target)

        def start(self):
            pass  # Drive the worker at its boundary, with real Qt signal owners/widgets.

    monkeypatch.setattr(threading, "Thread", Worker)
    frames = []
    owner = Owner()

    def download(info, progress_cb):
        for percent in (10, 90):
            progress_cb(percent)
            app.processEvents()
            screen = owner._update_splash
            assert screen.bar.value() == percent
            assert f"{percent}%" in screen.msg.text()
            image = screen.grab().toImage()
            frames.append(bytes(image.constBits()))
        if outcome == "download_failure":
            raise OSError("download failed")
        return Path("new.exe")

    def apply(path):
        applications.append(path)
        if outcome == "apply_failure":
            raise OSError("apply failed")

    monkeypatch.setattr(updater, "download", download)
    monkeypatch.setattr(updater, "apply_update", apply)
    MainWindow._on_update_clicked(owner)
    screen = owner._update_splash
    assert isinstance(screen, update_splash.UpdateSplash)
    assert (
        screen.isVisible()
        and screen.size().width() == 440
        and screen.size().height() == 208
    )
    assert len(screen.findChildren(QProgressBar)) == 1 and screen.bar.value() == 0
    assert owner.events == ["hide"]
    assert len(jobs) == 1
    jobs[0]()
    assert len(frames) == 2 and frames[0] != frames[1]
    assert owner._update_splash is None and not screen.isVisible()
    assert applications == ([] if outcome == "download_failure" else [Path("new.exe")])
    if outcome == "success":
        assert owner._force_quit and quits == [True] and warnings == []
    else:
        assert not owner._force_quit and not quits and len(warnings) == 1
        assert owner.events == ["hide", "show"]
    # All connections must be removed before retry/late worker notifications.
    owner._update_progress.emit(30)
    owner._update_result.emit(True, "")
    assert len(quits) == (1 if outcome == "success" else 0)
    assert len(warnings) == (0 if outcome == "success" else 1)


def test_declined_manual_update_does_not_open_screen_or_start_worker(app, monkeypatch):
    import threading

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )
    monkeypatch.setattr(
        threading, "Thread", lambda **k: pytest.fail("declined update started worker")
    )
    monkeypatch.setattr(
        update_splash,
        "UpdateSplash",
        lambda: pytest.fail("declined update opened screen"),
    )
    owner = Owner()
    MainWindow._on_update_clicked(owner)
    assert owner._update_splash is None and owner.events == []
