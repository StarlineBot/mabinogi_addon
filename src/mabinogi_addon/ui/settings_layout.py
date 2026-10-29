"""Small layout helpers shared by grouped settings pages."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QLabel, QPushButton, QToolButton
from shiboken6 import isValid
import weakref

LOCK_STYLE = (
    "QPushButton { padding:4px 10px; border:1px solid palette(mid); border-radius:3px;"
    " background:palette(button); color:palette(button-text); font-weight:600; }"
    "QPushButton:disabled { color:palette(mid); }"
    "QPushButton:checked:enabled { background:#00b894; color:#062f28; border-color:#00856b; }"
)
DANGER_STYLE = "QPushButton:enabled { color:#d35b58; }"
# 잠금 버튼 통일(안내·도움말 명세 13.1): 글자는 '위치 잠금(됨)', 여러 개를 한 번에 잠그는 버튼만 '전체 위치 잠금(됨)'.
# 앱 전체에서 같은 고정 폭(가장 긴 '전체 위치 잠금됨'이 들어가는 폭, 목업 128px).
LOCK_WIDTH = 128


def lock_text(locked, *, every=False):
    return ("전체 " if every else "") + ("위치 잠금됨" if locked else "위치 잠금")


def lock_width(widget=None):
    font = QFont(widget.font()) if widget is not None else QFont()
    font.setWeight(QFont.Weight.DemiBold)  # LOCK_STYLE의 font-weight:600
    return max(LOCK_WIDTH, QFontMetrics(font).horizontalAdvance(lock_text(True, every=True)) + 26)


def lock_button(locked=False, *, every=False):
    """같은 모양·같은 폭의 위치 잠금 토글 버튼. 글자는 set_lock_text로 바꾼다."""
    button = QPushButton(lock_text(locked, every=every))
    button.setCheckable(True)
    button.setChecked(bool(locked))
    button.setStyleSheet(LOCK_STYLE)
    button.setFixedWidth(lock_width(button))
    button.setProperty("lockEvery", bool(every))
    return button


def set_lock_text(button, locked):
    button.setText(lock_text(locked, every=bool(button.property("lockEvery"))))


# 보스 패턴·1분 헤일로 '화면 표시'의 줄 앞 이름(두 화면 버튼 위치를 같게 하려고 한 묶음으로 잰다, 명세 13.2)
DISPLAY_NAMES = ("패턴 경고", "패턴 목록", "다음 헤일로", "헤일로 경고")


def name_label(text, names=DISPLAY_NAMES):
    """한 상자 안 여러 줄의 줄 앞 이름 칸(명세 13.1). 폭 = 묶음 이름 중 가장 긴 글자 폭.
    가장 긴 이름 뒤 간격이 다른 화면의 '라벨 + 버튼' 간격(레이아웃 기본 간격)과 같아지고, 잠금 버튼은 같은 세로선에 선다."""
    label = QLabel(text)
    metrics = label.fontMetrics()
    label.setFixedWidth(max(metrics.horizontalAdvance(name) for name in (*names, text)) + 2)
    return label


def disclosure(title,body,layout):
    button = QToolButton()
    button.setText(title)
    button.setCheckable(True)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setArrowType(Qt.ArrowType.RightArrow)
    body_ref,button_ref = weakref.ref(body),weakref.ref(button)
    def toggle(value):
        target,control = body_ref(),button_ref()
        if target is not None and isValid(target):
            target.setVisible(value)
        if control is not None and isValid(control):
            control.setArrowType(Qt.ArrowType.DownArrow if value else Qt.ArrowType.RightArrow)
    button.toggled.connect(toggle)
    layout.addWidget(button)
    layout.addWidget(body)
    body.hide()
    return button
