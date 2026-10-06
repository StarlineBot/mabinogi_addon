"""설정 탭 (기획서 5.3).

일반 설정 + 게임 창 인식. (오버레이 배율은 각 버프/디버프 탭으로 이동, 알림음은
버프별 등록 사운드로 재생 — TTS 미사용.) 아직 설정 파일과 연결 안 한 항목도 있다.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..system.window_watcher import WindowWatcher
from .widgets import hint_label


def _checked(text: str, on: bool = True) -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(on)
    return box


class SettingsTab(QWidget):
    def __init__(self, watcher: WindowWatcher) -> None:
        super().__init__()
        self._watcher = watcher
        self._detect_count = 0
        self._detect_timer: QTimer | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(12)
        v.addWidget(self._general_group())
        v.addWidget(self._game_group())
        v.addStretch(1)

    def _general_group(self) -> QGroupBox:
        box = QGroupBox("일반")
        v = QVBoxLayout(box)
        v.addWidget(_checked("Windows 시작 시 자동 실행"))
        v.addWidget(_checked("실행 시 트레이로 시작"))
        v.addWidget(_checked("닫기(X) 버튼을 누르면 트레이로 최소화"))
        v.addWidget(_checked("게임 비활성 중에도 소리 알림"))
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
        title, exe = self._watcher.foreground_info()
        self._detect_btn.setEnabled(True)
        self._detect_btn.setText("게임 창 자동 찾기")
        if exe:
            config.save_game_exe(exe)
            self._watcher.set_game_exe(exe)
            self._update_game_label()
        else:
            self._game_hint.setText("자동 찾기 실패(창 정보를 못 읽음). Windows에서 시도하세요.")
            self._game_hint.setStyleSheet("color:#e67e22;")
