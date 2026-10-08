"""DPI(디스플레이 배율) 좌표 변환.

Qt6은 기본이 per-monitor DPI aware라, 영역 선택(RegionSelector)이 돌려주는 좌표는
**논리좌표**다(예: 4K@150%면 화면이 2560×1440 논리). 반면 화면 캡처(dxcam·mss)는
실제 프레임버퍼의 **물리픽셀**(3840×2160)을 쓴다. 배율 100%(dpr=1)면 둘이 같아 문제가
없지만, 150%면 1.5배 어긋나 "영역이 이상하게 잡힌다".

그래서 **캡처에 넘기기 직전에만** 논리→물리로 변환한다(메모 오버레이 위치처럼 Qt로
그리는 좌표는 논리 그대로 둬야 하므로 전역 변환은 하지 않는다).
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication


def screen_scale() -> float:
    """주 화면의 devicePixelRatio(배율). 화면이 없으면 1.0."""
    s = QGuiApplication.primaryScreen()
    return float(s.devicePixelRatio()) if s is not None else 1.0


def to_physical(region: dict) -> tuple[int, int, int, int]:
    """논리좌표 영역 dict(x,y,w,h) → 물리픽셀 (x, y, w, h). 배율 100%면 그대로."""
    s = screen_scale()
    return (
        round(region["x"] * s),
        round(region["y"] * s),
        round(region["w"] * s),
        round(region["h"] * s),
    )
