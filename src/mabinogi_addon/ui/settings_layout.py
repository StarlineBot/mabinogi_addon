"""Small layout helpers shared by grouped settings pages."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton
from shiboken6 import isValid
import weakref

LOCK_STYLE = (
    "QPushButton { padding:4px 10px; border:1px solid palette(mid); border-radius:3px;"
    " background:palette(button); color:palette(button-text); font-weight:600; }"
    "QPushButton:disabled { color:palette(mid); }"
    "QPushButton:checked:enabled { background:#00b894; color:#062f28; border-color:#00856b; }"
)
DANGER_STYLE = "QPushButton:enabled { color:#d35b58; }"


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
