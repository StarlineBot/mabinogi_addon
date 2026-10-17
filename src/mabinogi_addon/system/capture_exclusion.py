"""Temporarily exclude owned windows from capture without hiding or activating them."""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from functools import lru_cache
import logging
import os
import sys


_log = logging.getLogger(__name__)
_EXCLUDE = 0x11
_warned = False


def available():
    # Older Windows treats EXCLUDEFROMCAPTURE as MONITOR (a black rectangle).
    if sys.platform != "win32":
        return False
    return sys.getwindowsversion().platform_version[2] >= 19041


@lru_cache(maxsize=1)
def _api():
    user = ctypes.WinDLL("user32", use_last_error=True)
    dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
    signatures = (
        (user.GetWindowRect, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
        (user.IsWindow, [wintypes.HWND], wintypes.BOOL),
        (user.IsWindowVisible, [wintypes.HWND], wintypes.BOOL),
        (user.GetWindowThreadProcessId, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        (user.GetWindowDisplayAffinity, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (user.SetWindowDisplayAffinity, [wintypes.HWND, wintypes.DWORD], wintypes.BOOL),
        (dwm.DwmFlush, [], ctypes.c_long),
    )
    for function, arguments, result in signatures:
        function.argtypes = arguments
        function.restype = result
    return user, dwm


def _owned(user, hwnd):
    pid = wintypes.DWORD()
    if not user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
        return None
    return pid.value == os.getpid()


def _warning():
    global _warned
    if not _warned:
        _warned = True
        _log.warning("자체 창 캡처 제외 또는 복원 실패; Windows 캡처 결과가 가려질 수 있습니다")


def _restore(user, hwnd, previous):
    for _ in range(3):
        try:
            owned = _owned(user, hwnd)
            if owned is False or (owned is None and not user.IsWindow(hwnd)):
                return True
            if owned and user.SetWindowDisplayAffinity(hwnd, previous):
                return True
        except Exception:
            pass
    _warning()
    return False


def restore_window(hwnd, previous):
    """Retry a failed restore; caller must verify the original widget still owns HWND."""
    try:
        user, dwm = _api()
        restored = _restore(user, hwnd, previous)
        if restored and dwm.DwmFlush() != 0:
            _warning()
        return restored
    except Exception:
        _warning()
        return False


@contextmanager
def excluding_windows(handles, box):
    """Physical-pixel box; change only intersecting, visible, current-process HWNDs."""
    changed = []
    pending = []
    user = dwm = None
    try:
        if available():
            user, dwm = _api()
            x, y, width, height = box
            for hwnd in dict.fromkeys(handles):
                if not _owned(user, hwnd) or not user.IsWindowVisible(hwnd):
                    continue
                rect = wintypes.RECT()
                if not user.GetWindowRect(hwnd, ctypes.byref(rect)):
                    _warning()
                    continue
                if rect.right <= x or rect.bottom <= y or rect.left >= x + width or rect.top >= y + height:
                    continue
                previous = wintypes.DWORD()
                if not user.GetWindowDisplayAffinity(hwnd, ctypes.byref(previous)):
                    _warning()
                    continue
                if previous.value == _EXCLUDE:
                    continue
                if user.SetWindowDisplayAffinity(hwnd, _EXCLUDE):
                    changed.append((hwnd, previous.value))
                else:
                    _warning()
            if changed and dwm.DwmFlush() != 0:
                _warning()
    except Exception:
        _warning()
    try:
        yield pending
    finally:
        for hwnd, previous in reversed(changed):
            if not _restore(user, hwnd, previous):
                pending.append((hwnd, previous))
        if changed:
            try:
                if dwm.DwmFlush() != 0:
                    _warning()
            except Exception:
                _warning()
