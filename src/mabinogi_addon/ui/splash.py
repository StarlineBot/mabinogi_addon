"""시작 스플래시 (로딩 화면).

onefile exe는 실행 직후 압축 해제 + Python/Qt 로딩 때문에 바로 안 뜬다. 그 사이를
로고 + 프로그레스바 + (로딩 문구 자리에) 랜덤 위트 메시지로 덮는다.

- 압축 해제 구간: PyInstaller --splash(정적, frozen 전용)가 먼저 덮고(entry에서 닫음),
- 초기화 구간: 이 Qt 스플래시가 진행률을 보여준다.
"""

from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .. import paths

_LOGO = paths.resource_dir() / "logo.png"
_PROFILE = paths.resource_dir() / "profile.png"  # 제작자 아이콘(없으면 로고로 폴백)
_CREATOR = "섯다라인"  # 캐릭터가 말하는 것처럼 "섯다라인 : <문구>"

# 로딩 문구(마비노기 상황극) — discord_bot modules/loading.js 의 FLAVORS에서 가져옴.
MESSAGES = [
    "브리레흐 3관 도는 중",
    "크롬바스에서 보상상자 까는 중",
    "볼트 마법 조합 준비 중",
    "비바체 연주 하는 중",
    "스노우 스톰 시전 중",
    "익스플로전 런지 시전 중",
    "80 헤일로 어떻게 한 번에 깰지 고민 중",
    "브리레흐 2관 줄넘기 중",
    "크롬바스 심연에서 회오리 피하는 중",
    "잔흔 부족으로 레이턴트 이그니션 사용 못하는 중",
    "잘못 나간 라이트닝 체인 줍는 중",
    "브리레흐 1관 도는 중",
    "크롬바스에서 100버스트 중",
    "스노우 스톰 아끼는 중",
    "레이턴트 이그니션 사용 중",
    "크롬바스 심연에서 레이저 맞는 중",
]


def _round_pixmap(path, size: int) -> QPixmap | None:
    """이미지를 정사각 중앙 크롭 후 원형으로."""
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
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, size, size)
    p.setClipPath(clip)
    p.drawPixmap(0, 0, src)
    p.end()
    return out


class Splash(QWidget):
    """로고 + 프로그레스바 + 위트 메시지. step()으로 진행률·문구 갱신."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen,
        )
        self.setFixedSize(440, 170)

        card = QWidget(self)
        card.setObjectName("card")
        card.setFixedSize(440, 170)
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 22, 24, 22)
        v.setSpacing(12)

        v.addStretch(1)
        # [캐릭터 얼굴] 옆에 [이름(위) / 내용(아래)] 두 줄 — 캐릭터가 말하는 느낌
        row = QHBoxLayout()
        row.setSpacing(14)
        avatar = QLabel()
        avatar.setFixedSize(56, 56)
        pm = _round_pixmap(_PROFILE, 56) or _round_pixmap(_LOGO, 56)
        if pm is not None:
            avatar.setPixmap(pm)
        row.addWidget(avatar)

        col = QVBoxLayout()
        col.setSpacing(3)
        col.addStretch(1)
        name = QLabel(_CREATOR)
        name.setObjectName("name")
        col.addWidget(name)
        self.msg = QLabel()
        self.msg.setObjectName("msg")
        col.addWidget(self.msg)
        col.addStretch(1)
        row.addLayout(col, 1)
        v.addLayout(row)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        v.addWidget(self.bar)
        v.addStretch(1)  # 위·아래 stretch로 전체(얼굴+문구+바)를 세로 가운데 정렬

        self._set_msg(random.choice(MESSAGES))

        self.setStyleSheet(
            "#card { background:#1f2937; border:1px solid #00B894; border-radius:14px; }"
            "#name { color:#00D1A7; font-size:14px; font-weight:700; }"
            "#msg { color:#e5e7eb; font-size:13px; }"
            "QProgressBar { background:#111827; border:none; border-radius:3px; }"
            "QProgressBar::chunk { background:#00D1A7; border-radius:3px; }"
        )

    def _set_msg(self, text: str) -> None:
        self.msg.setText(text)

    def step(self, pct: int, msg: str | None = None) -> None:
        """진행률(%)과 문구 갱신. 문구 생략 시 랜덤 상황 문구."""
        self.bar.setValue(max(0, min(100, pct)))
        self._set_msg(msg or random.choice(MESSAGES))
        QApplication.processEvents()  # 스플래시가 바로 다시 그려지게

    def center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center() - self.rect().center())
