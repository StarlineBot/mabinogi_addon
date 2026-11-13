"""잡담 소리를 누르는(뜨는) 순간 바로(0.48.0, 사용자 요청 11-14) — 같은 파일은 다시 열지 않기·재생기 미리 준비·앞 무음 잘라 냄."""
import os
import re
import shutil
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import paths
from mabinogi_addon.ui import notifier


class FakePlayer:
    def __init__(self):
        self.calls = []

    def setSource(self, url):
        self.calls.append(("source", url.toLocalFile()))

    def setPosition(self, ms):
        self.calls.append(("position", ms))

    def play(self):
        self.calls.append(("play",))

    def stop(self):
        self.calls.append(("stop",))


def test_same_source_opens_once_then_rewinds(tmp_path):
    QApplication.instance() or QApplication([])
    a, b = tmp_path / "a.mp3", tmp_path / "b.mp3"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    n = notifier.SoundNotifier({"a": a, "b": b})
    n._player = FakePlayer()
    assert n.prepare("a")
    for _ in range(3):
        assert n.play("a")
    assert [c for c in n._player.calls if c[0] == "source"] == [("source", str(a))]  # setSource 1번
    assert n._player.calls[1:] == [("position", 0), ("play",)] * 3  # 처음 위치로 돌려 재생
    n.play("b")
    n.play("a")
    assert [c[1] for c in n._player.calls if c[0] == "source"] == [str(a), str(b), str(a)]  # 다른 파일이면 바꿔 엶


def test_dialogue_player_is_prepared_when_sound_on(monkeypatch):
    QApplication.instance() or QApplication([])
    from mabinogi_addon import config
    from mabinogi_addon.ui.main_window import MainWindow
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    prepared = []
    real = notifier.SoundNotifier.prepare
    monkeypatch.setattr(notifier.SoundNotifier, "prepare", lambda self, key: prepared.append(key) or real(self, key))
    config.save_general_flag("skipSetup", True)
    w = MainWindow()
    try:
        d = w.creator_dialogue
        tab = w.settings_tab
        tab.dialogue_sound_enabled.setChecked(False)
        d._notifier = None
        tab.dialogue_enabled.setChecked(True)
        assert d._notifier is None  # 잡담 소리가 꺼져 있으면 만들지 않음
        tab.dialogue_sound_enabled.setChecked(True)  # 소리를 켜면 그때 미리
        assert d._notifier is not None and prepared == ["dialogue"]
        assert d._notifier._player.source_sets == 1  # 파일을 한 번 열어 둠(가짜 재생기 — test_support.boundaries)
        d._notifier = None
        d.started = False
        d.start()  # 앱 시작(잡담·소리 켜짐)에도 미리
        assert d._notifier is not None
    finally:
        w._force_quit = True
        w.close()


def test_request_logs_ms_until_sound(monkeypatch, caplog):
    import logging
    QApplication.instance() or QApplication([])
    from mabinogi_addon import config
    from mabinogi_addon.ui.main_window import MainWindow
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    config.save_general_flag("skipSetup", True)
    w = MainWindow()
    try:
        w._hide_home()
        w.show()
        QApplication.instance().processEvents()
        d = w.creator_dialogue
        d.visibility = lambda *a: True
        order = []
        d.sound = lambda text: order.append(("sound", d.bubble.isVisible())) or True
        w.settings_tab.dialogue_sound_enabled.setChecked(True)
        caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.creator_dialogue")
        assert d.request()
        assert order == [("sound", True)]  # 말풍선을 띄운 바로 그 자리에서
        line = [r.getMessage() for r in caplog.records if r.getMessage().startswith("제작자 잡담 요청")][-1]
        assert re.search(r"소리 요청까지=\d+\.\dms", line)
    finally:
        w._force_quit = True
        w.close()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 없음")
def test_dialogue_sound_leading_silence_trimmed():
    path = paths.resource_dir() / "sounds" / "제작자 잡담.mp3"
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "silencedetect=n=-40dB:d=0.005",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"silence_start: 0\b.*?silence_end: ([\d.]+)", out, re.S)
    lead = float(m.group(1)) if m else 0.0
    assert lead <= 0.02
