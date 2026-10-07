"""DWM 썸네일(미러) — Windows 컴포지터에게 복사를 맡기는 저부하 미러 (기획서 3.6).

mss로 매 프레임 전체화면을 CPU 캡처→변환→그리기 하면 60fps에서 CPU가 계속 돈다.
대신 Windows의 DWM Thumbnail API(`DwmRegisterThumbnail`)로 "이 소스 창의 이 영역을
내 오버레이 창에 실시간으로 비춰줘"라고 **등록만** 하면, 이후 매 프레임 복사는 OS의
컴포지터(GPU)가 한다. 앱은 창이 움직일 때만 사각형을 갱신하면 되므로 CPU ~0%, 또
디스플레이 주사율로 합성돼 끊김이 없다.

읽기 전용 원칙 준수: 화면(소스 창)을 비추기만 하며 입력을 만들지 않는다.
Windows 전용. 다른 OS에서는 import는 되지만 `available()`이 False이고, 호출 측은
기존 mss 미러로 폴백한다.
"""

from __future__ import annotations

import sys

# DWM_TNP_* 플래그(갱신할 속성 선택)
DWM_TNP_RECTDESTINATION = 0x00000001
DWM_TNP_RECTSOURCE = 0x00000002
DWM_TNP_OPACITY = 0x00000004
DWM_TNP_VISIBLE = 0x00000008
DWM_TNP_SOURCECLIENTAREAONLY = 0x00000010


def available() -> bool:
    """이 환경에서 DWM 썸네일을 쓸 수 있는지(Windows + dwmapi 로드 가능)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        ctypes.windll.dwmapi  # noqa: B018 — 로드 가능 여부만 확인
        import win32gui  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _structs():
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class DWM_THUMBNAIL_PROPERTIES(ctypes.Structure):
        _fields_ = [
            ("dwFlags", wintypes.DWORD),
            ("rcDestination", RECT),
            ("rcSource", RECT),
            ("opacity", ctypes.c_ubyte),
            ("fVisible", wintypes.BOOL),
            ("fSourceClientAreaOnly", wintypes.BOOL),
        ]

    return RECT, DWM_THUMBNAIL_PROPERTIES


def find_game_window(exe: str | None, titles: tuple[str, ...]) -> int:
    """게임 최상위 창 HWND를 찾는다(보이는 창만). 못 찾으면 0.

    exe(실행파일 basename)가 있으면 그 프로세스의 창을, 없으면 제목 매칭으로.
    포그라운드가 아니어도 찾을 수 있게 EnumWindows로 전수 조사한다.
    """
    if sys.platform != "win32":
        return 0
    try:
        import win32gui
        import win32process

        from .window_watcher import _exe_basename_of_pid
    except Exception:  # noqa: BLE001
        return 0

    exe = (exe or "").lower() or None
    low_titles = tuple(t.lower() for t in titles)
    found: list[int] = []

    def _cb(hwnd, _lparam):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = (win32gui.GetWindowText(hwnd) or "").lower()
        if exe:
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:  # noqa: BLE001
                return True
            if _exe_basename_of_pid(pid) == exe:
                found.append(hwnd)
                return False  # 중단
        elif any(t in title for t in low_titles):
            found.append(hwnd)
            return False
        return True

    try:
        win32gui.EnumWindows(_cb, 0)
    except Exception:  # noqa: BLE001, S110 — 콜백 중단(False 반환)도 예외로 올 수 있음
        pass
    return found[0] if found else 0


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """창의 화면 좌표 사각형 (left, top, right, bottom). 실패 시 None."""
    if not hwnd:
        return None
    try:
        import win32gui

        return win32gui.GetWindowRect(hwnd)
    except Exception:  # noqa: BLE001
        return None


class Thumbnail:
    """목적지 창(우리 오버레이)에 소스 창(게임)의 한 영역을 실시간 미러.

    register() 후 update_rects()로 소스/목적지 사각형을 지정한다. 소스 사각형은
    '화면 좌표 영역'을 받아, 소스 창의 현재 위치를 빼서 창-상대 좌표로 변환한다
    (게임 창이 움직여도 같은 화면 영역을 따라가게 하려면 주기적으로 다시 호출).
    """

    def __init__(self) -> None:
        self._dwm = None
        self._handle = None
        self._dest = 0
        self._src = 0

    def register(self, dest_hwnd: int, src_hwnd: int) -> bool:
        """목적지(오버레이)·소스(게임) 창을 연결. 성공 True."""
        if not available() or not dest_hwnd or not src_hwnd:
            return False
        import ctypes
        from ctypes import wintypes

        dwm = ctypes.windll.dwmapi
        # HWND·핸들은 포인터 크기 → argtypes를 c_void_p로 명시하지 않으면 64비트에서
        # 값이 잘려(기본 c_int) 잘못된 핸들이 넘어간다.
        dwm.DwmRegisterThumbnail.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.POINTER(ctypes.c_void_p)
        ]
        dwm.DwmRegisterThumbnail.restype = ctypes.c_long
        dwm.DwmUpdateThumbnailProperties.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        dwm.DwmUpdateThumbnailProperties.restype = ctypes.c_long
        dwm.DwmUnregisterThumbnail.argtypes = [ctypes.c_void_p]
        dwm.DwmUnregisterThumbnail.restype = ctypes.c_long

        handle = ctypes.c_void_p()
        hr = dwm.DwmRegisterThumbnail(
            wintypes.HWND(dest_hwnd), wintypes.HWND(src_hwnd), ctypes.byref(handle)
        )
        if hr != 0 or not handle.value:
            return False
        self._dwm = dwm
        self._handle = handle
        self._dest = dest_hwnd
        self._src = src_hwnd
        return True

    def update(
        self,
        src_rect_rel: tuple[int, int, int, int],
        dest_rect: tuple[int, int, int, int],
        *,
        visible: bool = True,
        opacity: int = 255,
    ) -> bool:
        """소스 영역(소스 창 상대 l,t,r,b)·목적지 사각형(오버레이 상대 x,y,w,h)로 갱신.

        소스 영역은 '게임 창 기준' 상대 좌표라, 게임 창이 움직여도 같은 인게임
        요소를 가리킨다. 창 경계를 벗어나는 부분은 clamp한다. 성공 True.
        """
        if self._handle is None or self._dwm is None:
            return False
        import ctypes

        rect = window_rect(self._src)
        if rect is None:
            return False
        wl, wt, wr, wb = rect
        ww, wh = wr - wl, wb - wt
        l, t, r, b = src_rect_rel
        l = max(0, min(l, ww))
        t = max(0, min(t, wh))
        r = max(0, min(r, ww))
        b = max(0, min(b, wh))
        if r <= l or b <= t:
            return False

        RECT, PROPS = _structs()
        dx, dy, dw, dh = dest_rect
        props = PROPS()
        props.dwFlags = (
            DWM_TNP_RECTDESTINATION
            | DWM_TNP_RECTSOURCE
            | DWM_TNP_OPACITY
            | DWM_TNP_VISIBLE
        )
        props.rcDestination = RECT(int(dx), int(dy), int(dx + dw), int(dy + dh))
        props.rcSource = RECT(int(l), int(t), int(r), int(b))
        props.opacity = max(0, min(255, int(opacity)))
        props.fVisible = 1 if visible else 0
        props.fSourceClientAreaOnly = 0
        hr = self._dwm.DwmUpdateThumbnailProperties(self._handle, ctypes.byref(props))
        return hr == 0

    def set_visible(self, visible: bool) -> None:
        if self._handle is None or self._dwm is None:
            return
        import ctypes

        _, PROPS = _structs()
        props = PROPS()
        props.dwFlags = DWM_TNP_VISIBLE
        props.fVisible = 1 if visible else 0
        self._dwm.DwmUpdateThumbnailProperties(self._handle, ctypes.byref(props))

    def unregister(self) -> None:
        if self._handle is not None and self._dwm is not None:
            try:
                self._dwm.DwmUnregisterThumbnail(self._handle)
            except Exception:  # noqa: BLE001, S110
                pass
        self._handle = None
        self._dest = 0
        self._src = 0
