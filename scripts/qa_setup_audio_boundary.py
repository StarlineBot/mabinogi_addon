"""Headless QA only: keep real Qt objects, replace native audio construction."""

import pytest
from PySide6.QtCore import QObject


def install(monkeypatch):
    from mabinogi_addon.ui.notifier import SoundNotifier

    def initialize(self, sounds, parent=None, volume=1.0):
        QObject.__init__(self, parent)
        self._sounds = dict(sounds)
        self._player = None
        self._audio = None

    monkeypatch.setattr(SoundNotifier, "__init__", initialize)


@pytest.fixture(autouse=True)
def no_native_audio(monkeypatch):
    install(monkeypatch)
