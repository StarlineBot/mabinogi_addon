"""토스트 알림 위젯 (기획서 3.5).

직접 그리는 프레임리스 창: 화면 우측 하단, 항상 최상위, 3초 후 자동 소멸,
클릭하면 즉시 닫힘. 네이티브 Windows 토스트가 아니라 Qt 창이라 집중지원 모드에
묻히지 않고 위치·지속을 완전히 제어한다.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from .. import config

_MARGIN = 16  # 화면 가장자리 여백
_GAP = 10  # 토스트 사이 간격
_active: list[Toast] = []  # 현재 떠 있는 토스트(아래→위로 쌓기)


class Toast(QWidget):
    def __init__(
        self,
        title: str,
        body: str,
        duration_ms: int = 5000,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        self._on_click = on_click
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        # 포커스를 뺏지 않고 뜬다(게임 입력 방해 금지).
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedWidth(320)
        if on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)  # 클릭 가능 표시

        wrap = QWidget(self)
        wrap.setObjectName("toast")
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("toastTitle")
        body_label = QLabel(body)
        body_label.setObjectName("toastBody")
        body_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(body_label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrap)

        self.setStyleSheet(
            "#toast { background:#1f2937; border:1px solid #00B894; border-radius:10px; }"
            "#toastTitle { color:#00D1A7; font-weight:600; font-size:13px; }"
            "#toastBody { color:#e5e7eb; font-size:13px; }"
        )

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)
        self._timer.start(duration_ms)

    # 클릭하면 동작(있으면) 실행 후 즉시 닫기
    def mousePressEvent(self, event) -> None:
        if self._on_click is not None:
            try:
                self._on_click()
            except Exception:  # noqa: BLE001, S110 — 클릭 동작 실패로 앱이 죽지 않게
                pass
        self.close()

    def closeEvent(self, event) -> None:
        if self in _active:
            _active.remove(self)
        _reflow()
        super().closeEvent(event)

    def show_toast_window(self) -> None:
        self.adjustSize()
        _active.append(self)
        _reflow()
        self.show()


def _reflow() -> None:
    """설정된 모서리 기준으로 떠 있는 토스트들을 쌓아 재배치(안쪽 방향으로)."""
    screen = QApplication.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    corner = config.load_toast_corner()
    right = corner in ("br", "tr")
    bottom = corner in ("br", "bl")
    # 바깥 모서리에서 시작해, 최신이 모서리에 가장 가깝게 안쪽으로 쌓는다.
    y = (area.bottom() - _MARGIN) if bottom else (area.top() + _MARGIN)
    for toast in reversed(_active):  # 최신이 모서리 쪽
        x = (area.right() - _MARGIN - toast.width()) if right else (area.left() + _MARGIN)
        if bottom:
            y -= toast.height()
            toast.move(x, y)
            y -= _GAP
        else:
            toast.move(x, y)
            y += toast.height() + _GAP


def show_toast(
    title: str,
    body: str,
    duration_ms: int = 5000,
    on_click: Callable[[], None] | None = None,
) -> Toast:
    toast = Toast(title, body, duration_ms, on_click)
    toast.show_toast_window()
    return toast
