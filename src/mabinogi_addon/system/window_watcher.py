"""포그라운드 감지 (기획서 3.4 / 4.7).

마비노기가 활성(포그라운드)일 때만 오버레이를 보여주기 위한 인터페이스.
자기 프로그램 창(설정 창·편집 모드 오버레이)도 '활성'으로 간주한다.

- WindowsWatcher: 현재 포그라운드 창의 프로세스·제목으로 판정(Windows 전용).
- AlwaysActiveWatcher: 맥/리눅스 개발용 — 항상 활성.

event hook(SetWinEventHook) 대신 폴링으로 구현한다: 이미 200ms 주기로 도는
캡처 워커 안에서 호출하면 되고, 메시지 루프가 필요 없어 스레드에서 안전하다.
"""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod

# 포그라운드 창 제목에 이 중 하나가 들어가면 '게임 활성'으로 본다(대소문자 무시).
DEFAULT_GAME_TITLES = ("mabinogi", "마비노기")


def is_main_window_foreground(hwnd: int, *, diagnostic=None) -> bool:
    """Read exact foreground HWND and ownership; never use the game-active fallback.

    Same-process editor overlays are intentionally excluded. Recheck current
    foreground and PID instead of retaining a process/window identity cache.
    """
    detail = {} if diagnostic is None else diagnostic
    detail.clear()
    detail["foreground"] = "unavailable"
    if sys.platform != "win32":
        return False
    try:
        import win32gui
        import win32process

        foreground = win32gui.GetForegroundWindow()
        if not hwnd or not foreground or not win32gui.IsWindow(hwnd) or not win32gui.IsWindow(foreground):
            return False
        if foreground != hwnd:
            detail["foreground"] = "other"
            return False
        own = os.getpid()
        if win32process.GetWindowThreadProcessId(hwnd)[1] != own:
            return False
        if (win32gui.GetForegroundWindow() != hwnd or not win32gui.IsWindow(hwnd)
                or win32process.GetWindowThreadProcessId(hwnd)[1] != own):
            return False
        detail["foreground"] = "main"
        return True
    except Exception as exc:
        detail["foreground_error"] = type(exc).__name__
        return False


class WindowWatcher(ABC):
    def is_active(self) -> bool:
        """게임 또는 자기 앱이 포그라운드인지(기존 호환)."""
        return self.is_game_active() or self.is_self_active()

    @abstractmethod
    def is_game_active(self) -> bool:
        """포그라운드가 게임(마비노기)인지."""

    def is_self_active(self) -> bool:
        """포그라운드가 우리 앱 창인지(편집 중 오버레이 유지에 사용)."""
        return False

    def foreground_info(self) -> tuple[str, str]:
        """현재 포그라운드 창의 (제목, 실행파일명). 자동 찾기·진단용."""
        return "", ""

    def set_game_exe(self, exe: str | None) -> None:
        """게임으로 볼 실행파일명(basename). None/빈값이면 제목 기반 폴백."""


class AlwaysActiveWatcher(WindowWatcher):
    """맥/리눅스 개발용 — 게임이 항상 활성인 것으로 취급."""

    def is_game_active(self) -> bool:
        return True


def _exe_basename_of_pid(pid: int) -> str:
    """pid의 실행파일 basename(소문자). 실패 시 빈 문자열. Windows 전용(ctypes)."""
    if not pid:
        return ""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.replace("/", "\\").split("\\")[-1].lower()
        return ""
    finally:
        k32.CloseHandle(handle)


def list_windows() -> list[tuple[str, str]]:
    """현재 보이는 top-level 창의 (제목, 실행파일) 목록. Windows 전용(아니면 빈 목록).

    시작 시 '게임 창 선택' 팝업에서 목록으로 고르게 하는 용도. 제목이 빈 창·우리 앱
    창은 제외하고, (제목, exe) 중복은 합친다.
    """
    if sys.platform != "win32":
        return []
    try:
        import win32gui
        import win32process
    except Exception:  # noqa: BLE001 — pywin32 없음
        return []

    own = os.getpid()
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _cb(hwnd: int, _extra: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        if not title:
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:  # noqa: BLE001
            pid = 0
        if not pid or pid == own:
            return True
        exe = _exe_basename_of_pid(pid)
        if not exe:
            return True
        key = (title, exe)
        if key not in seen:
            seen.add(key)
            out.append(key)
        return True  # 계속 열거

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:  # noqa: BLE001
        return out
    return out


class WindowsWatcher(WindowWatcher):
    """포그라운드 창을 프로세스(실행파일)로 판정. 미등록 시 제목으로 폴백.

    실행파일 기반이라 '마비노기'라는 이름의 폴더(탐색기) 창은 explorer.exe라서
    게임으로 오판하지 않는다. 사용자가 '자동 찾기'로 게임 실행파일을 등록하면 그걸 쓴다.
    """

    def __init__(
        self,
        game_titles: tuple[str, ...] = DEFAULT_GAME_TITLES,
        game_exe: str | None = None,
    ) -> None:
        self._titles = tuple(t.lower() for t in game_titles)
        self._game_exe = (game_exe or "").lower() or None
        self._own_pid = os.getpid()
        import win32gui  # noqa: F401  — 생성 시점에 사용 가능 여부 확인
        import win32process  # noqa: F401

    def set_game_exe(self, exe: str | None) -> None:
        self._game_exe = (exe or "").lower() or None

    def _foreground(self) -> tuple[str, int]:
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "", 0
        title = win32gui.GetWindowText(hwnd) or ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:  # noqa: BLE001
            pid = 0
        return title, pid

    def foreground_info(self) -> tuple[str, str]:
        try:
            title, pid = self._foreground()
            return title, _exe_basename_of_pid(pid)
        except Exception:  # noqa: BLE001
            return "", ""

    def _classify(self) -> str:
        """'game' / 'self' / 'other'. 판정 실패 시 'game'으로(숨기지 않게)."""
        try:
            title, pid = self._foreground()
        except Exception:  # noqa: BLE001
            return "game"
        if pid == self._own_pid:
            return "self"
        if self._game_exe:  # 등록된 실행파일이 있으면 그걸로 판정(정확)
            return "game" if _exe_basename_of_pid(pid) == self._game_exe else "other"
        low = title.lower()  # 폴백: 제목 매칭(폴더 창 등 오판 가능)
        return "game" if any(t in low for t in self._titles) else "other"

    def is_game_active(self) -> bool:
        return self._classify() == "game"

    def is_self_active(self) -> bool:
        return self._classify() == "self"


def create_window_watcher(
    game_titles: tuple[str, ...] = DEFAULT_GAME_TITLES,
    game_exe: str | None = None,
) -> WindowWatcher:
    """Windows면 WindowsWatcher, 아니면 AlwaysActiveWatcher."""
    if sys.platform == "win32":
        try:
            return WindowsWatcher(game_titles, game_exe)
        except Exception:  # noqa: BLE001 — pywin32 없음 등
            return AlwaysActiveWatcher()
    return AlwaysActiveWatcher()
