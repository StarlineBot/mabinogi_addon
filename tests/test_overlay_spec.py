from mabinogi_addon.tracker.engine import OverlayEntry
from mabinogi_addon.ui.overlay import overlay_spec


def test_spec_maps_time_and_blink():
    entries = [
        OverlayEntry("a", 7186, False),
        OverlayEntry("b", 28, True),  # 점멸
        OverlayEntry("c", None, False),  # 판독값 없음 → 칸 비움
        OverlayEntry("d", 100, False),  # 지속시간 표시 off → 칸 비움
    ]
    show = {"a": True, "b": True, "c": True, "d": False}
    assert overlay_spec(entries, show) == [
        ("a", "1h59m", False),
        ("b", "28s", True),
        ("c", None, False),
        ("d", None, False),
    ]
