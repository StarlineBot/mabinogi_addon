"""마우스 커서 위치 읽기(마우스 커서 명세 4절) — 읽기만 한다. 입력을 만들거나 옮기지 않는다.

Qt `QCursor.pos()`는 Windows에서 `GetCursorPos`를 불러 화면 배율(DPI)에 맞춘 논리 좌표로 돌려준다.
오버레이 창도 같은 논리 좌표로 놓이므로 이 값을 그대로 쓴다(직접 `GetCursorPos`를 부르면 물리 좌표라
모니터마다 배율 환산이 필요하다). 맥·리눅스에서도 같은 함수로 렌더·테스트한다.
"""

from __future__ import annotations


def cursor_pos() -> tuple[int, int]:
    from PySide6.QtGui import QCursor

    p = QCursor.pos()
    return p.x(), p.y()


def exclude_from_capture(widget) -> bool:
    """커서 효과 창을 화면 캡처에서 뺀다(Windows 10 2004+ `WDA_EXCLUDEFROMCAPTURE`).
    원·꼬리가 버프·디버프 판독 영역 위를 지나가도 판독 그림에 섞이지 않게 한다(진짜 커서도 캡처에 안 찍힌다).
    다른 OS·실패 시 False(표시는 그대로)."""
    import sys

    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), 0x11))
    except Exception:  # noqa: BLE001 — 옛 Windows 등
        return False
