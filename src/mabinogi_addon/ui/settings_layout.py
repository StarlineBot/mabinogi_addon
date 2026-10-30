"""Small layout helpers shared by grouped settings pages."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QLabel, QPushButton, QToolButton
from shiboken6 import isValid

from .palette import color
import weakref

# 상태형 토글(위치 잠금·최적화·FPS 표시·블랙박스 사용) 공통 톤. 굵기 보통·세로 padding 0, 켜짐 초록(안내·도움말 명세 13.1 정정).
# 높이는 스타일시트로 계산하지 않고 style_toggle에서 일반 버튼 높이로 고정한다(스타일시트를 입히면 Windows 기본 버튼 높이를 버리기 때문).
def lock_style():
    return (
        "QPushButton { padding:0 10px; border:1px solid palette(mid); border-radius:3px;"
        " background:palette(button); color:palette(button-text); font-weight:400; }"
        "QPushButton:disabled { color:palette(mid); }"
        f"QPushButton:checked:enabled {{ background:{color('accent')}; color:{color('on-accent')}; border-color:#00856b; }}"
    )


def danger_style():
    return f"QPushButton:enabled {{ color:{color('danger')}; }}"


LOCK_PADDING = 22  # 잠금 버튼 폭 = 보통 굵기 '…위치 잠금됨' 글자 폭 + 여백(B안)


def plain_button_height():
    """스타일시트 없는 일반 QPushButton의 기본 높이(옆 '알림 미리보기' 등과 같은 키)."""
    return QPushButton("가").sizeHint().height()


def style_toggle(button):
    """상태형 토글 버튼에 공통 톤을 입히는 한 곳: 스타일 + 일반 버튼 높이. 폭은 호출한 쪽이 정한다(토글은 글자에 맞춤)."""
    button.setCheckable(True)
    button.setStyleSheet(lock_style())
    button.setFixedHeight(plain_button_height())
    return button


def lock_text(locked, *, every=False):
    return ("전체 " if every else "") + ("위치 잠금됨" if locked else "위치 잠금")


def lock_width(widget=None, *, every=False):
    """같은 종류끼리 같은 폭: 일반 '위치 잠금(됨)' / '전체 위치 잠금(됨)'. 보통 굵기 '…잠금됨' 글자 폭 + 여백."""
    font = QFont(widget.font()) if widget is not None else QFont()
    return QFontMetrics(font).horizontalAdvance(lock_text(True, every=every)) + LOCK_PADDING


def lock_button(locked=False, *, every=False):
    """같은 모양의 위치 잠금 토글 버튼(일반·전체 종류별 같은 폭). 글자는 set_lock_text로 바꾼다."""
    button = style_toggle(QPushButton(lock_text(locked, every=every)))
    button.setChecked(bool(locked))
    button.setFixedWidth(lock_width(button, every=every))
    button.setProperty("lockEvery", bool(every))
    return button


def set_lock_text(button, locked):
    button.setText(lock_text(locked, every=bool(button.property("lockEvery"))))


def name_label(text, names=()):
    """한 상자 안 여러 줄의 줄 앞 이름 칸(명세 13.1). 폭 = 같은 상자 이름(names) 중 가장 긴 글자 폭.
    상자 안 잠금 버튼은 같은 세로선에 서고, 가장 긴 이름 뒤 간격은 다른 화면의 '라벨 + 버튼' 간격과 같다.
    화면끼리(보스 패턴·1분 헤일로) 버튼 위치는 맞추지 않는다 — 이름 길이가 달라 간격 통일을 택함(2026-10-29 사용자 결정)."""
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
