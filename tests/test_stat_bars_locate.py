"""체력바 영역 자동 찾기 회귀 테스트 (tests/data 스샷 기준).

게임 원본 체력바(하단 메뉴바의 생/마/스 3색 스택)를 전체 화면에서 정확히 찾는지 검증.
- 서로 다른 해상도(2560급·4K)에서 모두 정확 위치.
- 바가 없거나 빈 입력이면 None(→ 메뉴바 최소화 등, 호출 측은 수동 폴백/안내).

스샷이 없는 환경에서는 skip.
"""

import os

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect.stat_bars import locate_stat_bars


def _img(name: str):
    path = f"tests/data/{name}"
    if not os.path.exists(path):
        pytest.skip(f"스샷 없음: {name}")
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        pytest.skip(f"스샷 로드 실패: {name}")
    return img


# (파일명, 기대 bbox x,y,w,h) — 전체화면 검출로 측정한 '게임 원본 체력바' 위치.
# 마지막은 4K(3840x2160) — 해상도가 달라도 같은 로직으로 찾는지(교차검증).
_CASES = [
    ("스크린샷 2026-10-12 000512.png", (930, 1401, 104, 32)),
    ("스크린샷 2026-10-12 200511.png", (930, 1401, 103, 32)),
    ("스크린샷 2026-10-09 190901.png", (932, 1403, 103, 32)),
    ("2026-10-11_123333.png", (1572, 2123, 104, 31)),  # 4K 교차검증
]


@pytest.mark.parametrize("name,box", _CASES)
def test_locate_native_stat_bars(name, box):
    got = locate_stat_bars(_img(name))
    assert got is not None, f"{name}: 체력바를 못 찾음"
    ex, ey, ew, eh = box
    gx, gy, gw, gh = got
    assert abs(gx - ex) <= 10 and abs(gy - ey) <= 10, f"{name}: 위치 {got} != {box}"
    # 폭은 해상도 무관하게 비슷(게임이 UI를 고정 px로 렌더) — 80~160 안.
    assert 80 <= gw <= 160, f"{name}: 폭 이상 {gw}"


def test_locate_handles_empty():
    assert locate_stat_bars(None) is None
    assert locate_stat_bars(np.zeros((0, 0, 3), np.uint8)) is None
    assert locate_stat_bars(np.zeros((10, 10, 3), np.uint8)) is None
