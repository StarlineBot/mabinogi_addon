"""Exercise nested scrolling before asserting full control reachability."""

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QScrollArea


def assert_control_reachable(control, app, context):
    scrolls = []
    ancestor = control.parentWidget()
    while ancestor is not None:
        if isinstance(ancestor, QScrollArea):
            scrolls.append(ancestor)
        ancestor = ancestor.parentWidget()
    assert scrolls, (context, control.text(), "no scroll owner")
    for scroll in scrolls:
        scroll.ensureWidgetVisible(control)
        for _ in range(4):
            app.processEvents()
    for scroll in scrolls:
        rect = QRect(control.mapTo(scroll.viewport(), QPoint()), control.size())
        assert scroll.horizontalScrollBar().maximum() == 0, (context, "horizontal scroll")
        assert scroll.viewport().rect().contains(rect), (context, control, rect, scroll.viewport().rect())
