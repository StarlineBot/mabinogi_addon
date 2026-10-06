"""오버레이 클릭 통과 (기획서 3.4). Windows 전용, 그 외는 no-op.

Qt의 WA_TransparentForMouseEvents만으로 부족한 경우를 대비해, Windows에서는
확장 스타일 WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE를 직접 건다.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QWidget


def set_click_through(widget: QWidget, enabled: bool) -> None:
    """locked=True면 창을 클릭 통과·비활성화(포커스 안 뺏음)로 만든다."""
    if sys.platform != "win32":
        return
    try:
        import win32con
        import win32gui
    except ImportError:
        return

    hwnd = int(widget.winId())
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    flags = (
        win32con.WS_EX_TRANSPARENT
        | win32con.WS_EX_LAYERED
        | win32con.WS_EX_NOACTIVATE
    )
    if enabled:
        style |= flags
    else:
        style &= ~win32con.WS_EX_TRANSPARENT  # 레이어드·노액티베이트는 유지
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
