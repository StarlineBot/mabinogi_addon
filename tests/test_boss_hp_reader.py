"""보스 HP% 판독 회귀 테스트 (기획서 12).

실게임 스샷(값 알고 있음)으로 정수 HP%를 정확히 읽는지 고정. 바 배경색이 HP에 따라
달라도(보라/파랑) 밝기 임계로 흰 글씨만 남겨 판독한다.
"""

import os

import cv2
import pytest

from mabinogi_addon.detect.boss_hp_reader import read_percent

# 파일(2026-10-09) → 실제 HP 정수%
_CASES = {
    "190901": 98,
    "190905": 97,
    "190909": 94,
    "190911": 93,
    "190915": 92,
    "190926": 90,
    "191035": 96,
    "185117": 100,
    "185247": 100,
}
# HP바 % 영역(2560×1440 기준, 하단 중앙). 'XXX.XX %'가 다 들어오게 왼쪽 여유.
_PCT = (1248, 1288, 1380, 1600)  # y0, y1, x0, x1


def _pct_region(name: str):
    path = f"tests/data/스크린샷 2026-10-09 {name}.png"
    if not os.path.exists(path):
        pytest.skip("스샷 없음")
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None or img.shape[0] < 1300:  # % 영역(y≤1288)만 들어오면 됨
        pytest.skip("해상도 예상과 다름")
    y0, y1, x0, x1 = _PCT
    return img[y0:y1, x0:x1]


@pytest.mark.parametrize(("name", "expected"), list(_CASES.items()))
def test_read_hp_percent(name, expected):
    assert read_percent(_pct_region(name)) == expected


def test_empty_region_returns_none():
    import numpy as np

    assert read_percent(np.zeros((0, 0, 3), dtype=np.uint8)) is None
