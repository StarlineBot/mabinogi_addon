"""우리 오버레이 창을 화면 캡처에서 항상 빼기(0.37.1 사용자 결정 — 설정 스위치 없음).

오버레이를 사용자가 어디에 둘지 모르므로, 위치와 무관하게 판독(dxcam·mss 캡처)은 게임 화면만 읽어야 한다.
오버레이 창이 화면에 뜰 때(Show 이벤트)마다 `WDA_EXCLUDEFROMCAPTURE`를 건다 — 창 핸들이 다시 만들어져도 다시 건다.
판독·블랙박스·방송·스크린샷 모두 오버레이가 안 찍힌다(사용자 허용).
메인 창·대화상자·영역 지정 화면은 대상이 아니다(사용자 스크린샷용). Windows 10 2004 미만은 아무것도 하지 않는다 —
그 경우를 위해 보스·헤일로·도르카의 캡처 순간 제외(CaptureGuard·excluding_windows)는 남겨 둔다(이미 제외된 창은 건너뜀).

**오버레이 목록은 여기 한 곳에서 관리한다.** 항상 위에 뜨는 창을 새로 만들면 OVERLAYS나 NOT_OVERLAYS 중 하나에
이름을 넣어야 한다(`tests/test_overlay_capture.py`가 빠진 창을 찾는다).
"""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject

# 게임 화면 위에 뜨는 우리 창(판독 영역과 겹칠 수 있음) — 상시 제외 대상
OVERLAYS = frozenset({
    "BuffOverlay", "MirrorOverlay", "ChunkOverlay", "MemoOverlay", "StatBarOverlay", "PatternWarningOverlay",
    "UpcomingPatternsOverlay", "DorchaOverlay", "FrameOverlay", "BlackboxToast", "Toast", "_GridGuide", "_FxWindow",
})
# 항상 위에 뜨지만 오버레이가 아닌 창 — 영역 지정·안내·시작 화면(사용자가 캡처해 보낼 수 있어야 함)
NOT_OVERLAYS = frozenset({"RegionSelector", "TopEdgeSelector", "RegionHighlight", "Splash", "TourOverlay"})


def is_overlay(widget) -> bool:
    return widget.isWindow() and any(cls.__name__ in OVERLAYS for cls in type(widget).__mro__)


def available() -> bool:
    from ..system import capture_exclusion

    return capture_exclusion.available()


def apply(widget) -> bool:
    """오버레이 하나를 캡처에서 뺀다. 걸었으면 True."""
    from ..system import capture_exclusion

    if not available() or not is_overlay(widget):
        return False
    return capture_exclusion.set_excluded(int(widget.winId()), True)


class _ShowFilter(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.applied = weakref.WeakSet()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange):
            try:
                if hasattr(watched, "isWindow") and is_overlay(watched):
                    apply(watched)
                    self.applied.add(watched)
            except Exception:  # noqa: BLE001 — 캡처 제외 실패가 화면 표시를 막지 않게
                pass
        return False


_filter: _ShowFilter | None = None


def install(app) -> None:
    """앱 전체에 한 번 설치(메인 창 생성 때). 이후 뜨는 오버레이마다 자동 적용."""
    global _filter
    if _filter is None:
        _filter = _ShowFilter()
        app.installEventFilter(_filter)
