"""게임 창 중 다른 창에 가려지지 않고 보이는 부분(Windows 전용, QA 11-26 펫 '보이는 게임 화면 피하기').

진짜 창모드에서 게임이 포그라운드가 아니어도 화면에 보이는 게임 창 위로 펫이 지나가지 않게, 보이는 사각형을 구한다.
- 게임 창: 등록 실행파일(없으면 제목 폴백 — window_watcher와 같은 규칙)의 보이는 top-level 창 중 가장 큰 것. 최소화·숨김·cloaked 제외.
- 영역은 DWMWA_EXTENDED_FRAME_BOUNDS(그림자 제외). Z 순서에서 그보다 위의 보이는 창 영역을 뺀다
  (우리 앱 창, cloaked 창, 클릭 통과 투명 오버레이 WS_EX_TRANSPARENT+LAYERED는 가리지 않는 것으로).
- 주 화면 안으로 자른 물리 px (left, top, right, bottom) 목록. 판정 실패면 None(호출 쪽이 '막힌 곳 없음'으로).
화면을 읽기만 한다(키·클릭 없음). 1초에 한 번, 게임이 포그라운드가 아닐 때만 부른다.
"""
from __future__ import annotations

import sys

from .dialogue_visibility import subtract

WS_EX_TRANSPARENT, WS_EX_LAYERED = 0x20, 0x80000
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14


def _bounds(win32gui, ctypes, wintypes, hwnd):
    rect = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                                                  ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
        return rect.left, rect.top, rect.right, rect.bottom
    return tuple(win32gui.GetWindowRect(hwnd))


def _cloaked(ctypes, wintypes, hwnd) -> bool:
    value = wintypes.DWORD()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED,
                                                        ctypes.byref(value), ctypes.sizeof(value))
    return result == 0 and bool(value.value)


def _clip(rect, area):
    l, t, r, b = max(rect[0], area[0]), max(rect[1], area[1]), min(rect[2], area[2]), min(rect[3], area[3])
    return (l, t, r, b) if l < r and t < b else None


def visible_game_rects(game_exe: str | None, titles: tuple[str, ...], own_pid: int) -> list[tuple] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        import win32api
        import win32gui
        import win32process

        from .window_watcher import _exe_basename_of_pid, is_game_title

        order: list[int] = []
        win32gui.EnumWindows(lambda h, _: order.append(h) or True, None)   # 위(앞) 창부터
        exes: dict[int, str] = {}

        def exe_of(pid):
            if pid not in exes:
                exes[pid] = _exe_basename_of_pid(pid)
            return exes[pid]

        def shown(h):
            return win32gui.IsWindowVisible(h) and not win32gui.IsIconic(h) and not _cloaked(ctypes, wintypes, h)

        game, best = None, 0
        for index, h in enumerate(order):
            if not shown(h):
                continue
            pid = win32process.GetWindowThreadProcessId(h)[1]
            if not pid or pid == own_pid:
                continue
            if game_exe:
                hit = exe_of(pid) == game_exe
            else:
                title = win32gui.GetWindowText(h) or ""
                hit = any(t in title.lower() for t in titles) and is_game_title(title, exe_of(pid), titles)
            if not hit:
                continue
            rect = _bounds(win32gui, ctypes, wintypes, h)
            area = max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])
            if area > best:
                game, best = (index, rect), area
        if game is None:
            return []
        index, rect = game
        monitor = win32api.GetMonitorInfo(win32api.MonitorFromPoint((0, 0), 1))["Monitor"]   # 주 화면(펫 바닥과 같은 화면)
        start = _clip(rect, monitor)
        pieces = [start] if start else []
        for h in order[:index]:
            if not pieces:
                break
            if not shown(h) or win32process.GetWindowThreadProcessId(h)[1] == own_pid:
                continue
            style = win32gui.GetWindowLong(h, -20)
            if style & WS_EX_TRANSPARENT and style & WS_EX_LAYERED:   # 클릭 통과 투명 오버레이(다른 앱 HUD 등)
                continue
            cover = _bounds(win32gui, ctypes, wintypes, h)
            if cover[2] <= cover[0] or cover[3] <= cover[1]:
                continue
            pieces = [p for piece in pieces for p in subtract(piece, cover)]
        return pieces
    except Exception:  # noqa: BLE001 — 권한·API 오류는 '막힌 곳 없음'(지금 동작 그대로)
        return None
