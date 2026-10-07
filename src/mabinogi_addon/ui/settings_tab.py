"""설정 탭 (기획서 5.3).

일반 설정 + 게임 창 인식. (오버레이 배율은 각 버프/디버프 탭으로 이동, 알림음은
버프별 등록 사운드로 재생 — TTS 미사용.) 아직 설정 파일과 연결 안 한 항목도 있다.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config, discord_auth
from ..system.window_watcher import WindowWatcher
from .widgets import hint_label

_ASSETS = Path(__file__).resolve().parents[1] / "assets"
PROFILE_IMAGE = _ASSETS / "profile.png"  # 제작자 프로필(없으면 로고로 폴백)
LOGO_IMAGE = _ASSETS / "logo.png"


def _circular(path: Path, size: int) -> QPixmap | None:
    """이미지를 정사각 중앙 크롭 후 원형으로 잘라 size×size 픽스맵으로."""
    src = QPixmap(str(path))
    if src.isNull():
        return None
    src = src.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = (src.width() - size) // 2
    y = (src.height() - size) // 2
    src = src.copy(x, y, size, size)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, size, size)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, src)
    painter.end()
    return out


def _checked(text: str, on: bool = True) -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(on)
    return box


# general 설정 키 ↔ 체크박스 라벨
_TRAY_MINIMIZE = "minimizeToTray"
_TRAY_START = "startInTray"


class SettingsTab(QWidget):
    # 로그인 상태가 바뀌면 메인이 받아 기능 노출(게이팅)을 갱신할 수 있게 알린다.
    login_changed = Signal()
    _login_done = Signal(bool, str, str)  # (성공, user_id, 이름)

    def __init__(self, watcher: WindowWatcher) -> None:
        super().__init__()
        self._watcher = watcher
        self._detect_count = 0
        self._detect_timer: QTimer | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(12)
        v.addWidget(self._creator_header())
        v.addWidget(self._inquiry_button())
        v.addWidget(self._discord_group())
        v.addWidget(self._general_group())
        v.addWidget(self._game_group())
        v.addStretch(1)
        self._login_done.connect(self._on_login_done)

    # ---- Discord 계정(로그인) ----
    def _discord_group(self) -> QGroupBox:
        box = QGroupBox("Discord 계정")
        v = QVBoxLayout(box)
        self._login_status = hint_label("")
        v.addWidget(self._login_status)
        row = QHBoxLayout()
        self._login_btn = QPushButton("")
        self._login_btn.clicked.connect(self._on_login_clicked)
        row.addWidget(self._login_btn)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(
            hint_label("로그인하면 문의 답변을 DM으로 받을 수 있어요.")
        )
        self._refresh_login()
        return box

    def _refresh_login(self) -> None:
        user = config.load_discord_user()
        if user:
            self._login_status.setText(f"로그인됨: {user['name']}")
            self._login_status.setStyleSheet("color:#2ecc71;")
            self._login_btn.setText("로그아웃")
        else:
            self._login_status.setText("로그인하지 않음")
            self._login_status.setStyleSheet("color:#8a8f98;")
            self._login_btn.setText("Discord 로그인")

    def _on_login_clicked(self) -> None:
        if config.load_discord_user():
            config.clear_discord_user()
            self._refresh_login()
            self.login_changed.emit()
            return
        self._login_btn.setEnabled(False)
        self._login_status.setText("브라우저에서 Discord 승인을 진행하세요…")
        self._login_status.setStyleSheet("color:#8a8f98;")
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
        self._login_btn.setEnabled(True)
        if ok:
            config.save_discord_user(user_id, name)
        else:
            self._login_status.setText("로그인 실패/취소 — 다시 시도하세요.")
            self._login_status.setStyleSheet("color:#e67e22;")
        self._refresh_login()
        self.login_changed.emit()

    # ---- 제작자 헤더 + 문의하기 ----
    def _creator_header(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(4, 4, 4, 0)
        row.setSpacing(10)

        avatar = QLabel()
        avatar.setFixedSize(48, 48)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = _circular(PROFILE_IMAGE, 48) or _circular(LOGO_IMAGE, 48)
        if pm is not None:
            avatar.setPixmap(pm)
        else:
            avatar.setText("👤")
            avatar.setStyleSheet("font-size:28px;")
        row.addWidget(avatar)

        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(f"제작자: {config.CREATOR_NAME}")
        name.setStyleSheet("font-size:15px; font-weight:700;")
        desc = QLabel(
            "개인개발용 마비노기 애드온 입니다.\n"
            "건의사항이나 필요한 기능은 아래 문의하기 버튼 혹은 "
            "하프서버 Starline 에게 문의해 주세요."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#8a8f98; font-size:11px;")
        col.addWidget(name)
        col.addWidget(desc)
        row.addLayout(col, 1)
        return box

    def _inquiry_button(self) -> QPushButton:
        btn = QPushButton("문의하기")
        btn.setToolTip("제작자에게 제목·내용으로 문의를 보냅니다")
        btn.clicked.connect(self._open_inquiry)
        return btn

    def _open_inquiry(self) -> None:
        from .inquiry_dialog import InquiryDialog

        InquiryDialog(self).exec()

    def _general_group(self) -> QGroupBox:
        box = QGroupBox("일반")
        v = QVBoxLayout(box)
        v.addWidget(_checked("Windows 시작 시 자동 실행"))  # (미연결)

        self._start_tray = _checked(
            "실행 시 트레이로 시작", config.load_general_flag(_TRAY_START, False)
        )
        self._start_tray.toggled.connect(
            lambda on: config.save_general_flag(_TRAY_START, on)
        )
        v.addWidget(self._start_tray)

        self._min_tray = _checked(
            "닫기(X) 버튼을 누르면 트레이로 최소화",
            config.load_general_flag(_TRAY_MINIMIZE, True),
        )
        self._min_tray.toggled.connect(
            lambda on: config.save_general_flag(_TRAY_MINIMIZE, on)
        )
        v.addWidget(self._min_tray)
        return box

    # ---- 게임 창 인식(포그라운드 판정 대상) ----
    def _game_group(self) -> QGroupBox:
        box = QGroupBox("게임 창 인식")
        v = QVBoxLayout(box)
        self._game_hint = hint_label("")
        self._update_game_label()
        v.addWidget(self._game_hint)

        row = QHBoxLayout()
        self._detect_btn = QPushButton("게임 창 자동 찾기")
        self._detect_btn.clicked.connect(self._start_detect)
        row.addWidget(self._detect_btn)
        row.addStretch(1)
        v.addLayout(row)

        v.addWidget(
            hint_label(
                "버튼을 누르고 3초 안에 마비노기 창을 클릭해 맨 앞으로 두세요.\n"
                "제목이 아니라 '실행파일'로 인식 → 이름이 같은 폴더 창 등과 헷갈리지 않습니다."
            )
        )
        return box

    def _update_game_label(self) -> None:
        exe = config.load_game_exe()
        if exe:
            self._game_hint.setText(f"인식 대상(실행파일): {exe}")
            self._game_hint.setStyleSheet("color:#2ecc71;")
        else:
            self._game_hint.setText(
                "미등록 — 창 제목에 '마비노기'가 들어가면 게임으로 판정(폴더 창 등 오인 가능)"
            )
            self._game_hint.setStyleSheet("color:#8a8f98;")

    def _start_detect(self) -> None:
        self._detect_count = 3
        self._detect_btn.setEnabled(False)
        self._detect_btn.setText("3초 후 현재 창 등록…")
        self._detect_timer = QTimer(self)
        self._detect_timer.setInterval(1000)
        self._detect_timer.timeout.connect(self._tick_detect)
        self._detect_timer.start()

    def _tick_detect(self) -> None:
        self._detect_count -= 1
        if self._detect_count > 0:
            self._detect_btn.setText(f"{self._detect_count}초 후 현재 창 등록…")
            return
        if self._detect_timer is not None:
            self._detect_timer.stop()
        _title, exe = self._watcher.foreground_info()
        self._detect_btn.setEnabled(True)
        self._detect_btn.setText("게임 창 자동 찾기")
        if exe:
            config.save_game_exe(exe)
            self._watcher.set_game_exe(exe)
            self._update_game_label()
        else:
            self._game_hint.setText("자동 찾기 실패(창 정보를 못 읽음). Windows에서 시도하세요.")
            self._game_hint.setStyleSheet("color:#e67e22;")
