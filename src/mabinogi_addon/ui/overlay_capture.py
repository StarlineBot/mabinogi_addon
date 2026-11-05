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

from PySide6.QtCore import QEvent, QObject

# 게임 화면 위에 뜨는 우리 창(판독 영역과 겹칠 수 있음) — 상시 제외 대상
OVERLAYS = frozenset({
    "BuffOverlay", "MirrorOverlay", "ChunkOverlay", "MemoOverlay", "StatBarOverlay", "PatternWarningOverlay",
    "UpcomingPatternsOverlay", "DorchaOverlay", "FrameOverlay", "BlackboxToast", "Toast", "_GridGuide", "_FxWindow",
    "InquiryChip",  # 문의 자료 모으는 중 진행 표시(문의 일원화 6.2 4항 — 클릭 통과·판독 캡처 제외)
    "CooldownOverlay",  # 쿨타임 오버레이 한 줄(쿨타임 명세 10절 — 자기 자신을 원본으로 다시 찍지 않게)
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
    """오버레이 창에만 설치하는 필터(앱 전체가 아니라 — 0.37.1 Windows 검증: 앱 전체 Python 필터는 모든 이벤트마다
    불려 예외가 남은 상태에서 연쇄 오류를 냈다). 본문 전체를 try로 감싸 어떤 경우에도 이벤트를 막지 않는다."""

    def eventFilter(self, watched, event):
        try:
            if event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange):
                apply(watched)
            if event.type() == QEvent.Type.Show and watched not in _front:
                keep_cursor_front()  # 0.38.1: 다른 오버레이가 뜨면 커서 창을 다시 맨 앞으로
        except Exception:  # noqa: BLE001 — 캡처 제외 실패가 화면 표시를 막지 않게
            pass
        return False


_filter: _ShowFilter | None = None


def watch(widget) -> None:
    """오버레이 생성자에서 부른다. 이 창이 뜰 때마다(창 핸들이 바뀌어도) 캡처 제외를 건다."""
    global _filter
    try:
        if _filter is None:
            _filter = _ShowFilter()
        widget.installEventFilter(_filter)
    except Exception:  # noqa: BLE001
        pass


# ---- 0.38.1 마우스 커서 창은 우리 다른 '항상 위' 창보다 항상 앞 ----------------------------------------------
# 같은 '항상 위' 층에서는 나중에 뜨거나(show) 올려진(raise_) 창이 위라, 미러·오버레이가 다시 뜨면 커서를 덮었다.
# 오버레이가 뜰 때(위 Show 필터)·올려질 때(raise_overlay) 커서 창을 다시 맨 앞으로 — 커서 틱에서는 순서를 안 바꾼다.
import weakref  # noqa: E402

_front: "weakref.WeakSet" = weakref.WeakSet()
_pending = False


def keep_in_front(widget) -> None:
    """커서 창 등록(생성자에서)."""
    _front.add(widget)


def raise_overlay(widget) -> None:
    """오버레이 raise_() 대신 — 올린 뒤 커서 창을 다시 그 위로."""
    widget.raise_()
    keep_cursor_front()


def keep_cursor_front() -> None:
    """한 이벤트 루프 차례 뒤 한 번(여러 창이 한꺼번에 떠도 한 번만) 보이는 커서 창들을 맨 앞으로."""
    global _pending
    if _pending or not len(_front):
        return
    _pending = True
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, _bring_front)


def _bring_front() -> None:
    global _pending
    _pending = False
    from shiboken6 import isValid

    from ..system.zorder import bring_to_front
    for widget in list(_front):
        try:
            if isValid(widget) and widget.isVisible():
                bring_to_front(widget)
        except Exception:  # noqa: BLE001
            pass
