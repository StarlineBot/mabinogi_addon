"""Real QtNetwork lifecycle, isolated from UI regressions and public endpoints."""

import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtNetwork import QHostAddress, QNetworkAccessManager, QTcpServer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from mabinogi_addon import paths
from mabinogi_addon.ui import dialogue_feed
from test_support.boundaries import ExternalBoundaries


pytestmark = pytest.mark.windows_integration
START_FEED = dialogue_feed.DialogueFeed.start


def test_real_network_managers_finish_abort_and_destroy_repeatedly(monkeypatch, capsys):
    app = QApplication.instance() or QApplication([])
    server = QTcpServer()
    sockets = []
    requests = []
    payload = (paths.resource_dir() / "dialogues.json").read_bytes()

    def accept():
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            sockets.append(socket)
            received = bytearray()

            def respond(socket=socket, received=received):
                received.extend(bytes(socket.readAll()))
                if b"\r\n\r\n" not in received:
                    return
                requests.append(bytes(received))
                socket.readyRead.disconnect()
                if b"/stall " in received:
                    return
                socket.write(b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                             + str(len(payload)).encode() + b"\r\n\r\n" + payload)
                socket.disconnectFromHost()

            socket.readyRead.connect(respond)

    def wait_for(predicate):
        deadline = time.monotonic() + 5
        while not predicate():
            assert time.monotonic() < deadline, "Qt network operation did not complete"
            loop = QEventLoop()
            QTimer.singleShot(5, loop.quit)
            loop.exec()

    server.newConnection.connect(accept)
    # Opt into the real transport explicitly; all other external boundaries remain.
    monkeypatch.setattr(dialogue_feed, "QNetworkAccessManager", QNetworkAccessManager)
    assert server.listen(QHostAddress.SpecialAddress.LocalHost, 0), server.errorString()
    try:
        for index in range(200):
            cancel = index % 2 == 1
            route = "stall" if cancel else "ok"
            with capsys.disabled():
                print(f"QT_NETWORK_LIFECYCLE {index + 1}/200: {route}", flush=True)
            monkeypatch.setattr(dialogue_feed, "RAW_URL",
                                f"http://127.0.0.1:{server.serverPort()}/{route}")
            feed = dialogue_feed.DialogueFeed()
            manager = feed.network
            updated = QSignalSpy(feed.updated)
            reply = None
            try:
                assert isinstance(manager, QNetworkAccessManager)
                START_FEED(feed)
                reply = feed.reply
                assert reply is not None
                wait_for(lambda: len(requests) == index + 1)
                if cancel:
                    feed.shutdown()
                wait_for(lambda: feed.reply is None)
                assert not feed.timer.isActive()
                assert not feed.buffer
                assert updated.count() == (0 if cancel else 1)
                if not cancel:
                    assert feed.cache.read_bytes() == payload
                feed.shutdown()
                feed.shutdown()
            finally:
                feed.shutdown()
                feed.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                app.processEvents()
            assert not isValid(manager)
            assert not isValid(reply)
            for socket in sockets:
                socket.abort()
                socket.deleteLater()
            sockets.clear()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert len(requests) == 200
    finally:
        for socket in sockets:
            socket.abort()
        server.close()
        server.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_real_network_manager_in_repeated_main_window_lifecycle(monkeypatch, capsys):
    from mabinogi_addon.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    with ExternalBoundaries() as boundary:
        monkeypatch.setattr(dialogue_feed, "QNetworkAccessManager", QNetworkAccessManager)
        for index in range(20):
            with capsys.disabled():
                print(f"QT_NETWORK_MAIN_WINDOW {index + 1}/20", flush=True)
            before = set(app.topLevelWidgets())
            window = MainWindow()
            manager = window.creator_dialogue.feed.network
            try:
                assert isinstance(manager, QNetworkAccessManager)
                window._post_show_done = True
                for timer in window.findChildren(QTimer):
                    timer.stop()
                window.show()
                app.processEvents()
            finally:
                window._force_quit = True
                window.close()
                assert window.creator_dialogue.closed
                assert not window.creator_dialogue.feed.timer.isActive()
                for widget in set(app.topLevelWidgets()) - before:
                    widget.close()
                    widget.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                app.processEvents()
            assert not isValid(manager)
            assert not isValid(window)
        assert not boundary.violations
