"""시작 시 '게임 창 인식' 안내 팝업.

게임 창 인식은 자동 찾기·오버레이·포그라운드 판정 정확도에 필요(필수)하다. 미등록이면
앱 시작 때 띄워 현재 열린 창 목록에서 마비노기 창을 바로 고르게 한다. '나중에'는 이번
실행만 건너뛰며(영구 숨김 없음), 등록되기 전까진 다음 실행 때 다시 안내한다.

Windows 전용 성격이지만(창 목록이 win32), 다른 OS에서도 생성은 되게 두고 목록이
비면 안내만 보인다(개발/테스트 안전).
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .. import config
from ..system.window_watcher import list_windows
from .notifier import SoundNotifier, sound_path

_GAME_HINTS = ("마비노기", "mabinogi")
# 팝업이 뜰 때 울릴 '경고음'. 전용 사운드는 나중에 교체 예정 → 일단 파티 알림 기본음 사용.
_ALERT_SOUND = "파티 알림.mp3"


class GameWindowDialog(QDialog):
    """현재 창 목록에서 게임 창을 고르는 시작 팝업."""

    def __init__(self, watcher, parent=None) -> None:
        super().__init__(parent)
        self._watcher = watcher
        self.setWindowTitle("게임 창 인식")
        self.setMinimumWidth(420)
        # 팝업이 뜰 때 울릴 경고음(지금은 파티 알림음으로 대체, 전용 음원은 나중에 교체).
        self._notifier = SoundNotifier({"alert": sound_path(_ALERT_SOUND)}, self, volume=0.6)
        self._sound_played = False
        self._last_sig: tuple[tuple[str, str], ...] | None = None

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)

        title = QLabel("⚠️ 게임 창 인식이 필요합니다")
        title.setStyleSheet("font-size:14px; font-weight:700; color:#e67e22;")
        title.setWordWrap(True)
        v.addWidget(title)

        desc = QLabel(
            "이 앱이 제대로 동작하려면 어떤 창이 '게임'인지 알아야 합니다. "
            "인식이 안 되면 자동 찾기가 엉뚱한 화면을 잡거나(특히 모니터 여러 개), "
            "오버레이·포그라운드 판정이 어긋날 수 있습니다.\n"
            "아래에서 마비노기 창을 골라 '이 창으로 지정'을 눌러 주세요."
        )
        desc.setStyleSheet("color:#c7ccd4; font-size:12px;")
        desc.setWordWrap(True)
        v.addWidget(desc)

        self._combo = QComboBox()
        v.addWidget(self._combo)

        self._empty = QLabel("")
        self._empty.setStyleSheet("color:#e67e22; font-size:12px;")
        self._empty.setWordWrap(True)
        self._empty.hide()
        v.addWidget(self._empty)

        row = QHBoxLayout()
        self._refresh_btn = QPushButton("🔄 새로고침")
        self._refresh_btn.clicked.connect(self._refresh)
        row.addWidget(self._refresh_btn)
        row.addStretch(1)
        v.addLayout(row)

        btns = QHBoxLayout()
        btns.addStretch(1)
        later = QPushButton("나중에")
        later.clicked.connect(self._on_later)
        btns.addWidget(later)
        ok = QPushButton("이 창으로 지정")
        ok.setDefault(True)
        ok.clicked.connect(self._on_accept)
        btns.addWidget(ok)
        v.addLayout(btns)

        hint = QLabel(
            "'나중에'를 누르면 이번엔 창 '제목'으로 대충 판정하지만(오인 가능), "
            "등록 전까진 다음 실행 때 다시 안내합니다.\n"
            "설정 탭 → '게임 창 인식'에서 언제든 지정할 수 있어요."
        )
        hint.setStyleSheet("color:#8a8f98; font-size:11px;")
        hint.setWordWrap(True)
        v.addWidget(hint)

        self._refresh()
        # 팝업을 열어둔 채 게임을 켜면 자동으로 목록에 반영(1.5초 폴링).
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._sound_played:
            self._sound_played = True  # 뜰 때 한 번만 경고음
            self._notifier.play("alert")

    def _auto_refresh(self) -> None:
        """팝업을 열어둔 채 게임을 켜면 몇 초 안에 목록에 자동으로 뜨게(변화 있을 때만)."""
        windows = list_windows()
        if tuple(windows) != self._last_sig:
            self._refresh(windows)

    def _refresh(self, windows: list[tuple[str, str]] | None = None) -> None:
        if windows is None:
            windows = list_windows()
        self._last_sig = tuple(windows)
        prev = self._combo.currentData()  # 자동 갱신 시 선택 중이던 항목 유지
        self._combo.clear()
        if not windows:
            self._combo.hide()
            self._empty.setText(
                "열린 창을 찾지 못했어요. 게임을 켜면 자동으로 목록에 나타납니다.\n"
                "(안 뜨면 '새로고침'을 눌러 주세요.)"
            )
            self._empty.show()
            return
        self._empty.hide()
        self._combo.show()
        pre = 0
        for i, (win_title, exe) in enumerate(windows):
            self._combo.addItem(f"{win_title}  —  {exe}", exe)
            low = f"{win_title} {exe}".lower()
            if pre == 0 and any(h in low for h in _GAME_HINTS):
                pre = i  # 마비노기로 보이는 창을 기본 선택
        # 이전에 고르던 게 아직 있으면 그대로, 없으면 마비노기 추정 창.
        keep = next((i for i in range(self._combo.count())
                     if self._combo.itemData(i) == prev), None) if prev else None
        self._combo.setCurrentIndex(keep if keep is not None else pre)

    def done(self, result: int) -> None:
        self._timer.stop()  # 닫히면 폴링 중단
        super().done(result)

    def _on_later(self) -> None:
        # 이번 실행만 건너뛴다(영구 숨김 없음) — 등록 전까진 다음 실행 때 다시 안내한다.
        self.reject()

    def _on_accept(self) -> None:
        exe = self._combo.currentData()
        if exe:
            config.save_game_exe(exe)
            self._watcher.set_game_exe(exe)
        self.accept()
