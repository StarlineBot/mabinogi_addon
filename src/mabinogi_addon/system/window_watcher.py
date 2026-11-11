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

# 제목에 '마비노기'가 있어도 게임이 아닌 프로그램(0.46.0, #221 실측: '마비노기 - 나무위키' 크롬 탭에 오버레이가 뜸).
# 게임창 미등록일 때의 제목 폴백·게임창 등록·받은 설정의 gameExe 검사에 같이 쓴다.
NOT_GAME_EXES = frozenset({
    "chrome.exe", "msedge.exe", "whale.exe", "firefox.exe", "opera.exe", "brave.exe",  # 브라우저
    "explorer.exe",  # 탐색기('마비노기' 폴더 창)
    "discord.exe", "kakaotalk.exe",  # 메신저('마비노기 길드' 채널 창)
})
APP_EXE = "mabinogi-addon.exe"  # 이 앱 배포본 실행파일 — 앱 자신을 게임으로 등록하지 않게


def _own_exe() -> str:
    return os.path.basename(sys.executable).lower() if getattr(sys, "frozen", False) else APP_EXE


def is_acceptable_game_exe(exe: str | None) -> bool:
    """게임 실행파일로 등록해도 되는 이름인지(빈 값·제외 목록·앱 자신이면 False). 순수 함수."""
    low = (exe or "").strip().lower()
    return bool(low) and low not in NOT_GAME_EXES and low not in (APP_EXE, _own_exe())


def is_game_title(title: str, exe: str | None, titles: tuple[str, ...] = DEFAULT_GAME_TITLES) -> bool:
    """게임창 미등록 때 쓰는 제목 폴백 판단: 제목에 '마비노기'가 있고 제외 프로그램이 아니면 게임.
    exe를 못 읽었으면(빈 값) 예전처럼 제목만 본다. 순수 함수(맥에서 테스트)."""
    low = (title or "").lower()
    if not any(t.lower() in low for t in titles):
        return False
    return not exe or is_acceptable_game_exe(exe)


def is_game_window(title: str, exe: str | None, pid: int = 0, own_pid: int | None = None,
                   titles: tuple[str, ...] = DEFAULT_GAME_TITLES) -> bool:
    """떠 있는 창이 '마비노기 게임 창'으로 보이는지: 앱 자신 아님 + 제목 마비노기 + 제외 목록 아님(실행파일 필요)."""
    if pid and pid == (os.getpid() if own_pid is None else own_pid):
        return False
    return bool(exe) and is_game_title(title, exe, titles)


def find_running_game(windows: list[tuple[str, str]], titles: tuple[str, ...] = DEFAULT_GAME_TITLES) -> str | None:
    """list_windows() 결과에서 게임 창 실행파일이 딱 하나면 그 이름, 없거나 둘 이상이면 None."""
    found = {exe.lower() for title, exe in windows if is_game_window(title, exe, titles=titles)}
    return found.pop() if len(found) == 1 else None


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

    등록된 실행파일이 있으면 그걸로만 판정한다. 미등록이면 제목 폴백(is_game_title) — 제목에 '마비노기'가
    있어도 브라우저·탐색기·메신저(NOT_GAME_EXES)와 앱 자신은 게임이 아니다.
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
        # 폴백: 제목 매칭 + 브라우저·탐색기·메신저 제외(실행파일을 못 읽으면 제목만)
        exe = _exe_basename_of_pid(pid) if any(t in title.lower() for t in self._titles) else ""
        return "game" if is_game_title(title, exe, self._titles) else "other"

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
