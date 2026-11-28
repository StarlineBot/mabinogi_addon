"""펫 창 진단(QA 11-28 — 사용자 제보 '게임에서 알트탭하면 캐릭터도 사라짐', 간헐·재현 안 됨).

게임 앞/뒤가 바뀔 때 펫 창이 Windows에서 실제로 어떤 상태인지(보임·최소화·맨 위·겹친 창)를 읽는다. 읽기만 한다.
맥/리눅스나 실패하면 {"win32": "없음"} 같은 짧은 값.
"""
from __future__ import annotations

import os
import sys

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000


def probe(hwnd: int, point: tuple[int, int], api=None) -> dict:
    """hwnd 펫 창, point 펫 가운데(물리 px 화면 좌표). api는 테스트용 가짜(win32gui·win32process 같은 함수들)."""
    if api is None:
        if sys.platform != "win32":
            return {"win32": "없음"}
        try:
            import win32gui
            import win32process

            class _Api:
                IsWindowVisible = staticmethod(win32gui.IsWindowVisible)
                IsIconic = staticmethod(win32gui.IsIconic)
                GetWindowLong = staticmethod(win32gui.GetWindowLong)
                WindowFromPoint = staticmethod(win32gui.WindowFromPoint)
                GetAncestor = staticmethod(win32gui.GetAncestor)
                GetClassName = staticmethod(win32gui.GetClassName)
                GetWindowThreadProcessId = staticmethod(win32process.GetWindowThreadProcessId)
            api = _Api
        except Exception as exc:  # noqa: BLE001 — 진단은 앱을 멈추지 않음
            return {"win32": f"오류 {type(exc).__name__}"}
    out: dict = {}
    try:
        out["visible"] = bool(api.IsWindowVisible(hwnd))
        out["iconic"] = bool(api.IsIconic(hwnd))
        ex = int(api.GetWindowLong(hwnd, GWL_EXSTYLE))
        out["topmost"] = bool(ex & WS_EX_TOPMOST)
        out["layered"] = bool(ex & WS_EX_LAYERED)
        out["toolwindow"] = bool(ex & WS_EX_TOOLWINDOW)
        hit = int(api.WindowFromPoint(point) or 0)
        top = int(api.GetAncestor(hit, 2) or hit) if hit else 0   # GA_ROOT
        pid = int(api.GetWindowThreadProcessId(top)[1]) if top else 0
        out["at_center"] = {"ours": top == hwnd, "pid": pid, "own_pid": pid == os.getpid(),
                            "class": api.GetClassName(top) if top else ""}
    except Exception as exc:  # noqa: BLE001
        out["error"] = type(exc).__name__
    return out


def line(info: dict) -> str:
    """한 줄 기록(app.log '[펫 창]') — key=value를 정해진 순서로."""
    order = ("why", "after", "shown", "logical", "physical", "screen", "win32", "state", "pos", "goal", "blocked",
             "fg_before", "fg_now")
    parts = [f"{k}={info[k]}" for k in order if k in info]
    parts += [f"{k}={v}" for k, v in info.items() if k not in order]
    return "[펫 창] " + " ".join(parts)
