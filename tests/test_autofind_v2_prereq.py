"""자동 찾기 v2 선행 2건(0.39.0에서 되돌려진 것 다시 넣기, 11-06).

- 1920×1080 버프 찾기: 멤버십 기준 아이콘이 없는 목록 — 같은 열·24px 간격의 서로 다른 목록 아이콘 3개로 찾는다(임계값은 그대로).
- 헤일로 위치 찾기: 전투 제한 시간이 15분 넘는 동안에도 위치는 찾는다(위치 탐색만 3600초, 알림 판독은 900초 그대로).
tests/data 큰 화면 112장 측정(11-06): 버프 111·단축바 111·체력바 105·투아림 111·도르카 110·헤일로 59·보스바 77 — 0.39.0 측정(89장) 이상.
"""
import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector


def _frame(name):
    return image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)


@pytest.mark.parametrize("name,x", [("image01.png", 112), ("image02.png", 117), ("image03.png", 117), ("image04.png", 117)])
def test_1080_buff_list_without_membership_icon_is_found(name, x):
    trace = {}
    box = run_detector("buff", _frame(name), detector_assets("buff"), trace)
    assert box is not None and box[0] == x
    assert trace.get("fallback") == "aligned_distinct_buff_icons"


def test_buff_fallback_needs_three_distinct_icons_in_one_column():
    import numpy as np
    from mabinogi_addon.detect.status_panel import fallback_assets, locate_icon_column
    templates = fallback_assets()
    frame = np.zeros((400, 300, 3), np.uint8)
    one = next(iter(templates.values()))
    frame[100:116, 50:66] = one  # 아이콘 하나만 → 목록으로 보지 않음
    assert locate_icon_column(frame, templates) is None


def test_halo_location_search_allows_long_battles_but_alert_reading_keeps_900():
    from mabinogi_addon.detect import halo_timer
    frame = _frame("2026-10-30_windowed_wireweb_1.png")
    box = run_detector("halo_timer", frame, detector_assets("halo_timer"), {})
    assert box is not None
    x, y, w, h = box
    crop = frame[y:y + h, x:x + w]
    seconds = halo_timer.read_seconds(crop, max_seconds=3600)
    assert seconds is not None and seconds > 900  # 15분 넘는 전투 시간에서도 자리를 찾음
    assert halo_timer.read_seconds(crop) is None  # 알림 판독(기본 900초)은 그대로
