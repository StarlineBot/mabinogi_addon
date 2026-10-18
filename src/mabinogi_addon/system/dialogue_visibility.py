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
        error = ctypes.WinError()
        error.native_api = "OpenInputDesktop"
        raise error
    try:
        name = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name),
                                              ctypes.byref(needed)):
            error = ctypes.WinError()
            error.native_api = "GetUserObjectInformationW"
            raise error
        return name.value == "Default"
    finally:
        user.CloseDesktop(desktop)


def _region_overlap(gui, hwnd, targets, detail):
    """Return None without positive region evidence; always release the temporary GDI region."""
    region = None
    try:
        region = gui.CreateRectRgn(0, 0, 0, 0)
        kind = gui.GetWindowRgn(hwnd, region)
        detail["region_type"] = kind
        if kind == 1:  # NULLREGION: explicitly empty, unlike ERROR (no region information).
            return False
        if kind not in (2, 3):
            return None
        x, y, _, _ = gui.GetWindowRect(hwnd)
        # Window regions are relative to GetWindowRect, not the DWM extended frame.
        return any(gui.RectInRegion(region, (l-x, t-y, r-x, b-y)) for l, t, r, b in targets)
    except Exception as exc:
        detail["region_error"] = type(exc).__name__
        return None
    finally:
        if region is not None:
            try:
                gui.DeleteObject(region)
            except Exception as exc:
                detail["region_cleanup_error"] = type(exc).__name__


def _blocker_identity(gui, hwnd, detail):
    """Best-effort manual-click diagnostics; no title, full path, cache or process IPC."""
    try:
        import win32api
        import win32process
        from pathlib import PureWindowsPath
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        detail["blocker_pid"] = pid
        handle = win32api.OpenProcess(0x1000, False, pid)
        try:
            basename = PureWindowsPath(win32process.QueryFullProcessImageName(handle, 0)).name
            same_pid = win32process.GetWindowThreadProcessId(hwnd)[1] == pid
        finally:
            handle.Close()
        if same_pid:
            detail["blocker_exe"] = basename[:128]
        else:
            detail.pop("blocker_pid", None)
            detail["identity_changed"] = True
    except Exception as exc:
        detail["identity_error"] = type(exc).__name__


def exposed(hwnd: int, local_rects: list, logical_size: tuple[int, int], *, diagnostic=None,
            diagnose=False) -> bool:
    # A caller-owned record avoids shared state between windows and automatic ticks.
    detail = diagnostic if diagnostic is not None else {}
    detail.clear()
    detail.update(stage="platform", hwnd=hwnd)
    if sys.platform != "win32":
        return False  # 렌더에서는 명시적으로 가짜 노출 판정을 주입한다.
    try:
        import ctypes
        from ctypes import wintypes
        import win32api
        import win32gui

        detail["stage"] = "input_desktop"
        if not desktop_unlocked():
            return False
        detail["stage"] = "owner_visibility"
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return False
        detail["stage"] = "target_geometry"
        client = win32gui.GetClientRect(hwnd)
        origin = win32gui.ClientToScreen(hwnd, (0, 0))
        sx, sy = client[2] / logical_size[0], client[3] / logical_size[1]
        targets = [(origin[0] + int(x * sx), origin[1] + int(y * sy),
                    origin[0] + int((x + w) * sx + .999),
                    origin[1] + int((y + h) * sy + .999)) for x, y, w, h in local_rects]
        detail.update(targets=targets, stage="monitor_coverage")
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
            detail.update(stage="window_state", other_hwnd=other)
            if not win32gui.IsWindowVisible(other) or win32gui.IsIconic(other):
                return True
            detail.update(stage="window_bounds", other_hwnd=other)
            bounds = wintypes.RECT()
            result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(other), 9, ctypes.byref(bounds), ctypes.sizeof(bounds))
            detail["bounds_hresult"] = int(result)
            cover = ((bounds.left, bounds.top, bounds.right, bounds.bottom) if result == 0
                     else win32gui.GetWindowRect(other))
            blocked = any(max(t[0], cover[0]) < min(t[2], cover[2])
                          and max(t[1], cover[1]) < min(t[3], cover[3]) for t in targets)
            if blocked:
                # Unrelated windows must not veto the target on a cloak-query failure.
                detail.update(stage="window_cloak", cover=cover)
                cloaked = wintypes.DWORD()
                result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    wintypes.HWND(other), 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
                detail["cloak_hresult"] = int(result)
                if result != 0:
                    return True
                if cloaked.value:
                    blocked = False
                    return True
                detail["stage"] = "occluded"
                # Flags alone do not prove transparency. Unknown/per-pixel
                # alpha stays conservative; only global alpha zero is ignored.
                try:
                    style = win32gui.GetWindowLong(other, -20)
                    detail["extended_style"] = style
                    detail["layered"] = bool(style & 0x80000)
                    if style & 0x80000:
                        _, alpha, flags = win32gui.GetLayeredWindowAttributes(other)
                        detail.update(alpha=alpha, alpha_flags=flags)
                        if flags & 2 and alpha == 0:
                            blocked = False
                except Exception as exc:
                    detail["alpha_error"] = type(exc).__name__
                if blocked and _region_overlap(win32gui, other, targets, detail) is False:
                    blocked = False
            return True

        detail["stage"] = "window_enumeration"
        win32gui.EnumWindows(visit, None)
        if blocked:
            try:
                detail["window_class"] = win32gui.GetClassName(detail["other_hwnd"])[:128]
            except Exception:
                pass
            if diagnose:
                _blocker_identity(win32gui, detail["other_hwnd"], detail)
        if not blocked:
            detail.clear()
            detail.update(stage="exposed" if found else "owner_not_enumerated", hwnd=hwnd)
        return found and not blocked
    except Exception as exc:  # 부가기능 판정 실패를 기존 트래커로 전파하지 않는다.
        detail["error"] = type(exc).__name__
        code = getattr(exc, "winerror", None)
        if isinstance(code, int):
            detail["winerror"] = code
        api = getattr(exc, "native_api", None)
        if api in {"OpenInputDesktop", "GetUserObjectInformationW"}:
            detail["native_api"] = api
        return False
