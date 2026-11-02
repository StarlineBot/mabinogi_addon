"""창을 '항상 위' 층의 맨 앞으로(0.38.1 — 마우스 커서 창이 미러링·오버레이 뒤로 숨던 문제).

Windows: SetWindowPos(HWND_TOPMOST, NOMOVE|NOSIZE|NOACTIVATE) — 위치·크기·포커스는 건드리지 않고 순서만 바꾼다.
그 밖(맥·리눅스·테스트): Qt raise_().
"""
from __future__ import annotations

import sys

_HWND_TOPMOST = -1
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOACTIVATE, _SWP_NOOWNERZORDER = 0x0001, 0x0002, 0x0010, 0x0200


def bring_to_front(widget) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            if user32.SetWindowPos(ctypes.c_void_p(int(widget.winId())), ctypes.c_void_p(_HWND_TOPMOST), 0, 0, 0, 0,
                                   _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_NOOWNERZORDER):
                return
        except Exception:  # noqa: BLE001 — 실패하면 Qt 방식으로
            pass
    widget.raise_()
