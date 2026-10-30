"""문의하기 창 (설정 → 문의하기).

제목·내용을 입력하고 '보내기'를 누르면 제작자 Discord 채널(웹훅)로 전송한다.
네트워크 호출은 데몬 스레드에서 하고, 결과는 Qt 시그널로 UI 스레드에 돌려준다
(위젯은 UI 스레드에서만 만져야 하므로).
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .palette import color
from .. import config
from ..inquiry import send_inquiry
from ..logbuffer import recent_logs
from .toast import show_toast
from .widgets import hint_label

_BUG = "버그 신고"
_CATEGORIES = [_BUG, "기능 요청", "기타"]


class InquiryDialog(QDialog):
    """제목·내용 입력 → Discord 웹훅 전송."""

    _done = Signal(bool, str)  # (성공 여부, 실패 메시지)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("문의하기")
        self.setModal(True)
        self.resize(420, 360)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        # 로그인 상태면 답변을 DM으로 받을 수 있다는 안내(로그인은 설정 탭에서).
        user = config.load_discord_user()
        hint = QLabel(
            f"답변 받을 계정: {user['name']}"
            if user
            else "로그인(설정 탭)하면 답변을 디스코드 DM으로 받을 수 있어요"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color:{color('ok')};" if user else f"color:{color('muted')};"
        )
        v.addWidget(hint)

        v.addWidget(QLabel("분류"))
        self.category = QComboBox()
        self.category.addItems(_CATEGORIES)
        self.category.currentTextChanged.connect(self._on_category)
        v.addWidget(self.category)

        v.addWidget(QLabel("제목"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("문의 제목")
        v.addWidget(self.title_edit)

        v.addWidget(QLabel("내용"))
        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("문의 내용을 적어주세요")
        v.addWidget(self.content_edit, 1)

        # 버그 신고는 진단 로그를 항상 자동 첨부(개발자가 원인 파악에 꼭 필요).
        self._log_hint = hint_label(
            "🛠 진단용 최근 로그가 자동으로 함께 전송돼요(버전·환경 포함)."
        )
        v.addWidget(self._log_hint)
        self._on_category(self.category.currentText())

        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.clicked.connect(self.reject)
        self.send_btn = QPushButton("보내기")
        self.send_btn.setDefault(True)
        self.send_btn.setStyleSheet(
            f"QPushButton {{ background:{color('accent')}; color:{color('on-accent')}; font-weight:600;"
            " padding:4px 14px; }"
        )
        self.send_btn.clicked.connect(self._on_send)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.send_btn)
        v.addLayout(btn_row)

        self._done.connect(self._on_done)

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color('danger')};" if error else f"color:{color('muted')};")

    def _on_category(self, text: str) -> None:
        # 로그 자동 첨부 안내는 '버그 신고'에서만 노출.
        self._log_hint.setVisible(text == _BUG)

    def _on_send(self) -> None:
        title = self.title_edit.text().strip()
        content = self.content_edit.toPlainText().strip()
        if not title or not content:
            self._set_status("제목과 내용을 모두 입력하세요.", error=True)
            return
        webhook = config.get_inquiry_webhook_url()
        if not webhook:
            self._set_status(
                "문의 채널이 설정되지 않았어요(웹훅 미등록).", error=True
            )
            return

        category = self.category.currentText()
        # 버그 신고는 진단 헤더(버전·환경·설정) + 최근 로그를 항상 첨부.
        log_text = None
        if category == _BUG:
            from ..diagnostics import header_text

            log_text = f"{header_text()}\n\n===== 최근 로그 =====\n{recent_logs()}"
        user = config.load_discord_user()
        user_id = user["id"] if user else None

        self.send_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self._set_status("전송 중…")
        threading.Thread(
            target=self._worker,
            args=(webhook, title, content, category, log_text, user_id),
            daemon=True,
        ).start()

    def _worker(
        self, webhook, title, content, category, log_text, user_id
    ) -> None:
        try:
            send_inquiry(
                webhook,
                title,
                content,
                category=category,
                log_text=log_text,
                user_id=user_id,
            )
            self._done.emit(True, "")
        except Exception as exc:  # noqa: BLE001 — 네트워크/응답 오류를 UI에 전달
            self._done.emit(False, str(exc))

    def _on_done(self, ok: bool, msg: str) -> None:
        if ok:
            show_toast("문의", "보내기 완료 — 소중한 의견 감사해요!")
            self.accept()
            return
        self.send_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self._set_status(f"전송 실패: {msg}", error=True)

    def keyPressEvent(self, event) -> None:
        # 내용(QTextEdit)에서 Enter는 줄바꿈이어야 하므로, 전역 Enter=전송은 막는다.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        super().keyPressEvent(event)
