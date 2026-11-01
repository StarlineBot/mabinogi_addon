"""판독 캡처 때 우리 오버레이 창 빼기(도르카 `_grab_tracking_rect`와 같은 방식을 공용으로).

판독 영역과 겹친 **우리** 최상위 창만 캡처하는 동안 화면 캡처에서 제외(`WDA_EXCLUDEFROMCAPTURE`)했다가 되돌린다.
창을 숨기거나 활성화하지 않는다. Windows 10 2004 미만·다른 OS(`capture_exclusion.available()` False)는 그대로 캡처.
되돌리기에 실패한 창은 기억했다가 다음 캡처·정지 때 다시 되돌린다(같은 HWND가 다른 창으로 재사용됐으면 건드리지 않음).
"""

from __future__ import annotations

import weakref

from PySide6.QtCore import Qt


class CaptureGuard:
    def __init__(self) -> None:
        self._pending: dict[int, tuple] = {}

    def grab(self, grab, x: int, y: int, w: int, h: int):
        from ..system import capture_exclusion

        self.restore()
        if not capture_exclusion.available():
            return grab(x, y, w, h)
        from PySide6.QtWidgets import QApplication

        widgets = {int(widget.winId()): weakref.ref(widget)
                   for widget in QApplication.topLevelWidgets() if widget.isVisible()}
        pending = []
        try:
            with capture_exclusion.excluding_windows(widgets, (x, y, w, h)) as pending:
                return grab(x, y, w, h)
        finally:
            for hwnd, previous in pending:
                self._pending.setdefault(hwnd, (widgets[hwnd], previous))

    def restore(self) -> None:
        if not self._pending:
            return
        from shiboken6 import isValid
        from ..system.capture_exclusion import restore_window

        for hwnd, (reference, previous) in list(self._pending.items()):
            widget = reference()
            if (widget is None or not isValid(widget)
                    or not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)
                    or int(widget.winId()) != hwnd or restore_window(hwnd, previous)):
                del self._pending[hwnd]
