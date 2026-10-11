"""설정 탭 (기획서 5.3).

일반 설정 + 게임 창 인식. (오버레이 배율은 각 버프/디버프 탭으로 이동, 알림음은
버프별 등록 사운드로 재생 — TTS 미사용.) 아직 설정 파일과 연결 안 한 항목도 있다.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("mabinogi_addon.discord")
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config, discord_auth, paths
from ..system.window_watcher import WindowWatcher
from .widgets import checkbox, hint_label

# 테마 스와치 색(동그라미). 시스템=반반 그라데이션(라이트/다크 자동).
_THEME_SWATCH = {
    "system": (
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f4f4f5, "
        "stop:0.5 #f4f4f5, stop:0.5 #2b2d31, stop:1 #2b2d31)"
    ),
    "light": "#f4f4f5",
    "dark": "#2b2d31",
}
_THEME_ACCENT = "#00C9A2"  # 다크 테마 강조(민트)

# 번들 경로 사용(exe=_MEIPASS/assets). __file__ 기준은 frozen에서 어긋나 이미지가 안 뜬다.
_ASSETS = paths.resource_dir()
PROFILE_IMAGE = _ASSETS / "profile.png"  # 제작자 프로필(없으면 로고로 폴백)
LOGO_IMAGE = _ASSETS / "logo.png"


def _circular(
    path: Path,
    size: int,
    border_width: int = 0,
    border_color: str | None = None,
) -> QPixmap | None:
    """이미지를 정사각 중앙 크롭 후 원형으로 잘라 size×size 픽스맵으로.

    border_width>0 이면 그 두께·색으로 원 테두리를 그린다(테두리는 안쪽으로 그려
    size 밖으로 새지 않게 함).
    """
    src = QPixmap(str(path))
    if src.isNull():
        return None
    # 테두리 두께만큼 이미지를 안으로 들여, 테두리가 이미지를 가리지 않게 한다.
    inner = max(1, size - 2 * border_width)
    src = src.scaled(
        inner, inner,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = (src.width() - inner) // 2
    y = (src.height() - inner) // 2
    src = src.copy(x, y, inner, inner)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(border_width, border_width, inner, inner)
    painter.setClipPath(clip)
    painter.drawPixmap(border_width, border_width, src)
    if border_width > 0 and border_color:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPen

        painter.setClipping(False)
        pen = QPen(QColor(border_color))
        pen.setWidth(border_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        half = border_width / 2.0
        painter.drawEllipse(QRectF(half, half, size - border_width, size - border_width))
    painter.end()
    return out


def _checked(text: str, on: bool = True) -> QCheckBox:
    box = checkbox(text)
    box.setChecked(on)
    return box


# general 설정 키 ↔ 체크박스 라벨
_TRAY_MINIMIZE = "minimizeToTray"
_GRID_SNAP = "gridSnap"
_GRID_SIZES = [8, 16, 24, 32, 48, 64]  # 격자 크기 선택지(px)
_TRAY_START = "startInTray"
# 토스트 알림 위치 선택지(라벨, config 모서리 코드)
_TOAST_CORNER_CHOICES = [
    ("우측 하단", "br"),
    ("우측 상단", "tr"),
    ("좌측 하단", "bl"),
    ("좌측 상단", "tl"),
]


class _LoginThread(QThread):
    """디스코드 로그인(브라우저 콜백 대기)을 백그라운드로. QThread라야 done 시그널이
    UI 스레드로 확실히 전달된다(일반 threading.Thread는 전달이 안 됐다)."""

    done = Signal(bool, str, str)  # (성공, user_id, 이름)

    def run(self) -> None:
        try:
            result = discord_auth.login()
        except Exception:  # noqa: BLE001 — 포트 사용 중·네트워크 오류 등
            result = None
        if result:
            _log.info("워커: login() 반환 성공 → UI로 전달")
            self.done.emit(True, result[0], result[1])
        else:
            _log.info("워커: login() 반환 실패/None → UI로 전달")
            self.done.emit(False, "", "")


class _ConfigExportThread(QThread):
    """설정을 디스코드 릴레이 웹훅으로 전송(백그라운드)."""

    done = Signal(bool, str)  # (성공, 메시지)

    def __init__(self, webhook: str, user: dict, payload: bytes, parent=None) -> None:
        super().__init__(parent)
        self._webhook = webhook
        self._user = user
        self._payload = payload

    def run(self) -> None:
        from .. import settings_sync

        try:
            settings_sync.send_config_backup(
                self._webhook,
                self._user["id"],
                self._payload,
                username=self._user.get("name"),
            )
            self.done.emit(True, "설정을 DM으로 보냈습니다. 디스코드를 확인하세요.")
        except Exception as exc:  # noqa: BLE001 — 네트워크/웹훅 오류 UI로
            self.done.emit(False, f"전송 실패: {exc}")


class SettingsTab(QWidget):
    # 로그인 상태가 바뀌면 메인이 받아 기능 노출(게이팅)을 갱신할 수 있게 알린다.
    login_changed = Signal()
    # 설정 가져오기/초기화 직후 메인에 알려, 종료 시 낡은 상태로 덮어쓰지 않게 한다.
    config_imported = Signal()
    # 알림 목소리 팩 변경 → 메인이 실행 중 재생기들을 새 팩으로 갱신(바로 적용).
    voice_pack_changed = Signal()
    # '사용법 투어 다시 보기' → 메인이 온보딩 투어를 다시 실행.
    replay_tour = Signal()
    theme_changed = Signal()  # 테마 변경 → 메인이 탭 등 테마색 재적용

    def __init__(self, watcher: WindowWatcher) -> None:
        super().__init__()
        self._watcher = watcher
        self._detect_count = 0
        self._detect_timer: QTimer | None = None
        self._login_thread: _LoginThread | None = None
        self._export_thread: _ConfigExportThread | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(12)
        v.addWidget(self._creator_header())
        v.addWidget(self._inquiry_button())
        v.addWidget(self._diag_button())
        v.addWidget(self._discord_group())
        v.addWidget(self._backup_group())
        v.addWidget(self._general_group())
        v.addWidget(self._theme_group())
        v.addWidget(self._game_group())
        v.addStretch(1)

    def _backup_group(self) -> QGroupBox:
        box = QGroupBox("설정 백업")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        export_btn = QPushButton("설정 내보내기")
        export_btn.clicked.connect(self._on_export_config)
        import_btn = QPushButton("설정 가져오기")
        import_btn.clicked.connect(self._on_import_config)
        row.addWidget(export_btn)
        row.addWidget(import_btn)
        v.addLayout(row)
        v.addWidget(
            hint_label(
                "설정과 등록한 버프·디버프 아이콘까지 하나의 zip으로 저장/불러옵니다"
                "(다른 PC로 이동·백업).\n가져오면 앱을 다시 시작해 전부 반영합니다."
            )
        )

        # 디스코드로 내보내기: 봇이 백업 파일을 내 DM으로 보내준다(로그인 필요).
        self._dm_export_btn = QPushButton("디스코드로 내보내기 (DM)")
        self._dm_export_btn.clicked.connect(self._on_export_discord)
        v.addWidget(self._dm_export_btn)
        v.addWidget(
            hint_label(
                "로그인한 계정으로 섯다라인 봇이 백업 파일을 DM으로 보냅니다.\n"
                "다른 PC에서 그 파일을 받아 '설정 가져오기'로 적용하세요."
            )
        )

        reset_btn = QPushButton("설정 초기화")
        reset_btn.clicked.connect(self._on_reset_config)
        v.addWidget(reset_btn)
        v.addWidget(
            hint_label("모든 설정을 지우고 처음 상태로 되돌립니다(되돌릴 수 없음).")
        )
        self._refresh_dm_export()
        return box

    def _refresh_dm_export(self) -> None:
        """로그인 상태에 따라 'DM 내보내기' 버튼 활성/비활성."""
        if hasattr(self, "_dm_export_btn"):
            logged_in = config.load_discord_user() is not None
            self._dm_export_btn.setEnabled(logged_in)
            self._dm_export_btn.setToolTip(
                "" if logged_in else "먼저 Discord 로그인이 필요합니다"
            )

    def _on_export_discord(self) -> None:
        user = config.load_discord_user()
        if user is None:
            QMessageBox.information(
                self, "디스코드로 내보내기", "먼저 Discord 로그인을 해주세요."
            )
            return
        webhook = config.get_config_webhook_url()
        if not webhook:
            QMessageBox.warning(
                self, "디스코드로 내보내기", "설정 백업 채널이 구성되지 않았습니다."
            )
            return
        payload = config.export_bundle_bytes()
        self._dm_export_btn.setEnabled(False)
        self._dm_export_btn.setText("보내는 중…")
        self._export_thread = _ConfigExportThread(webhook, user, payload, self)
        self._export_thread.done.connect(self._on_dm_result)
        self._export_thread.start()

    def _on_dm_result(self, ok: bool, msg: str) -> None:
        self._dm_export_btn.setText("디스코드로 내보내기 (DM)")
        self._refresh_dm_export()
        if ok:
            QMessageBox.information(self, "디스코드로 내보내기", msg)
        else:
            QMessageBox.warning(self, "디스코드로 내보내기", msg)

    def _on_export_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "설정 내보내기",
            "섯다라인_애드온_설정.zip",
            "설정 백업 (*.zip)",
        )
        if not path:
            return
        try:
            config.export_bundle(Path(path))
        except OSError as exc:
            QMessageBox.warning(self, "설정 내보내기", f"저장 실패: {exc}")
            return
        QMessageBox.information(self, "설정 내보내기", "설정을 저장했습니다.")

    def _on_import_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "설정 가져오기", "", "설정 백업 (*.zip *.json)"
        )
        if not path:
            return
        try:
            config.import_bundle(Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "설정 가져오기", f"불러오기 실패: {exc}")
            return
        self._offer_restart("설정 가져오기", "설정을 가져왔습니다.")

    def _on_reset_config(self) -> None:
        if (
            QMessageBox.question(
                self,
                "설정 초기화",
                "모든 설정을 지우고 처음 상태로 되돌립니다.\n계속할까요?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            config.reset_config()
        except OSError as exc:
            QMessageBox.warning(self, "설정 초기화", f"초기화 실패: {exc}")
            return
        self._offer_restart("설정 초기화", "설정을 초기화했습니다.")

    def _offer_restart(self, title: str, msg: str) -> None:
        """가져오기/초기화 후: 종료 시 덮어쓰기 방지 신호를 보내고, 재실행을 안내한다.

        자동 재시작은 하지 않는다(onefile exe 자가 재실행이 임시폴더 충돌로 깨짐).
        대신 사용자가 직접 '완전히 종료 후 다시 실행'하면 바뀐 설정·자산이 반영된다.
        """
        self.config_imported.emit()
        QMessageBox.information(
            self,
            title,
            f"{msg}\n\n전부 반영하려면 앱을 완전히 종료한 뒤 다시 실행하세요.\n"
            "(트레이로 최소화가 아니라 트레이 아이콘 → '종료' 후 재실행)\n"
            "지금 창을 닫아도 가져온 설정은 안전하게 유지됩니다.",
        )

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
            hint_label(
                "로그인하면 문의 답변을 DM으로 받을 수 있어요.\n"
                "또한 베타 기능(예: 체력바 오버레이)과 디버그 기능을 사용할 수 있습니다."
            )
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
        self._refresh_dm_export()  # 로그인 상태에 맞춰 DM 내보내기 버튼 갱신
        self._refresh_diag()  # 진단 스냅샷(디버깅)도 로그인 시에만 노출

    def _on_login_clicked(self) -> None:
        if config.load_discord_user():
            config.clear_discord_user()
            self._refresh_login()
            self.login_changed.emit()
            return
        self._login_btn.setEnabled(False)
        self._login_status.setText("브라우저에서 Discord 승인을 진행하세요…")
        self._login_status.setStyleSheet("color:#8a8f98;")
        self._login_thread = _LoginThread(self)
        self._login_thread.done.connect(self._on_login_done)
        self._login_thread.start()

    def _on_login_done(self, ok: bool, user_id: str, name: str) -> None:
        _log.info("UI 로그인 결과 수신: ok=%s id=%s", ok, user_id)
        self._login_btn.setEnabled(True)
        if ok:
            try:
                config.save_discord_user(user_id, name)
            except Exception as exc:  # noqa: BLE001 — 저장 실패도 UI엔 알림
                _log.warning("사용자 저장 실패: %r", exc)
                self._login_status.setText("로그인됐지만 저장 실패 — 다시 시도하세요.")
                self._login_status.setStyleSheet("color:#e67e22;")
                return
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
        # 제작자 아이콘: 굵은 테두리(RGB 58,7,41 = #3A0729).
        pm = _circular(PROFILE_IMAGE, 48, 3, "#3A0729") or _circular(
            LOGO_IMAGE, 48, 3, "#3A0729"
        )
        if pm is not None:
            avatar.setPixmap(pm)
        else:
            avatar.setText("👤")
            avatar.setStyleSheet("font-size:28px;")
        row.addWidget(avatar)

        col = QVBoxLayout()
        col.setSpacing(2)
        # 버전은 상단 타이틀바에 이미 노출되므로 제작자 줄에서는 뺀다.
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

    def _diag_button(self) -> QPushButton:
        # 디버깅용 도구 → 디스코드 로그인 사용자에게만 노출(설명 없이 쓰기 어려움).
        btn = QPushButton("진단 스냅샷 저장 (시간·% 오류 신고용)")
        btn.setToolTip(
            "지금 설정된 버프·디버프·투아림 영역을 그대로 캡처해 PNG로 저장합니다.\n"
            "시간/% 가 틀리게 읽힐 때, 저장된 파일을 제작자에게 보내면 원인을 찾습니다."
        )
        btn.clicked.connect(self._on_diag_snapshot)
        self._diag_btn = btn
        self._refresh_diag()
        return btn

    def _refresh_diag(self) -> None:
        """진단 스냅샷 버튼은 디스코드 로그인 시에만 보인다(디버깅 전용)."""
        if hasattr(self, "_diag_btn"):
            self._diag_btn.setVisible(config.load_discord_user() is not None)

    def _on_diag_snapshot(self) -> None:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMessageBox

        # 바로 캡처하면 앱 창이 게임 영역을 덮어 '어두운 화면'이 찍힌다.
        # 앱을 잠시 최소화하고 몇 초 뒤 캡처해, 그 사이 게임을 맨 앞으로 두게 한다.
        if QMessageBox.question(
            self, "진단 스냅샷",
            "게임에서 버프창(남은시간)이 보이게 띄워 주세요.\n\n"
            "'확인'을 누르면 이 앱이 잠시 최소화되고 5초 뒤 자동으로 캡처합니다.\n"
            "그 사이 게임 화면을 맨 앞으로 두세요.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Ok:
            return
        self.window().showMinimized()
        QTimer.singleShot(5000, self._do_diag_capture)

    def _do_diag_capture(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from .diag_capture import save_diagnostic

        out, saved = save_diagnostic()
        win = self.window()
        win.showNormal()
        win.raise_()
        win.activateWindow()
        if not saved:
            QMessageBox.information(
                self, "진단 스냅샷",
                "저장할 영역이 없습니다 — 버프/디버프/투아림 영역을 먼저 지정하세요.",
            )
            return
        box = QMessageBox(self)
        box.setWindowTitle("진단 스냅샷")
        box.setText(
            f"{len(saved)}개 저장했습니다:\n" + "\n".join(saved)
            + f"\n\n폴더: {out}\n\n이 파일들을 제작자에게 보내 주세요."
        )
        open_btn = box.addButton("폴더 열기", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("닫기", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self._open_folder(out)

    @staticmethod
    def _open_folder(path) -> None:
        import subprocess
        import sys

        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:  # noqa: BLE001, S110 — 폴더 열기는 부가기능(실패해도 무시)
            pass

    def _theme_group(self) -> QGroupBox:
        from .theme import THEME_LABELS, THEMES

        box = QGroupBox("테마")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        row.setSpacing(18)
        self._theme_btns: dict[str, QPushButton] = {}
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        cur = config.load_theme()
        for name in THEMES:
            col = QVBoxLayout()
            col.setSpacing(4)
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setChecked(name == cur)
            btn.setFixedSize(24, 24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, n=name: self._on_theme_pick(n))
            grp.addButton(btn)
            self._theme_btns[name] = btn
            lbl = QLabel(THEME_LABELS[name])
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(lbl)
            cell = QWidget()
            cell.setLayout(col)
            row.addWidget(cell)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(hint_label("'시스템'은 Windows 설정을 따라요. 기본은 다크예요."))
        self._sync_theme_swatches(cur)
        return box

    def _style_swatch(self, btn: QPushButton, name: str, selected: bool) -> None:
        bg = _THEME_SWATCH[name]
        border = (
            f"2px solid {_THEME_ACCENT}" if selected else "1px solid #6b6e76"
        )
        btn.setText("✓" if selected else "")
        btn.setStyleSheet(
            "QPushButton {"
            f" background: {bg}; border: {border}; border-radius: 12px;"
            f" color: {_THEME_ACCENT}; font-size: 12px; font-weight: 900;"
            " }"
        )

    def _sync_theme_swatches(self, selected: str) -> None:
        for name, btn in self._theme_btns.items():
            btn.setChecked(name == selected)
            self._style_swatch(btn, name, name == selected)

    def _on_theme_pick(self, name: str) -> None:
        from .theme import apply_theme

        config.save_theme(name)
        apply_theme(name)  # 즉시 적용
        self._sync_theme_swatches(name)
        self.theme_changed.emit()  # 메인이 탭 등 테마색 재적용

    def _general_group(self) -> QGroupBox:
        from ..system import autostart

        box = QGroupBox("일반")
        v = QVBoxLayout(box)
        # 체크 상태는 저장된 '의도' 기준(없으면 현재 작업 상태를 이어받음).
        intent = config.load_autostart_intent()
        if intent is None:
            intent = autostart.is_enabled()
        self._autostart = _checked("Windows 시작 시 자동 실행", intent)
        self._autostart.setEnabled(autostart.available())
        if not autostart.available():
            self._autostart.setToolTip("Windows에서만 사용할 수 있습니다")
        self._autostart.toggled.connect(self._on_autostart_toggled)
        v.addWidget(self._autostart)

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

        self._grid_snap = _checked(
            "오버레이 격자 맞춤 (이동 시 칸에 딱 맞춤)",
            config.load_general_flag(_GRID_SNAP, False),
        )
        self._grid_snap.toggled.connect(
            lambda on: config.save_general_flag(_GRID_SNAP, on)
        )
        v.addWidget(self._grid_snap)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("격자 크기"))
        self._grid_size = QComboBox()
        for px in _GRID_SIZES:
            self._grid_size.addItem(f"{px} px", px)
        cur = config.load_grid_size()
        idx = _GRID_SIZES.index(cur) if cur in _GRID_SIZES else _GRID_SIZES.index(32)
        self._grid_size.setCurrentIndex(idx)
        self._grid_size.currentIndexChanged.connect(
            lambda _i: config.save_grid_size(self._grid_size.currentData())
        )
        size_row.addWidget(self._grid_size)
        size_row.addStretch(1)
        v.addLayout(size_row)
        v.addWidget(
            hint_label("작을수록 미세, 클수록 큼직하게 칸칸 이동. (기본 32px)")
        )

        toast_row = QHBoxLayout()
        toast_row.addWidget(QLabel("토스트 알림 위치"))
        self._toast_corner = QComboBox()
        for label, corner in _TOAST_CORNER_CHOICES:
            self._toast_corner.addItem(label, corner)
        cur_corner = config.load_toast_corner()
        corner_idx = next(
            (i for i, (_, c) in enumerate(_TOAST_CORNER_CHOICES) if c == cur_corner),
            0,
        )
        self._toast_corner.setCurrentIndex(corner_idx)
        self._toast_corner.currentIndexChanged.connect(self._on_toast_corner_changed)
        toast_row.addWidget(self._toast_corner)
        toast_test = QPushButton("테스트")
        toast_test.setToolTip("지금 설정한 위치로 샘플 토스트를 한 번 띄웁니다")
        toast_test.clicked.connect(self._on_toast_test)
        toast_row.addWidget(toast_test)
        toast_row.addStretch(1)
        v.addLayout(toast_row)
        v.addWidget(
            hint_label("파티모집 등 토스트 알림이 뜰 화면 모서리. (기본 우측 하단)")
        )

        from .notifier import list_voice_packs

        voice_row = QHBoxLayout()
        voice_row.addWidget(QLabel("알림 목소리"))
        self._voice_pack = QComboBox()
        self._voice_pack.addItem("기본(녹음)", "")  # flat 녹음본
        for pack in list_voice_packs():
            self._voice_pack.addItem(pack, pack)
        cur_pack = config.load_voice_pack()
        vi = self._voice_pack.findData(cur_pack)
        self._voice_pack.setCurrentIndex(max(vi, 0))
        self._voice_pack.currentIndexChanged.connect(self._on_voice_pack_changed)
        voice_row.addWidget(self._voice_pack)
        voice_row.addStretch(1)
        v.addLayout(voice_row)
        v.addWidget(
            hint_label(
                "버프·투아림·파티 알림에 쓸 목소리 팩. 고르면 미리듣기가 재생되고 바로 적용돼요."
            )
        )

        tour_row = QHBoxLayout()
        tour_btn = QPushButton("사용법 투어 다시 보기")
        tour_btn.setToolTip("처음 실행 때 나온 단계별 사용법 안내를 다시 봅니다")
        tour_btn.clicked.connect(self.replay_tour.emit)
        tour_row.addWidget(tour_btn)
        notes_btn = QPushButton("업데이트 노트 보기")
        notes_btn.setToolTip("지금까지 배포된 버전별 업데이트 노트를 다시 봅니다")
        notes_btn.clicked.connect(self._show_release_notes)
        tour_row.addWidget(notes_btn)
        tour_row.addStretch(1)
        v.addLayout(tour_row)
        return box

    def _show_release_notes(self) -> None:
        from ..version import display_version
        from .release_notes import ReleaseNotesDialog, all_notes

        md = all_notes()
        if not md:
            md = "표시할 업데이트 노트가 없어요."
        dlg = ReleaseNotesDialog(md, display_version(), self)
        dlg.exec()

    def _on_toast_test(self) -> None:
        from .toast import show_toast

        show_toast("테스트 알림", "토스트가 이 위치에 이렇게 표시됩니다 🎉", 3000)

    def _on_voice_pack_changed(self, _index: int) -> None:
        pack = self._voice_pack.currentData()
        config.save_voice_pack(pack)  # 먼저 저장 → sound_path가 선택 팩을 가리킴
        self._preview_voice()
        self.voice_pack_changed.emit()  # 실행 중 재생기도 새 팩으로 갱신(바로 적용)

    def _preview_voice(self) -> None:
        """선택한 팩의 샘플 음성을 재생(미리듣기). 팩에 없으면 기본 녹음본."""
        from .notifier import SoundNotifier, sound_path

        sample = sound_path("투아림 부스트 발동 직전.mp3")
        if not sample.exists():
            return
        if getattr(self, "_voice_preview", None) is None:
            self._voice_preview = SoundNotifier({})
        self._voice_preview.set_sounds({"preview": sample})
        self._voice_preview.play("preview")

    def _on_autostart_toggled(self, on: bool) -> None:
        from ..system import autostart

        if not autostart.set_enabled(on):
            # 실패: 체크 상태를 실제 결과로 되돌린다(시그널 재발 방지로 blockSignals).
            self._autostart.blockSignals(True)
            self._autostart.setChecked(autostart.is_enabled())
            self._autostart.blockSignals(False)
            QMessageBox.warning(
                self, "자동 실행", "자동 실행 설정을 변경하지 못했습니다."
            )
            return
        config.save_autostart_intent(on)  # 의도 저장 → 다음 시작부터 reconcile이 유지
        if on and not config.load_general_flag(_TRAY_START, False):
            QMessageBox.information(
                self,
                "자동 실행",
                "로그인 시 자동으로 실행됩니다.\n"
                "창 없이 조용히 시작하려면 '실행 시 트레이로 시작'도 켜두세요.",
            )

    def _on_toast_corner_changed(self, _index: int) -> None:
        corner = self._toast_corner.currentData()
        config.save_toast_corner(corner)
        # 바뀐 위치를 바로 확인할 수 있게 샘플 토스트를 띄운다(다음 토스트부터 적용).
        from .toast import show_toast

        show_toast("알림 위치", "토스트가 여기에 표시됩니다.", 2000)

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

    def refresh_game_label(self) -> None:
        """외부(시작 팝업 등)에서 게임 창 등록을 바꾼 뒤 라벨 동기화."""
        self._update_game_label()

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
