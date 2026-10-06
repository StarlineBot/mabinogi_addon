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

    def foreground_title(self) -> str:
        """현재 포그라운드 창 제목(진단용). 알 수 없으면 빈 문자열."""
        return ""


class AlwaysActiveWatcher(WindowWatcher):
    """맥/리눅스 개발용 — 게임이 항상 활성인 것으로 취급."""

    def is_game_active(self) -> bool:
        return True


class WindowsWatcher(WindowWatcher):
    """포그라운드 창이 우리 프로세스이거나 게임이면 활성."""

    def __init__(self, game_titles: tuple[str, ...] = DEFAULT_GAME_TITLES) -> None:
        self._titles = tuple(t.lower() for t in game_titles)
        self._own_pid = os.getpid()
        import win32gui  # noqa: F401  — 생성 시점에 사용 가능 여부 확인
        import win32process  # noqa: F401

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

    def foreground_title(self) -> str:
        try:
            return self._foreground()[0]
        except Exception:  # noqa: BLE001
            return ""

    def _classify(self) -> str:
        """'game' / 'self' / 'other'. 판정 실패 시 'game'으로(숨기지 않게)."""
        try:
            title, pid = self._foreground()
        except Exception:  # noqa: BLE001
            return "game"
        if pid == self._own_pid:
            return "self"
        low = title.lower()
        return "game" if any(t in low for t in self._titles) else "other"

    def is_game_active(self) -> bool:
        return self._classify() == "game"

    def is_self_active(self) -> bool:
        return self._classify() == "self"


def create_window_watcher(
    game_titles: tuple[str, ...] = DEFAULT_GAME_TITLES,
) -> WindowWatcher:
    """Windows면 WindowsWatcher, 아니면 AlwaysActiveWatcher."""
    if sys.platform == "win32":
        try:
            return WindowsWatcher(game_titles)
        except Exception:  # noqa: BLE001 — pywin32 없음 등
            return AlwaysActiveWatcher()
    return AlwaysActiveWatcher()
