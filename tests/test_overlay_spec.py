from mabinogi_addon.tracker.engine import OverlayEntry
from mabinogi_addon.ui.overlay import overlay_spec


def test_spec_maps_time_warn_and_gone():
    """(id, 시간, 임박여부, 사라짐여부). 임박=남은시간<60s(숫자 빨강), 사라짐=entry.gone."""
    entries = [
        OverlayEntry("a", 7186, False),  # 1h59m → 넉넉 → 빨강 아님
        OverlayEntry("b", 59, False),  # 59s → 1분 미만 → 빨강
        OverlayEntry("c", 60, True),  # 60s → 경계(미만 아님) → 빨강 아님
        OverlayEntry("d", None, False),  # 판독값 없음 → 칸 비움
        OverlayEntry("e", 30, False),  # 지속시간 표시 off → 칸 비움
        OverlayEntry("f", None, False, gone=True),  # 디버프 사라짐 → gone True
    ]
    show = {"a": True, "b": True, "c": True, "d": True, "e": False, "f": True}
    assert overlay_spec(entries, show) == [
        ("a", "1h59m", False, False),
        ("b", "59s", True, False),
        ("c", "1:00", False, False),
        ("d", None, False, False),
        ("e", None, False, False),
        ("f", None, False, True),
    ]
