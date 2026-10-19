"""Original detector reproductions with an explicit compositor-exclusion boundary."""

from contextlib import contextmanager

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from mabinogi_addon.system import capture_exclusion
from test_support.regressions.dorcha_restart import (
    moved,
    test_restart_must_reacquire_visible_moved_resource,
    test_one_shot_autofind_approval_recovers_the_same_input,
    test_restart_recovery_with_own_window_over_ornament,
)


@pytest.fixture(autouse=True)
def compositor_boundary(monkeypatch):
    # The original fake desktop composites QWidget visibility, not real HWND affinity.
    # Model exclusion only at this OS boundary; detectors and assertions stay original.
    @contextmanager
    def excluded(handles, box):
        x, y, w, h = box
        changed = []
        for widget in QApplication.topLevelWidgets():
            rect = widget.geometry()
            if (widget.isVisible() and int(widget.winId()) in handles
                    and rect.right() >= x and rect.bottom() >= y
                    and rect.left() < x+w and rect.top() < y+h):
                changed.append((widget, widget.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)))
                widget.hide()
        try:
            yield []
        finally:
            for widget, previous in changed:
                widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
                widget.show()
                widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, previous)

    monkeypatch.setattr(capture_exclusion, "available", lambda: True)
    monkeypatch.setattr(capture_exclusion, "excluding_windows", excluded)
