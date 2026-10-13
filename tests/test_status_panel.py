"""상태목록창 앵커 자동 검출 회귀 테스트 (tests/data 스샷 기준).

검증 목표:
- 상태목록창이 떠 있는 스샷에서 앵커(프리미엄 배틀 멤버십)를 **정확한 위치**로 찾는다.
- 앵커가 없는(마을/메뉴) 스샷에서는 None(→ 호출 측 수동 폴백).

스샷이 없는 환경(용량 문제로 로컬에만 있을 때)에서는 skip.
"""

import os

import cv2
import pytest

from mabinogi_addon.detect.status_panel import find_anchor, locate_status_region

_TPL_PATH = "src/mabinogi_addon/assets/buff/icon/premium_battle.png"


def _img(name: str):
    path = f"tests/data/{name}"
    if not os.path.exists(path):
        pytest.skip(f"스샷 없음: {name}")
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        pytest.skip(f"스샷 로드 실패: {name}")
    return img


def _template():
    t = cv2.imread(_TPL_PATH, cv2.IMREAD_COLOR)
    assert t is not None, "앵커 템플릿 로드 실패"
    return t


# (파일명, 기대 좌상단 x, y) — 전체화면 매칭으로 측정한 실제 위치(ts16)
_PRESENT = [
    ("스크린샷 2026-10-12 000512.png", 14, 871),
    ("스크린샷 2026-10-09 190901.png", 16, 873),
    ("스크린샷 2026-10-12 200511.png", 14, 967),
]
# 상태목록창(앵커)이 없는 스샷 — 마을/메뉴/비전투
_ABSENT = [
    "스크린샷 2026-10-09 193901.png",
    "스크린샷 2026-10-09 195115.png",
]


@pytest.mark.parametrize("name,ex,ey", _PRESENT)
def test_anchor_found_at_expected_location(name, ex, ey):
    hit = find_anchor(_img(name), _template())
    assert hit is not None, f"{name}: 앵커를 못 찾음"
    assert hit.score > 0.9, f"{name}: 점수 낮음 {hit.score}"
    # 위치가 측정값과 거의 일치(±8px). 패널이 옮겨져도 전체탐색이라 그 위치를 정확히 잡아야.
    assert abs(hit.x - ex) <= 8, f"{name}: x {hit.x} != {ex}"
    assert abs(hit.y - ey) <= 8, f"{name}: y {hit.y} != {ey}"


@pytest.mark.parametrize("name", _ABSENT)
def test_anchor_absent_returns_none(name):
    hit = find_anchor(_img(name), _template())
    assert hit is None, f"{name}: 앵커 없는데 오탐 {hit}"


# 4K/고해상도 회귀: 1차(반해상도) 크기 추정이 ±2px 어긋나도 2차에서 주변 크기를 함께
# 시도해 찾아야 한다. (크기 하나만 재시도하던 커밋에서 4K가 None으로 회귀했었다.)
_PRESENT_4K = [
    ("2026-10-11_111640.png", 3541, 919),
    ("2026-10-11_123333.png", 208, 573),
]


@pytest.mark.parametrize("name,ex,ey", _PRESENT_4K)
def test_anchor_found_on_4k(name, ex, ey):
    hit = find_anchor(_img(name), _template())
    assert hit is not None, f"{name}: 4K 앵커를 못 찾음(회귀)"
    assert hit.score >= 0.85, f"{name}: 점수 낮음 {hit.score}"
    assert abs(hit.x - ex) <= 8 and abs(hit.y - ey) <= 8, f"{name}: 위치 {hit}"


@pytest.mark.parametrize("name,ex,ey", _PRESENT_4K)
def test_locate_status_region_bottom_to_screen_end(name, ex, ey):
    """영역 아래 끝은 화면 하단까지(상한 없음) — 버프가 늘어 앵커가 잘리지 않도록."""
    img = _img(name)
    H = img.shape[0]
    reg = locate_status_region(img, _template())
    assert reg is not None, name
    rx, ry, rw, rh = reg
    assert ry + rh == H, f"{name}: 아래가 화면 끝이 아님 {reg} (H={H})"
    assert rx <= ex and ry <= ey, f"{name}: 앵커가 영역 밖 {reg}"


def test_find_anchor_handles_empty_input():
    import numpy as np

    assert find_anchor(None, _template()) is None
    assert find_anchor(np.zeros((0, 0, 3), np.uint8), _template()) is None


@pytest.mark.parametrize("name,ex,ey", _PRESENT)
def test_locate_status_region_covers_anchor(name, ex, ey):
    """앵커가 있으면 그 앵커를 포함하는 영역을 돌려준다(아래로 화면 끝까지)."""
    img = _img(name)
    reg = locate_status_region(img, _template())
    assert reg is not None, f"{name}: 영역 유도 실패"
    rx, ry, rw, rh = reg
    # 앵커(ex,ey)가 영역 안에 들어온다(위로 넉넉, 아래로 앵커보다 더 내려감).
    assert rx <= ex and ry <= ey, f"{name}: 앵커가 영역 밖 {reg}"
    assert ry + rh > ey, f"{name}: 아래가 앵커보다 위 {reg}"


def test_locate_status_region_absent_none():
    for name in _ABSENT:
        assert locate_status_region(_img(name), _template()) is None, name
