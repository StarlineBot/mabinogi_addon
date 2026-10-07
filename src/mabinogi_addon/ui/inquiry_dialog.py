"""문의하기 창 (설정 → 문의하기).

제목·내용을 입력하고 '보내기'를 누르면 제작자 Discord 채널(웹훅)로 전송한다.
네트워크 호출은 데몬 스레드에서 하고, 결과는 Qt 시그널로 UI 스레드에 돌려준다
(위젯은 UI 스레드에서만 만져야 하므로).
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .. import config, discord_auth
from ..inquiry import send_inquiry
from ..logbuffer import recent_logs
from .toast import show_toast

_BUG = "버그 신고"
_CATEGORIES = [_BUG, "기능 요청", "기타"]


class InquiryDialog(QDialog):
    """제목·내용 입력 → Discord 웹훅 전송."""

    _done = Signal(bool, str)  # (성공 여부, 실패 메시지)
    _login_done = Signal(bool, str, str)  # (성공, user_id, 이름)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("문의하기")
        self.setModal(True)
        self.resize(420, 400)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        # 로그인 행: 로그인하면 답변을 Discord DM으로 받을 수 있다(비로그인=단방향 접수).
        login_row = QHBoxLayout()
        self.login_status = QLabel("")
        self.login_status.setWordWrap(True)
        login_row.addWidget(self.login_status, 1)
        self.login_btn = QPushButton("")
        self.login_btn.clicked.connect(self._on_login_clicked)
        login_row.addWidget(self.login_btn)
        v.addLayout(login_row)
        self._refresh_login()

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

        # 버그 신고일 때만: 진단용 최근 로그를 파일로 첨부(민감하면 끌 수 있음)
        self.attach_log = QCheckBox("오류 로그 첨부 (진단용)")
        self.attach_log.setChecked(True)
        self.attach_log.setToolTip(
            "최근 실행 로그를 파일로 함께 보냅니다. 어떤 상황이었는지 확인에 도움이 됩니다."
        )
        v.addWidget(self.attach_log)
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
            "QPushButton { background:#00B894; color:white; font-weight:600;"
            " padding:4px 14px; }"
        )
        self.send_btn.clicked.connect(self._on_send)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.send_btn)
        v.addLayout(btn_row)

        self._done.connect(self._on_done)
        self._login_done.connect(self._on_login_done)

    # ---- 로그인 ----
    def _refresh_login(self) -> None:
        user = config.load_discord_user()
        if user:
            self.login_status.setText(f"답변 받을 계정: {user['name']}")
            self.login_status.setStyleSheet("color:#2ecc71;")
            self.login_btn.setText("로그아웃")
        else:
            self.login_status.setText("Discord 로그인하면 답변을 DM으로 받을 수 있어요")
            self.login_status.setStyleSheet("color:#8a8f98;")
            self.login_btn.setText("Discord 로그인")

    def _on_login_clicked(self) -> None:
        if config.load_discord_user():
            config.clear_discord_user()
            self._refresh_login()
            return
        self.login_btn.setEnabled(False)
        self.login_status.setText("브라우저에서 Discord 승인을 진행하세요…")
        self.login_status.setStyleSheet("color:#8a8f98;")
        threading.Thread(target=self._login_worker, daemon=True).start()

    def _login_worker(self) -> None:
        try:
            result = discord_auth.login()
        except Exception:  # noqa: BLE001 — 포트 사용 중·네트워크 오류 등
            result = None
        if result:
            self._login_done.emit(True, result[0], result[1])
        else:
            self._login_done.emit(False, "", "")

    def _on_login_done(self, ok: bool, user_id: str, name: str) -> None:
        self.login_btn.setEnabled(True)
        if ok:
            config.save_discord_user(user_id, name)
        else:
            self._set_status("로그인 실패/취소 — 로그인 없이도 보낼 수 있어요.", error=True)
        self._refresh_login()

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setStyleSheet("color:#e74c3c;" if error else "color:#8a8f98;")

    def _on_category(self, text: str) -> None:
        # 로그 첨부 옵션은 '버그 신고'에서만 노출.
        self.attach_log.setVisible(text == _BUG)

    def _on_send(self) -> None:
        title = self.title_edit.text().strip()
        content = self.content_edit.toPlainText().strip()
        if not title or not content:
            self._set_status("제목과 내용을 모두 입력하세요.", error=True)
            return
        webhook = config.get_inquiry_webhook_url()
        if not webhook:
            self._set_status(
                "문의 채널이 설정되지 않았습니다(웹훅 미등록).", error=True
            )
            return

        category = self.category.currentText()
        log_text = (
            recent_logs()
            if category == _BUG and self.attach_log.isChecked()
            else None
        )
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
            show_toast("문의", "보내기 완료 — 소중한 의견 감사합니다!")
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
