"""해외(영문 제목) 마비노기 클라이언트 보호(사용자 결정 2026-11-18) — 그 게임 프로세스는 열지 않는다.

NA 사용자가 애드온만 켠 상태에서 두 번 NA 보안 프로그램에 게임이 끊겼다(원인 기능 미확정). 가장 유력한 후보는
게임 프로세스를 여는 코드(OpenProcess — 실행 파일 이름 확인·최적화·FPS·블랙박스) → 해외 게임 창의 프로세스는 열지 않는다.
화면 캡처(바탕화면 복사)·판독은 그대로.

어떻게:
- 창 목록(EnumWindows)에서 제목·창 클래스·pid만 읽는다(GetWindowText·GetClassName·GetWindowThreadProcessId —
  프로세스를 열지 않음). 제목이 해외(`is_overseas_title`)이고 브라우저·탐색기 같은 창 클래스가 아니면 해외 게임 창.
- 그 pid는 '보호 pid' — 프로세스를 여는 곳(실행 파일 이름 확인 등)은 먼저 `is_protected_pid`를 묻고 열지 않는다.
- 한 번이라도 해외 게임 창을 보면 이번 실행 동안 `active()` — 최적화·FPS·블랙박스는 시작하지 않는다.
- 한국 클라이언트('마비노기' 제목)만 있으면 아무것도 바뀌지 않는다.
"""
from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Iterable

from .window_watcher import is_overseas_title

SCAN_SECONDS = 2.0  # 창 목록을 다시 훑는 간격(수 ms) — 게임을 나중에 켜도 2초 안에 보호
# 제목에 'Mabinogi'가 있어도 게임이 아닌 창(실행 파일을 열지 않고 창 클래스로만 가린다)
NOT_GAME_CLASSES = frozenset({
    "Chrome_WidgetWin_0", "Chrome_WidgetWin_1",  # 크롬·엣지·웨일·브레이브·디스코드·카카오톡 등 크로미엄 계열
    "MozillaWindowClass",  # 파이어폭스
    "CabinetWClass", "ExploreWClass",  # 탐색기
    "ApplicationFrameWindow",  # UWP 앱
    "Notepad", "OperaWindowClass",
})

_lock = threading.Lock()
_pids: set[int] = set()
_window: tuple[int, int] | None = None   # 마지막으로 본 해외 게임 창 (hwnd, pid)
_active = False
_scanned_at = float("-inf")


def is_overseas_game_window(title: str | None, window_class: str | None) -> bool:
    """해외 게임 창인지 — 제목이 해외이고 게임이 아닌 창 클래스가 아님. 순수 함수."""
    return is_overseas_title(title) and (window_class or "") not in NOT_GAME_CLASSES


def _enum_windows() -> Iterable[tuple[int, str, str, int]]:
    """보이는 최상위 창 (hwnd, 제목, 창 클래스, pid). 프로세스는 열지 않는다. Windows가 아니면 없음."""
    if sys.platform != "win32":
        return []
    try:
        import win32gui
        import win32process
    except Exception:  # noqa: BLE001 — pywin32 없음
        return []
    out = []

    def _cb(hwnd, _extra):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd) or ""
            if not is_overseas_title(title):
                return True  # 해외 제목만 클래스·pid를 읽는다
            out.append((hwnd, title, win32gui.GetClassName(hwnd) or "", win32process.GetWindowThreadProcessId(hwnd)[1]))
        except Exception:  # noqa: BLE001, S110 — 창 하나 실패는 건너뜀
            pass
        return True
    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:  # noqa: BLE001, S110
        pass
    return out


def scan(enum: Callable[[], Iterable[tuple[int, str, str, int]]] | None = None,
         now: float | None = None) -> bool:
    """창 목록을 훑어 해외 게임 창의 pid를 보호 목록에 더한다. 이번 실행에서 해외 게임 창을 본 적 있으면 True."""
    global _window, _active, _scanned_at
    rows = list((enum or _enum_windows)())
    with _lock:
        _scanned_at = time.monotonic() if now is None else now
        current = None
        for hwnd, title, window_class, pid in rows:
            if pid and is_overseas_game_window(title, window_class):
                _pids.add(int(pid))
                current = current or (int(hwnd), int(pid))
                _active = True
        _window = current  # 지금 떠 있는 해외 게임 창(닫히면 None — 보호 pid·active는 이번 실행 동안 유지)
        return _active


def protect(pid, hwnd=None) -> None:
    """창을 찾은 쪽이 북미 게임 창이라고 본 그 순간 pid를 보호 등록(다음 훑기를 기다리지 않음 — QA 5fbb5f09 ①)."""
    global _window, _active
    if not pid:
        return
    with _lock:
        _pids.add(int(pid))
        _active = True
        if hwnd:
            _window = (int(hwnd), int(pid))


def _refresh() -> None:
    with _lock:
        stale = time.monotonic() - _scanned_at >= SCAN_SECONDS
    if stale:
        scan()


def is_protected_pid(pid) -> bool:
    """이 pid가 해외 게임 창의 프로세스인지(열면 안 됨). 창 목록은 SCAN_SECONDS마다 다시 훑는다."""
    if not pid:
        return False
    _refresh()
    with _lock:
        return int(pid) in _pids


def active() -> bool:
    """이번 실행에서 해외 게임 창을 봤는지 — 최적화·FPS·블랙박스를 시작하지 않는다."""
    _refresh()
    with _lock:
        return _active


def game_window() -> tuple[int, int] | None:
    """지금 떠 있는 북미 게임 창 (hwnd, pid) — 판독 기능이 창 위치를 잡을 때(프로세스는 열지 않음)."""
    _refresh()
    with _lock:
        return _window


def reset_for_tests() -> None:
    global _window, _active, _scanned_at
    with _lock:
        _pids.clear()
        _window, _active, _scanned_at = None, False, float("-inf")
