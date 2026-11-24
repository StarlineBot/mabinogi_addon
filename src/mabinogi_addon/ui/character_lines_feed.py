"""캐릭터 대사 원격 갱신(제작자 잡담과 같은 방식 — 앱 배포 없이 대사를 늘림).

펫이 뜰 때 한 번만 받아 온다(펫을 안 띄우면 통신 0회). 128KB·8초 제한, 형식 검사(character/lines.parse)를
통과한 것만 user_data_dir/character-<폴더>-lines.json에 원자 저장 → 바로 쓰고, 다음 실행부터는 이 파일을 먼저 읽는다.
원격 파일이 없거나(404) 실패하면 내장 대사 그대로.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QIODevice, QObject, QSaveFile, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import paths
from ..character.lines import MAX_BYTES, parse

_log = logging.getLogger(__name__)
BASE_URL = "https://raw.githubusercontent.com/StarlineBot/mabinogi_addon-releases/refs/heads/main/data/characters/"
REMOTE_NAMES = {"다래": "dare-lines.json", "아리아": "aria-lines.json", "이안": "ian-lines.json", "레나": "lena-lines.json"}


def cache_path(folder: str):
    return paths.user_data_dir() / f"character-{folder}-lines.json"


class LinesFeed(QObject):
    updated = Signal(object)  # Lines

    def __init__(self, folder: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.folder = folder
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.buffer = bytearray()
        self.started = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._abort)

    def start(self) -> None:
        name = REMOTE_NAMES.get(self.folder)
        if self.started or name is None:
            return
        self.started = True
        request = QNetworkRequest(QUrl(BASE_URL + name))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(8000)
        try:
            self.reply = self.network.get(request)
        except Exception:  # noqa: BLE001
            _log.debug("캐릭터 대사 요청 시작 실패", exc_info=True)
            return
        self.reply.setReadBufferSize(MAX_BYTES + 1)
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finished)
        self.timer.start(8000)

    def _read(self) -> None:
        if self.reply is None or len(self.buffer) > MAX_BYTES:
            return
        self.buffer.extend(bytes(self.reply.read(MAX_BYTES + 1 - len(self.buffer))))
        if len(self.buffer) > MAX_BYTES:
            self._abort()

    def _abort(self) -> None:
        if self.reply is not None:
            self.reply.abort()

    def _finished(self) -> None:
        reply, self.reply = self.reply, None
        if reply is None:
            return
        self.timer.stop()
        try:
            self.buffer.extend(bytes(reply.read(MAX_BYTES + 1 - len(self.buffer))))
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if reply.error() != QNetworkReply.NetworkError.NoError or status != 200:
                return
            data = bytes(self.buffer)
            lines = parse(data)
            file = QSaveFile(str(cache_path(self.folder)))
            if file.open(QIODevice.OpenModeFlag.WriteOnly):
                if file.write(data) == len(data):
                    file.commit()
                else:
                    file.cancelWriting()
            self.updated.emit(lines)
        except (OSError, ValueError, UnicodeError):
            _log.debug("캐릭터 대사 갱신 실패", exc_info=True)
        finally:
            self.buffer.clear()
            reply.deleteLater()

    def shutdown(self) -> None:
        self.timer.stop()
        self._abort()
