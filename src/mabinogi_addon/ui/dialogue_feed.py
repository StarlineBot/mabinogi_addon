"""시작 1회 비동기 수신. 제한 크기/시간/원자 저장, 종료 시 요청 취소."""

import logging

from PySide6.QtCore import QObject, QSaveFile, QIODevice, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import paths
from ..creator_dialogue import MAX_BYTES, RAW_URL, parse, read

_log = logging.getLogger(__name__)


class DialogueFeed(QObject):
    updated = Signal(object)

    def __init__(self, parent=None, *, validate=None):
        super().__init__(parent)
        self.validate = validate or (lambda entries: entries)
        self.entries = ()
        try:
            self.entries = self._accepted(read(paths.resource_dir() / "dialogues.json"))
        except (OSError, ValueError, UnicodeError):
            _log.debug("내장 제작자 대사 읽기 실패", exc_info=True)
        self.cache = None
        try:
            self.cache = paths.user_data_dir() / "creator-dialogues.json"
            self.entries = self._accepted(read(self.cache))
        except (OSError, ValueError, UnicodeError):
            pass
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.started = False
        self.closed = False
        self.buffer = bytearray()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._abort)

    def _accepted(self, entries):
        usable = self.validate(entries)
        if not usable:
            raise ValueError("no renderable dialogue entries")
        return usable

    def start(self):
        if self.started or self.closed:
            return
        self.started = True
        request = QNetworkRequest(QUrl(RAW_URL))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(8000)
        try:
            self.reply = self.network.get(request)
        except Exception:
            _log.debug("제작자 대사 요청 시작 실패", exc_info=True)
            return
        self.reply.setReadBufferSize(MAX_BYTES + 1)
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finished)
        self.timer.start(8000)

    def _read(self):
        if self.reply is None:
            return
        if len(self.buffer) > MAX_BYTES:
            return
        self.buffer.extend(bytes(self.reply.read(MAX_BYTES + 1 - len(self.buffer))))
        if len(self.buffer) > MAX_BYTES:
            self._abort()

    def _abort(self):
        if self.reply is not None:
            self.reply.abort()

    def _finished(self):
        reply = self.reply
        if reply is None:
            return
        self.timer.stop()
        self._read()
        self.reply = None
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if self.closed or reply.error() != QNetworkReply.NetworkError.NoError or status != 200:
                return
            entries = self._accepted(parse(bytes(self.buffer)))
            self.entries = entries
            self.updated.emit(entries)
            if self.cache is not None:
                file = QSaveFile(str(self.cache))
                if file.open(QIODevice.OpenModeFlag.WriteOnly):
                    if file.write(bytes(self.buffer)) == len(self.buffer):
                        file.commit()
                    else:
                        file.cancelWriting()
        except (OSError, ValueError, UnicodeError):
            _log.debug("제작자 대사 갱신 실패", exc_info=True)
        finally:
            self.buffer.clear()
            reply.deleteLater()

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        self._abort()
