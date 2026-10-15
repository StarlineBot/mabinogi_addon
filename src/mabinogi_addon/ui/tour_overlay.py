"""첫 실행 온보딩 투어(코치마크).

전체를 살짝 어둡게 깔고, 현재 단계의 대상 위젯만 '밝게 뚫어' 노란 점선으로 강조하며,
설명 카드로 순서대로 안내한다([이전]/[다음]/[건너뛰기]). 메인 창 위에 올리는 자식
오버레이라, 게임/다른 창과의 z-order 문제 없이 앱 컨트롤만 가리킨다.

사용:
    steps = [TourStep(target=btn, title="...", body="...", before=cb), ...]
    TourOverlay(main_window, steps, on_done=...).start()
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass
class TourStep:
    target: QWidget | None  # 강조할 위젯(None이면 화면 중앙 설명 카드만)
    title: str
    body: str
    before: Callable[[], None] | None = None  # 단계 진입 시 실행(예: 탭 전환)


_PAD = 6  # 강조 박스가 대상보다 살짝 크게


class TourOverlay(QWidget):
    def __init__(
        self,
        host: QWidget,
        steps: list[TourStep],
        on_done: Callable[[], None] | None = None,
        section_title: str = "",
    ) -> None:
        # 화면 전체를 덮는 최상위 반투명 창. (자식 위젯이면 앱 영역만 덮고, 게다가
        # Clear로 뚫은 구멍이 부모를 비추지 못해 '검게' 나온다.) 최상위라야 바탕화면까지
        # 어두워지고, 구멍이 뒤(앱 버튼)를 원래 밝기로 비춘다.
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._host = host
        self._steps = steps
        self._on_done = on_done
        self._section_title = section_title
        self._i = 0
        self._screen_geo = QRect()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self._card = QFrame(self)
        self._card.setObjectName("tourCard")
        cv = QVBoxLayout(self._card)
        cv.setContentsMargins(16, 14, 16, 12)
        cv.setSpacing(8)
        self._title = QLabel()
        self._title.setObjectName("tourTitle")
        self._title.setWordWrap(True)
        cv.addWidget(self._title)
        self._body = QLabel()
        self._body.setObjectName("tourBody")
        self._body.setWordWrap(True)
        cv.addWidget(self._body)
        row = QHBoxLayout()
        self._step_lbl = QLabel()
        self._step_lbl.setObjectName("tourStep")
        row.addWidget(self._step_lbl)
        row.addStretch(1)
        self._skip = QPushButton("건너뛰기")
        self._skip.setObjectName("tourSkip")
        self._skip.clicked.connect(self._finish)
        row.addWidget(self._skip)
        self._prev = QPushButton("이전")
        self._prev.clicked.connect(self._go_prev)
        row.addWidget(self._prev)
        self._next = QPushButton("다음")
        self._next.setObjectName("tourNext")
        self._next.clicked.connect(self._go_next)
        row.addWidget(self._next)
        cv.addLayout(row)
        self._card.setFixedWidth(320)

        self.setStyleSheet(
            "#tourCard { background:#1f2937; border:1px solid #FFD54A; border-radius:12px; }"
            "#tourTitle { color:#FFD54A; font-size:14px; font-weight:800; }"
            "#tourBody { color:#e5e7eb; font-size:12px; }"
            "#tourStep { color:#9aa0aa; font-size:11px; }"
            "QPushButton { background:#2a2f3a; color:#e5e7eb; border:1px solid #3a3f4a;"
            " border-radius:6px; padding:4px 12px; }"
            "#tourNext { background:#FFD54A; color:#2a2300; border:none; font-weight:700; }"
            "#tourSkip { background:transparent; color:#9aa0aa; border:none; }"
        )
        self._host.installEventFilter(self)  # 창 크기 바뀌면 오버레이도 맞춤

    # ---- 공개 ----
    def start(self) -> None:
        self._fit_to_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        self._show_step()

    # ---- 내부 ----
    def _fit_to_screen(self) -> None:
        """앱이 있는 화면 전체를 덮는다(바탕화면까지 어둡게)."""
        screen = self._host.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            self._screen_geo = screen.geometry()
            self.setGeometry(self._screen_geo)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # 앱이 움직이거나 크기가 바뀌면 대상 위치가 달라지므로 다시 맞춘다.
        if obj is self._host and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
        ):
            self._fit_to_screen()
            self._place_card()
            self.update()
        return super().eventFilter(obj, event)

    def _target_rect(self) -> QRect | None:
        step = self._steps[self._i]
        if step.target is None or not step.target.isVisible():
            return None
        gtl = step.target.mapToGlobal(QPoint(0, 0))  # 전역(스크린) 좌표
        tl = gtl - self._screen_geo.topLeft()  # 화면 오버레이 로컬 좌표
        return QRect(tl, step.target.size()).adjusted(-_PAD, -_PAD, _PAD, _PAD)

    def _show_step(self) -> None:
        step = self._steps[self._i]
        if step.before is not None:
            step.before()
        self._title.setText(step.title)
        self._body.setText(step.body)
        self._step_lbl.setText((self._section_title + " · " if self._section_title else "")
                               + f"{self._i + 1} / {len(self._steps)}")
        self._prev.setVisible(self._i > 0)
        self._next.setText("시작하기" if self._i == len(self._steps) - 1 else "다음")
        self._card.adjustSize()
        self._place_card()
        self.update()

    def _place_card(self) -> None:
        r = self._target_rect()
        cw, ch = self._card.width(), self._card.height()
        margin = 14
        if r is None:  # 대상 없음 → 화면 중앙
            x = (self.width() - cw) // 2
            y = (self.height() - ch) // 2
        else:
            # 대상 아래에 두되, 공간 없으면 위로. 가로는 대상 왼쪽에 맞추되 화면 안으로.
            y = r.bottom() + margin
            if y + ch > self.height() - margin:
                y = r.top() - margin - ch
            if y < margin:
                y = min(self.height() - ch - margin, max(margin, r.bottom() + margin))
            x = min(max(margin, r.left()), self.width() - cw - margin)
        self._card.move(max(0, x), max(0, y))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 130))  # 전체 딤
        r = self._target_rect()
        if r is not None:
            # 대상 영역만 '밝게' 뚫기(뒤 위젯이 원래 밝기로 보이게).
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(r, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(QColor("#FFD54A"), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(r, 8, 8)
        p.end()

    def _go_next(self) -> None:
        if self._i >= len(self._steps) - 1:
            self._finish()
            return
        self._i += 1
        self._show_step()

    def _go_prev(self) -> None:
        if self._i > 0:
            self._i -= 1
            self._show_step()

    def _finish(self) -> None:
        try:
            if self._on_done is not None:
                self._on_done()
        finally:
            self.dismiss()

    def dismiss(self) -> None:
        self._host.removeEventFilter(self)
        self.close()
        self.deleteLater()
