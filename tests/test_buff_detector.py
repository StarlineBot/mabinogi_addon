"""버프 디텍터 회귀 테스트 (실제 상태창 스크린샷 기반)."""

import os

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.detect import detect_buffs

# 좌표를 측정한 보정 기준 이미지(2556x1436)로 고정.
_SCREENSHOT = "tests/data/스크린샷 2026-10-06 223724.png"
REGION = (400, 0, 720, 360)  # (y0, x0, y1, x1) 버프 패널
ICON_COLUMN = (0, 44)  # 영역 기준 아이콘 세로 띠 x범위
# 영역 기준 아이콘 위치(y) — 측정값. (아이콘 상단 y, 화면 424/514/574 - 400)
SAMPLE_ROWS = {"buff_top": 24, "buff_mid": 114, "buff_low": 174}


def _region():
    if not os.path.exists(_SCREENSHOT):
        pytest.skip("tests/data에 스크린샷 PNG가 없음")
    img = image_io.imread(_SCREENSHOT, cv2.IMREAD_COLOR)
    assert img is not None, f"스샷 로드 실패: {_SCREENSHOT}"
    if img.shape[0] < 720:
        pytest.skip("스크린샷 해상도가 예상과 다름")
    y0, x0, y1, x1 = REGION
    return img[y0:y1, x0:x1]


def _templates(region):
    # 영역에서 실제 아이콘을 잘라 등록 템플릿으로 사용(자기 검색 → 반드시 찾혀야 함)
    return {
        bid: region[y : y + 30, 8:38] for bid, y in SAMPLE_ROWS.items()
    }


def test_detects_all_registered_in_y_order():
    region = _region()
    templates = _templates(region)

    detections = detect_buffs(region, templates, ICON_COLUMN)
    found = {d.buff_id for d in detections}
    assert found == set(SAMPLE_ROWS)  # 셋 다 검출

    ys = [d.y for d in detections]
    assert ys == sorted(ys)  # y 오름차순
    # 각 검출 y가 등록 위치와 근접
    by_id = {d.buff_id: d for d in detections}
    for bid, y in SAMPLE_ROWS.items():
        assert abs(by_id[bid].y - y) <= 2
        assert by_id[bid].score > 0.95


def test_icon_absent_in_background_region():
    if not os.path.exists(_SCREENSHOT):
        pytest.skip("tests/data에 스크린샷 PNG가 없음")
    img = image_io.imread(_SCREENSHOT, cv2.IMREAD_COLOR)
    region = _region()
    template = region[24:54, 8:38]  # 실제 버프 아이콘

    # 아이콘이 없는 배경(모래/잔디) 영역을 세로 띠로 검색 → present로 잡히면 안 됨
    background = img[900:1300, 700:744]
    detections = detect_buffs(background, {"buff_top": template}, (0, 44))
    assert detections == []


# ---- 요새화 기본 버프 + 한 줄 하나(제작자 11-05, image.png·image1.png) -------------------------------------------
def _status(name):
    import cv2
    import numpy as np
    from mabinogi_addon import image_io
    from mabinogi_addon.detect.status_panel import anchor_template, locate_status_region
    frame = image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)
    x, y, w, h = locate_status_region(frame, anchor_template())
    return np.ascontiguousarray(frame[y:y + h, x:x + w])


def _default_templates():
    from mabinogi_addon.catalog import DEFAULT_ICON_DIR, DEFAULT_IMAGE_DIR, build_templates, load_catalog
    return build_templates(load_catalog((DEFAULT_ICON_DIR,), (DEFAULT_IMAGE_DIR,)))


def test_fortification_is_default_buff_named_yosaehwa():
    from mabinogi_addon.catalog import DEFAULT_BUFF_NAMES, DEFAULT_ICON_DIR, DEFAULT_IMAGE_DIR, load_catalog
    ids = {b.id: b for b in load_catalog((DEFAULT_ICON_DIR,), (DEFAULT_IMAGE_DIR,))}
    assert "fortification" in ids and DEFAULT_BUFF_NAMES["fortification"] == "요새화"


def test_image1_fortification_row_is_not_vivace_even_when_vivace_was_held():
    from mabinogi_addon.detect import detect_buffs
    templates = _default_templates()
    region = _status("image1.png")
    found = {d.buff_id: d for d in detect_buffs(region, templates, (0, 50))}
    assert "fortification" in found and "vivace" not in found
    held = {"vivace": found["fortification"].y}  # 직전 프레임에 그 줄을 비바체로 잡고 있었어도(깜빡임·유지 가설)
    again = {d.buff_id for d in detect_buffs(region, templates, (0, 50), held=held)}
    assert "fortification" in again and "vivace" not in again


def test_one_buff_per_row_keeps_highest_and_same_picture_pair():
    import numpy as np
    from mabinogi_addon.detect.buff_detector import Detection, _one_per_row
    rng = np.random.default_rng(0)
    a = rng.integers(0, 255, (16, 16, 3), dtype=np.uint8)
    b = rng.integers(0, 255, (16, 16, 3), dtype=np.uint8)
    templates = {"fortification": a, "vivace": b, "same": a.copy(), "other": b}
    kept = _one_per_row([Detection("vivace", 0.78, 100), Detection("fortification", 1.0, 101),
                         Detection("same", 1.0, 100), Detection("other", 0.9, 130)], templates)
    assert {d.buff_id for d in kept} == {"fortification", "same", "other"}  # 같은 그림(same)은 함께, 다른 줄은 그대로


def test_color_check_rejects_lookalike_frame_icons():
    """회색 비교로는 테두리가 같아 0.8 안팎 — '시간 분열: 낮'(0.803)·'재생'(0.799)에 요새화가 붙지 않는다."""
    from mabinogi_addon.detect import detect_buffs
    templates = _default_templates()
    for name in ("스크린샷 2026-10-31 174946.png", "2026-10-30_windowed_wireweb_3.png"):
        assert "fortification" not in {d.buff_id for d in detect_buffs(_status(name), templates, (0, 50))}, name
