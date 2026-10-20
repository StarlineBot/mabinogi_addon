"""Exercise the actual manual download screen through MainWindow callbacks."""

from hashlib import sha256
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QFontInfo, QImage
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressBar

from mabinogi_addon.system import updater
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui import splash, update_splash


def render_frame(screen):
    """Paint the actual widget synchronously, independent of native grab caches."""
    ratio = screen.devicePixelRatioF()
    image = QImage(screen.size() * ratio, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)
    screen.render(image)
    return image


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
def test_manual_update_shares_layout_numbers_and_existing_success_failure_lifetime(
    app, monkeypatch, outcome
):
    import threading

    jobs, warnings, quits, applications = [], [], [], []
    monkeypatch.setattr(
        splash.Splash,
        "_choose",
        lambda self: pytest.fail("manual update selected dialogue"),
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
    frames, diagnostics = [], []
    owner = Owner()

    def download(info, progress_cb):
        for percent in (0, 10, 37, 90, 100):
            progress_cb(percent)
            app.processEvents()
            screen = owner._update_splash
            assert screen.msg.text() == f"새 버전 v0.8.0 받는 중 {percent}%"
            assert screen.geometry() == geometry
            assert not screen.findChildren(QTimer)
            image = render_frame(screen)
            frame = bytes(image.constBits())
            frames.append(sha256(frame).hexdigest())
            diagnostics.append(dict(percent=percent, text=screen.msg.text(),
                                    sha256=frames[-1],
                                    size=[image.width(), image.height()],
                                    dpr=image.devicePixelRatio(),
                                    font_pixels=screen.msg.font().pixelSize(),
                                    resolved_font=QFontInfo(screen.msg.font()).family()))
        if outcome == "download_failure":
            raise OSError("download failed")
        return Path("new.exe")

    def apply(path):
        assert screen.msg.text() == "업데이트 적용 중"
        owner._update_progress.emit(90)
        assert screen.msg.text() == "업데이트 적용 중"
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
        and screen.size().height() == 240
    )
    assert isinstance(screen, splash.Splash)
    assert not screen.findChildren(QProgressBar)
    assert not screen.findChildren(QTimer) and screen._timer is None
    assert screen.msg.text() == "새 버전 v0.8.0 받는 중 0%"
    assert screen._mode == "status"
    geometry = screen.geometry()
    assert owner.events == ["hide"]
    assert len(jobs) == 1
    jobs[0]()
    assert len(frames) == 5 and len(set(frames)) == 5, diagnostics
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
    closed_text = screen.msg.text()
    screen.download_progress(37)
    screen.step(37, "late")
    assert not screen.isVisible() and screen.msg.text() == closed_text
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


def test_real_worker_dispatch_and_failure_retry(app, monkeypatch):
    import threading
    import time

    from PySide6.QtTest import QTest

    owner = Owner()
    workers, displays, warnings, applied = [], [], [], []
    real_thread = threading.Thread
    original_show = splash.Splash._show_text

    def show(screen, text):
        assert QThread.isMainThread()
        displays.append(text)
        original_show(screen, text)

    def worker(**kwargs):
        thread = real_thread(**kwargs)
        workers.append(thread)
        return thread

    def download(info, progress_cb):
        for percent in (0, 10, 37, 90, 100):
            progress_cb(percent)
        return Path("new.exe")

    def apply(path):
        # A synchronous GUI dispatch must have completed before actual file apply.
        assert displays[-1] == "업데이트 적용 중"
        applied.append(path)
        raise OSError("retryable apply failure")

    monkeypatch.setattr(splash.Splash, "_show_text", show)
    monkeypatch.setattr(threading, "Thread", worker)
    monkeypatch.setattr(updater, "download", download)
    monkeypatch.setattr(updater, "apply_update", apply)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    screens = []
    for attempt in range(2):
        owner._pending_update = {"version": f"0.8.{attempt}"}
        MainWindow._on_update_clicked(owner)
        screen = owner._update_splash
        screens.append(screen)
        # Repeated clicks while active must not create another worker/window.
        MainWindow._on_update_clicked(owner)
        assert len(workers) == attempt + 1
        deadline = time.monotonic() + 5
        while (
            workers[-1].is_alive() or owner._update_splash is not None
        ) and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(1)
        workers[-1].join(timeout=0)
        assert not workers[-1].is_alive()
        assert owner._update_splash is None
        assert len(warnings) == attempt + 1
        assert not screen.isVisible() and not screen.findChildren(QTimer)
        assert f"새 버전 v0.8.{attempt} 받는 중 37%" in displays
        previous = list(displays)
        owner._update_progress.emit(37)
        app.processEvents()
        assert displays == previous
    assert screens[0] is not screens[1]
    assert applied == [Path("new.exe")] * 2
    assert owner.events == ["hide", "show"] * 2


def test_status_only_cannot_resume_dialogue_or_reopen_after_close(app):
    screen = update_splash.UpdateSplash("0.8.0")
    try:
        screen.step(1)
        screen._tick()
        assert screen.msg.text() == "새 버전 v0.8.0 받는 중 0%"
        assert screen._mode == "status" and not screen.findChildren(QTimer)
        screen.close()
        screen.prepare_apply()
        screen.download_progress(90)
        assert screen._mode == "closed" and not screen.isVisible()
        assert screen.msg.text() == "새 버전 v0.8.0 받는 중 0%"
    finally:
        screen.close()


@pytest.mark.parametrize("family", ["Malgun Gothic", "sans-serif"])
def test_long_target_version_fits_fixed_status_slot(app, family):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QFontMetrics

    version = "0.8.0-beta.20261020+0123456789abcdef0123456789abcdef"
    screen = update_splash.UpdateSplash(version)
    try:
        font = QFont(family)
        font.setPixelSize(13)
        screen.msg.setFont(font)
        geometry = screen.geometry()
        for text in (f"새 버전 v{version} 받는 중 100%", "업데이트 적용 중"):
            screen.step(100, text)
            bounds = QFontMetrics(screen.msg.font()).boundingRect(
                screen.msg.rect(), int(Qt.TextFlag.TextWordWrap), text
            )
            diagnostics = dict(text=text, requested_font=family,
                               resolved_font=QFontInfo(screen.msg.font()).family(),
                               font_pixels=screen.msg.font().pixelSize(),
                               bounds=[bounds.width(), bounds.height()],
                               slot=[screen.msg.width(), screen.msg.height()],
                               dpr=screen.devicePixelRatioF())
            assert bounds.width() <= screen.msg.width(), diagnostics
            assert bounds.height() <= screen.msg.height(), diagnostics
            assert screen.msg.text() == text
            assert screen.geometry() == geometry
        assert screen.msg.font().pixelSize() == 13, diagnostics
    finally:
        screen.close()
