"""진단 시점의 Qt 화면 정보와 Windows 모니터별 유효 DPI."""

from __future__ import annotations

import sys


def monitor_info() -> dict:
    from PySide6.QtGui import QGuiApplication

    screens = []
    for screen in QGuiApplication.screens():
        g = screen.geometry()
        screens.append({"name": screen.name(), "logical_rect": [g.x(), g.y(), g.width(), g.height()],
                        "device_pixel_ratio": screen.devicePixelRatio(),
                        "logical_dpi": [screen.logicalDotsPerInchX(), screen.logicalDotsPerInchY()],
                        "physical_dpi": [screen.physicalDotsPerInchX(), screen.physicalDotsPerInchY()],
                        "primary": screen == QGuiApplication.primaryScreen()})
    result = {"qt_screens": screens, "coordinate_conversion": "primary_screen_device_pixel_ratio"}
    if sys.platform == "win32":
        try:
            result["windows_monitors"] = _windows_monitors()
        except Exception as exc:
            result["windows_dpi_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _windows_monitors() -> list[dict]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shcore = ctypes.WinDLL("shcore", use_last_error=True)
    get_dpi = shcore.GetDpiForMonitor
    get_dpi.argtypes = [wintypes.HMONITOR, ctypes.c_int, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
    get_dpi.restype = ctypes.c_long
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    enum = user32.EnumDisplayMonitors
    enum.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), callback_type, wintypes.LPARAM]
    enum.restype = wintypes.BOOL
    monitors = []

    def collect(handle, _dc, rectangle, _data):
        rect = rectangle.contents
        x, y = wintypes.UINT(), wintypes.UINT()
        hr = get_dpi(handle, 0, ctypes.byref(x), ctypes.byref(y))
        monitors.append({"physical_rect": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
                         "effective_dpi": [x.value, y.value] if hr == 0 else None,
                         "dpi_hresult": hr})
        return True

    callback = callback_type(collect)
    if not enum(None, None, callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return monitors
