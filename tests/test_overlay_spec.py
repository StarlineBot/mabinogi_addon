from mabinogi_addon.tracker.engine import OverlayEntry
from mabinogi_addon.ui.overlay import overlay_spec


def test_spec_maps_time_and_warn():
    """임박여부(세 번째 값)는 '남은 시간 1분 미만(<60초)'일 때만 True → 숫자 빨강.
    알림 상태(alerting)와 무관하게 순수 시간 기준이다."""
    entries = [
        OverlayEntry("a", 7186, False),  # 1h59m → 넉넉 → 빨강 아님
        OverlayEntry("b", 59, False),  # 59s → 1분 미만 → 빨강
        OverlayEntry("c", 60, True),  # 60s → 경계(미만 아님) → 빨강 아님(alerting 무관)
        OverlayEntry("d", None, False),  # 판독값 없음 → 칸 비움
        OverlayEntry("e", 30, False),  # 지속시간 표시 off → 칸 비움(빨강 아님)
    ]
    show = {"a": True, "b": True, "c": True, "d": True, "e": False}
    assert overlay_spec(entries, show) == [
        ("a", "1h59m", False),
        ("b", "59s", True),
        ("c", "1:00", False),
        ("d", None, False),
        ("e", None, False),
    ]
