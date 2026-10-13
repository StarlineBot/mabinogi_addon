"""보스 체력바 영역 자동 찾기 회귀 테스트 (tests/data 스샷 기준).

색이 아니라 '연속 솔리드 가로 바' 구조로 찾는지 검증:
- 레넨 미이르(보라)·고목 페타크(노랑/빨강) 등 **색이 다른 보스**를 같은 로직으로 정확 검출.
- 보스전이 아닌(마을 등) 스샷은 None(→ 호출 측 '보스바 노출 확인' 안내).

스샷이 없는 환경에서는 skip.
"""

import os

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect.boss_bar import locate_boss_bar


def _img(name: str):
    path = f"tests/data/{name}"
    if not os.path.exists(path):
        pytest.skip(f"스샷 없음: {name}")
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        pytest.skip(f"스샷 로드 실패: {name}")
    return img


# (파일명, 기대 bbox) — 색이 다른 보스들: 레넨(보라), 고목 페타크(노랑/빨강)
_PRESENT = [
    ("스크린샷 2026-10-12 000512.png", (1016, 1246, 521, 37)),  # 레넨(보라)
    ("스크린샷 2026-10-12 200511.png", (1016, 1246, 521, 37)),  # 레넨(보라)
    ("스크린샷 2026-10-09 190901.png", (1018, 1244, 521, 45)),  # 레넨(보라)
    ("스크린샷 2026-10-09 200724.png", (1018, 1247, 521, 38)),  # 고목 페타크(빨강)
]


@pytest.mark.parametrize("name,box", _PRESENT)
def test_locate_boss_bar(name, box):
    got = locate_boss_bar(_img(name))
    assert got is not None, f"{name}: 보스바를 못 찾음"
    ex, ey, ew, eh = box
    gx, gy, gw, gh = got
    assert abs(gx - ex) <= 12 and abs(gy - ey) <= 12, f"{name}: 위치 {got} != {box}"
    assert abs(gw - ew) <= 30, f"{name}: 폭 {gw} != {ew}"


def test_boss_bar_handles_empty():
    assert locate_boss_bar(None) is None
    assert locate_boss_bar(np.zeros((0, 0, 3), np.uint8)) is None
    assert locate_boss_bar(np.zeros((30, 30, 3), np.uint8)) is None
