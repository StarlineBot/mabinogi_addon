"""버프 카탈로그 + 카탈로그 아이콘으로 실제 상태창 매칭 테스트."""

import os

import cv2
import pytest

from mabinogi_addon.catalog import build_templates, load_catalog
from mabinogi_addon.detect import detect_buffs

ICON_COLUMN = (0, 50)
REGION = (400, 770, 0, 50)  # (y0, y1, x0, x1) 아이콘 세로 띠
PRESENT_SHOT = "tests/data/스크린샷 2026-10-06 224732.png"  # 비바체(vivace) 있음
ABSENT_SHOT = "tests/data/스크린샷 2026-10-06 223724.png"  # 비바체 없음


def test_catalog_pairs_icon_and_image():
    catalog = load_catalog()
    by_id = {b.id: b for b in catalog}

    assert len(catalog) >= 20
    # matchIcon + displayImage 짝
    assert by_id["vivace"].display_image is not None
    # 이름이 뒤바뀐 cat도 정상 짝지어짐(icon cat_enable + image cat)
    assert "cat" in by_id and by_id["cat"].display_image is not None
    # 멤버십은 표시 이미지 없음 → None (오버레이는 matchIcon으로 대체)
    assert by_id["premium_battle"].display_image is None


def test_catalog_detects_present_buff():
    if not os.path.exists(PRESENT_SHOT):
        pytest.skip("스크린샷 없음")
    img = cv2.imread(PRESENT_SHOT, cv2.IMREAD_COLOR)
    y0, y1, x0, x1 = REGION
    region = img[y0:y1, x0:x1]
    templates = build_templates(load_catalog())

    found = {d.buff_id: d for d in detect_buffs(region, templates, ICON_COLUMN)}
    assert "vivace" in found
    assert found["vivace"].score > 0.9


def test_catalog_absent_buff_not_detected():
    if not os.path.exists(ABSENT_SHOT):
        pytest.skip("스크린샷 없음")
    img = cv2.imread(ABSENT_SHOT, cv2.IMREAD_COLOR)
    y0, y1, x0, x1 = REGION
    region = img[y0:y1, x0:x1]
    templates = build_templates(load_catalog())

    found = {d.buff_id for d in detect_buffs(region, templates, ICON_COLUMN)}
    assert "vivace" not in found  # 이 화면엔 비바체가 없다
