"""잡담 대상 영역만 Windows Z-order/모니터/입력 데스크톱으로 확인한다.

이미지 캡처나 포커스 이동은 하지 않는다. 판정 실패는 노출 불가다.
"""

import sys


def subtract(rect, cover):
    x, y, r, b = rect
    cx, cy, cr, cb = cover
    ix, iy, ir, ib = max(x, cx), max(y, cy), min(r, cr), min(b, cb)
    if ix >= ir or iy >= ib:
        return [rect]
    return [part for part in ((x, y, r, iy), (x, ib, r, b),
                              (x, iy, ix, ib), (ir, iy, r, ib))
            if part[0] < part[2] and part[1] < part[3]]


def desktop_unlocked():
    import ctypes
    from ctypes import wintypes

    user = ctypes.windll.user32
    user.OpenInputDesktop.restype = wintypes.HANDLE
    user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]
    desktop = user.OpenInputDesktop(0, False, 1)
    if not desktop:
        return False
    try:
        name = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        return bool(user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name),
                                                   ctypes.byref(needed)) and name.value == "Default")
    finally:
        user.CloseDesktop(desktop)


def exposed(hwnd: int, local_rects: list, logical_size: tuple[int, int]) -> bool:
    if sys.platform != "win32":
        return False  # 렌더에서는 명시적으로 가짜 노출 판정을 주입한다.
    try:
        import ctypes
        from ctypes import wintypes
        import win32api
        import win32gui

        if not desktop_unlocked() or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return False
        client = win32gui.GetClientRect(hwnd)
        origin = win32gui.ClientToScreen(hwnd, (0, 0))
        sx, sy = client[2] / logical_size[0], client[3] / logical_size[1]
        targets = [(origin[0] + int(x * sx), origin[1] + int(y * sy),
                    origin[0] + int((x + w) * sx + .999),
                    origin[1] + int((y + h) * sy + .999)) for x, y, w, h in local_rects]
        for rect in targets:
            remaining = [rect]
            for _, _, screen in win32api.EnumDisplayMonitors():
                remaining = [piece for item in remaining for piece in subtract(item, screen)]
            if remaining:
                return False
        found, blocked = False, False

        def visit(other, _):
            nonlocal found, blocked
            if found or blocked:
                return True
            if other == hwnd:
                found = True
                return True
            if not win32gui.IsWindowVisible(other) or win32gui.IsIconic(other):
                return True
            cloaked = wintypes.DWORD()
            result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(other), 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            if result != 0:
                blocked = True
                return True
            if cloaked.value:
                return True
            bounds = wintypes.RECT()
            result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(other), 9, ctypes.byref(bounds), ctypes.sizeof(bounds))
            cover = ((bounds.left, bounds.top, bounds.right, bounds.bottom) if result == 0
                     else win32gui.GetWindowRect(other))
            blocked = any(max(t[0], cover[0]) < min(t[2], cover[2])
                          and max(t[1], cover[1]) < min(t[3], cover[3]) for t in targets)
            return True

        win32gui.EnumWindows(visit, None)
        return found and not blocked
    except Exception:  # 부가기능 판정 실패를 기존 트래커로 전파하지 않는다.
        return False
