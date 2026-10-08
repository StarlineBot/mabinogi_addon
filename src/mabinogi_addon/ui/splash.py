"""시작 스플래시 (로딩 화면).

onefile exe는 실행 직후 압축 해제 + Python/Qt 로딩 때문에 바로 안 뜬다. 그 사이를
로고 + 프로그레스바 + (로딩 문구 자리에) 랜덤 위트 메시지로 덮는다.

- 압축 해제 구간: PyInstaller --splash(정적, frozen 전용)가 먼저 덮고(entry에서 닫음),
- 초기화 구간: 이 Qt 스플래시가 진행률을 보여준다.
"""

from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .. import paths

_LOGO = paths.resource_dir() / "logo.png"

# 로딩 문구 자리에 랜덤으로 뜨는 위트 메시지(마비노기 감성).
MESSAGES = [
    "마나를 끌어모으는 중…",
    "글렌 베르나 날씨 확인 중…",
    "투아림 눈치 보는 중…",
    "상지 다시 거는 중…",
    "비바체 리듬 타는 중…",
    "햄찌 소환 준비 중…",
    "하프 줄 고르는 중…",
    "요정 깨우는 중…",
    "버프 아이콘 외우는 중…",
    "파티원 수소문 중…",
    "전장의 서곡 튜닝 중…",
    "크리스탈 닦는 중…",
]


class Splash(QWidget):
    """로고 + 프로그레스바 + 위트 메시지. step()으로 진행률·문구 갱신."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen,
        )
        self.setFixedSize(360, 240)

        card = QWidget(self)
        card.setObjectName("card")
        card.setFixedSize(360, 240)
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 28, 24, 22)
        v.setSpacing(14)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = QPixmap(str(_LOGO))
        if not pm.isNull():
            logo.setPixmap(
                pm.scaled(
                    96, 96,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        v.addStretch(1)
        v.addWidget(logo)

        title = QLabel("섯다라인 마비노기 애드온")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setObjectName("title")
        v.addWidget(title)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        v.addWidget(self.bar)

        self.msg = QLabel(random.choice(MESSAGES))
        self.msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg.setObjectName("msg")
        v.addWidget(self.msg)
        v.addStretch(1)

        self.setStyleSheet(
            "#card { background:#1f2937; border:1px solid #00B894; border-radius:14px; }"
            "#title { color:#e5e7eb; font-size:14px; font-weight:700; }"
            "#msg { color:#8a8f98; font-size:12px; }"
            "QProgressBar { background:#111827; border:none; border-radius:3px; }"
            "QProgressBar::chunk { background:#00D1A7; border-radius:3px; }"
        )

    def step(self, pct: int, msg: str | None = None) -> None:
        """진행률(%)과 문구 갱신. 문구 생략 시 랜덤 위트 메시지."""
        self.bar.setValue(max(0, min(100, pct)))
        self.msg.setText(msg or random.choice(MESSAGES))
        QApplication.processEvents()  # 스플래시가 바로 다시 그려지게

    def center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center() - self.rect().center())
