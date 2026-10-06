"""UI 공용 소형 위젯.

지금 단계는 레이아웃 확정을 위한 '껍데기'다. 동작(파일 선택, 영역 지정,
설정 저장)은 아직 연결하지 않고 자리만 잡는다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


def icon_slot(placeholder: str = "▣") -> QLabel:
    """아이콘 미리보기 칸. 나중에 QPixmap을 setPixmap으로 채운다."""
    slot = QLabel(placeholder)
    slot.setAlignment(Qt.AlignmentFlag.AlignCenter)
    slot.setFixedSize(44, 44)
    slot.setStyleSheet(
        "border:1px solid #9aa0a6; border-radius:6px;"
        "font-size:22px; color:#9aa0a6; background:#2b2d31;"
    )
    return slot


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color:#8a8f98;")
    return lbl


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-weight:600; color:#c8ccd4;")
    return lbl
