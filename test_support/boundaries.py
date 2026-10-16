"""외부 장치 경계 대체. 별도 종료 프로세스에서도 pytest 없이 사용할 수 있다."""

from contextlib import ExitStack
import socket
import sys
from types import ModuleType
from unittest.mock import patch
import webbrowser

from PySide6.QtCore import QObject, QUrl


class AudioOutput(QObject):
    def setVolume(self, value):
        self._volume = value

    def setMuted(self, value):
        self._muted = value

    def setDevice(self, device):
        self._device = device


class MediaPlayer(QObject):
    def setAudioOutput(self, audio):
        self._output = audio

    def setSource(self, source):
        self._source = source

    def source(self):
        return getattr(self, "_source", QUrl())

    def play(self):
        self._playing = True

    def stop(self):
        self._playing = False


def audio_boundary():
    from PySide6 import QtMultimedia
    from PySide6.QtWidgets import QApplication

    stack = ExitStack()
    stack.enter_context(patch.object(QtMultimedia, "QAudioOutput", AudioOutput))
    stack.enter_context(patch.object(QtMultimedia, "QMediaPlayer", MediaPlayer))
    stack.enter_context(patch.object(QtMultimedia.QMediaDevices, "defaultAudioOutput", lambda: None))
    stack.enter_context(patch.object(QApplication, "beep", lambda: None))
    return stack


class ExternalBoundaries:
    def __init__(self, *, devices=True):
        self.stack = ExitStack()
        self.violations = []
        self.devices = devices

    def deny(self, operation):
        def blocked(*args, **kwargs):
            self.violations.append(operation)
            raise AssertionError(f"test requires an explicit boundary: {operation}")
        return blocked

    def __enter__(self):
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_resolve = socket.getaddrinfo

        def local(host):
            return host in ("localhost", "127.0.0.1", "::1", b"localhost", b"127.0.0.1", None)

        def connect(original):
            def guarded(sock, address):
                if isinstance(address, tuple) and not local(address[0]):
                    return self.deny("external network connection")()
                return original(sock, address)
            return guarded

        def resolve(host, *args, **kwargs):
            if not local(host):
                return self.deny("external DNS lookup")()
            return original_resolve(host, *args, **kwargs)

        self.stack.enter_context(patch.object(socket.socket, "connect", connect(original_connect)))
        self.stack.enter_context(patch.object(socket.socket, "connect_ex", connect(original_connect_ex)))
        self.stack.enter_context(patch.object(socket, "getaddrinfo", resolve))
        self.stack.enter_context(patch.object(webbrowser, "open", self.deny("browser launch")))
        from mabinogi_addon.ui.dialogue_feed import DialogueFeed
        # 실제 Qt 네트워크는 Python socket 대체를 우회하므로 명시적으로 분리한다.
        self.stack.enter_context(patch.object(DialogueFeed, "start", lambda self: None))
        if self.devices:
            import mss
            from mabinogi_addon.system import autostart

            self.stack.enter_context(audio_boundary())
            for name in ("mss", "MSS"):
                self.stack.enter_context(patch.object(mss, name, self.deny("desktop capture")))
            dxcam = ModuleType("dxcam")
            dxcam.create = self.deny("DXGI capture")
            # 전체 모듈 표를 되돌리면 범위 안에서 로드된 NumPy 같은 확장이 제거된다.
            missing = object()
            previous = sys.modules.get("dxcam", missing)
            def restore_dxcam():
                if previous is missing:
                    sys.modules.pop("dxcam", None)
                else:
                    sys.modules["dxcam"] = previous
            self.stack.callback(restore_dxcam)
            sys.modules["dxcam"] = dxcam
            for name in ("_task_enabled", "_reg_enabled"):
                self.stack.enter_context(patch.object(autostart, name, lambda: False))
            for name in ("_task_set", "_task_delete", "_reg_set", "_reg_delete"):
                self.stack.enter_context(patch.object(autostart, name, lambda *a: True))
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)
