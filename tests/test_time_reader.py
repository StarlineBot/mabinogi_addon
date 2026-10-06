"""시간 판독 회귀 테스트 (실제 상태창 스크린샷 기반)."""

import os

import cv2
import pytest

from mabinogi_addon.detect.time_reader import read_time

# (스크린샷, y0, y1, 기대 초)  x는 시간 영역을 넉넉히 150~380
CASES = [
    ("224732", 610, 624, 2 * 60 + 1),  # 2분 1초
    ("224732", 634, 648, 29 * 60 + 50),  # 29분 50초
    ("224732", 658, 672, 3600 + 59 * 60 + 46),  # 1시간 59분 46초
    ("224732", 682, 696, 3 * 86400 + 22 * 3600 + 60),  # 3일 22시간 1분
    ("225315", 607, 620, 57),  # 57초 (빨간 글자)
    ("225225", 610, 624, 60 + 48),  # 1분 48초
    ("225225", 634, 648, 24 * 60 + 55),  # 24분 55초
    ("225315", 682, 694, 3 * 86400 + 21 * 3600 + 56 * 60),  # 3일 21시간 56분
]


def _strip(name, y0, y1):
    path = f"tests/data/스크린샷 2026-10-06 {name}.png"
    if not os.path.exists(path):
        pytest.skip("스크린샷 없음")
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    return img[y0:y1, 150:380]


@pytest.mark.parametrize("name,y0,y1,expected", CASES)
def test_reads_time(name, y0, y1, expected):
    assert read_time(_strip(name, y0, y1)) == expected


def test_red_text_reads():
    # 임박(빨간) 글자도 읽혀야 한다
    assert read_time(_strip("225315", 607, 620)) == 57


def test_empty_region_returns_none():
    # 글자 없는 배경 영역
    path = "tests/data/스크린샷 2026-10-06 224732.png"
    if not os.path.exists(path):
        pytest.skip("스크린샷 없음")
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    assert read_time(img[900:950, 700:860]) is None
