"""창 내용을 PrintWindow로 캡처(화면에 가려진 부분도 포함).

영역 지정 돋보기용: 게임 창이 작업표시줄 등에 가려 있어도, 그 창 '자기 그림'을
읽어 미리보기에 보여준다. 화면 캡처(grabWindow)는 위에 덮인 창(작업표시줄 등)이
섞이지만, PrintWindow는 지정한 창의 내용만 그려낸다.

읽기 전용 — 창을 이동/활성화하지 않고 그림만 읽는다(앱의 '읽기만 한다' 철학 유지).
Windows 전용(그 외 None). PrintWindow(PW_RENDERFULLCONTENT)는 DWM/일부 D3D 창까지
렌더하지만, 하드웨어 가속 게임은 검게 나올 수 있어 호출 측이 폴백한다.
"""

from __future__ import annotations

import sys

_PW_RENDERFULLCONTENT = 0x00000002  # 가려지거나 D3D로 그려진 내용까지 렌더 시도


def registered_game_target():
    """Return (hwnd, pid, left, top, width, height) in physical pixels, or None."""
    if sys.platform != "win32":
        return None
    try:
        import win32process
        from .. import config
        from . import dwm_thumbnail
        from .window_watcher import DEFAULT_GAME_TITLES

        exe = config.load_game_exe()
        if not exe:
            return None
        hwnd = dwm_thumbnail.find_game_window(exe, DEFAULT_GAME_TITLES)
        rect = dwm_thumbnail.window_rect(hwnd) if hwnd else None
        if rect is None:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        left, top, right, bottom = rect
        if not pid or right <= left or bottom <= top:
            return None
        return int(hwnd), int(pid), left, top, right-left, bottom-top
    except Exception:
        return None


def capture_window_bgra(hwnd: int) -> tuple[bytes, int, int, int, int] | None:
    """창 내용을 (bgra, left, top, w, h)로. 실패/비Windows면 None.

    bgra: w*h*4 바이트(BGRA, top-down) — QImage Format_RGB32로 바로 읽을 수 있다.
    left/top: 창의 화면(물리) 좌표 — 스냅샷 위 합성 위치.
    """
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        import ctypes

        import win32gui
        import win32ui

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        try:
            ok = ctypes.windll.user32.PrintWindow(
                hwnd, save_dc.GetSafeHdc(), _PW_RENDERFULLCONTENT
            )
            bits = bmp.GetBitmapBits(True) if ok else None
        finally:
            win32gui.DeleteObject(bmp.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
        if not ok or not bits:
            return None
        return (bytes(bits), int(left), int(top), int(w), int(h))
    except Exception:  # noqa: BLE001 — 캡처 실패는 폴백(화면 스냅샷 사용)
        return None
