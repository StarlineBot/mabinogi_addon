"""버프 디텍터 회귀 테스트 (실제 상태창 스크린샷 기반)."""

import os

import cv2
import numpy as np
import pytest

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
    img = cv2.imread(_SCREENSHOT, cv2.IMREAD_COLOR)
    if img is None or img.shape[0] < 720:
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
    img = cv2.imread(_SCREENSHOT, cv2.IMREAD_COLOR)
    region = _region()
    template = region[24:54, 8:38]  # 실제 버프 아이콘

    # 아이콘이 없는 배경(모래/잔디) 영역을 세로 띠로 검색 → present로 잡히면 안 됨
    background = img[900:1300, 700:744]
    detections = detect_buffs(background, {"buff_top": template}, (0, 44))
    assert detections == []
