import socket
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from test_support.boundaries import AudioOutput, ExternalBoundaries, MediaPlayer


def test_audio_boundary_keeps_real_notifier_selection_logic(tmp_path):
    from mabinogi_addon.ui.notifier import SoundNotifier

    app = QApplication.instance() or QApplication([])
    clip = tmp_path / "알림.mp3"
    clip.write_bytes(b"test fixture")
    notifier = SoundNotifier({"one": clip}, volume=0.25)
    try:
        assert isinstance(notifier._audio, AudioOutput)
        assert isinstance(notifier._player, MediaPlayer)
        assert notifier._audio._volume == 0.25
        assert not notifier.play("missing")
        assert notifier.play("one")
        assert notifier._player.source() == QUrl.fromLocalFile(str(clip))
        notifier.set_sounds({})
        assert not notifier.play("one")
    finally:
        notifier.deleteLater()
        app.processEvents()


def test_network_guard_records_even_if_product_catches_exception():
    with ExternalBoundaries() as boundary:
        try:
            socket.getaddrinfo("example.invalid", 443)
        except Exception:
            pass
        assert boundary.violations == ["external DNS lookup"]


def test_dialogue_boundary_does_not_initialize_native_network(monkeypatch):
    from mabinogi_addon.ui import dialogue_feed

    app = QApplication.instance() or QApplication([])
    constructed = []
    original = dialogue_feed.QNetworkAccessManager

    def tracked(parent):
        constructed.append(parent)
        return original(parent)

    monkeypatch.setattr(dialogue_feed, "QNetworkAccessManager", tracked)
    with ExternalBoundaries() as boundary:
        feed = dialogue_feed.DialogueFeed()
        try:
            assert not constructed, "isolated feed constructed a native network manager"
            assert feed.entries
            with pytest.raises(AssertionError, match="Qt network request"):
                feed.network.get(None)
            assert boundary.violations == ["Qt network request"]
        finally:
            feed.shutdown()
            feed.deleteLater()
            app.processEvents()


def test_accidental_capture_is_blocked_before_hardware_access():
    import mss

    with ExternalBoundaries() as boundary:
        with pytest.raises(AssertionError, match="desktop capture"):
            mss.mss()
        assert boundary.violations == ["desktop capture"]


def test_capture_exclusion_native_state_requires_explicit_boundary(monkeypatch):
    from mabinogi_addon.system import capture_exclusion

    monkeypatch.setattr(capture_exclusion, "available", lambda: True)
    monkeypatch.setattr(capture_exclusion, "_api", lambda: pytest.fail("unisolated native affinity API"))
    with ExternalBoundaries():
        assert not capture_exclusion.available()
        with capture_exclusion.excluding_windows([1], (0, 0, 10, 10)):
            pass
    assert capture_exclusion.available()


def test_explicit_fake_capture_can_replace_the_boundary(monkeypatch):
    import mss

    sentinel = object()
    monkeypatch.setattr(mss, "mss", lambda: sentinel)
    assert mss.mss() is sentinel


def test_boundary_preserves_native_modules_imported_inside_it():
    script = """
import sys
from types import ModuleType
from test_support.boundaries import ExternalBoundaries

assert 'numpy' not in sys.modules
with ExternalBoundaries():
    import numpy
    import cv2
assert sys.modules['numpy'] is numpy
assert sys.modules['cv2'] is cv2
assert 'dxcam' not in sys.modules
import numpy as again
assert again is numpy

original = ModuleType('dxcam')
sys.modules['dxcam'] = original
with ExternalBoundaries():
    assert sys.modules['dxcam'] is not original
assert sys.modules['dxcam'] is original
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
