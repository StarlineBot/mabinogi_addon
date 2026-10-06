"""실제 상태창 스크린샷 기반 아이콘 매칭 회귀 테스트 (기획서 4.2)."""

import glob

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect import match_icon

# 네이티브 스크린샷(2556x1436)에서 잰 좌표.
# 버프 패널은 화면 좌상단, 아이콘 ≈30px.
_SCREENSHOT = next(iter(glob.glob("tests/data/*.png")), None)
BUFF_REGION = (400, 0, 720, 360)  # (y0, x0, y1, x1)
FIRST_ICON = (424, 8, 452, 36)  # 환생시 아이콘 (y0, x0, y1, x1)


def _load():
    if _SCREENSHOT is None:
        pytest.skip("tests/data에 스크린샷 PNG가 없음")
    img = cv2.imread(_SCREENSHOT, cv2.IMREAD_COLOR)
    if img is None or img.shape[0] < 720:
        pytest.skip("스크린샷 해상도가 예상과 다름(좌표 재측정 필요)")
    return img


def test_icon_matches_itself_in_region():
    img = _load()
    y0, x0, y1, x1 = BUFF_REGION
    region = img[y0:y1, x0:x1]
    iy0, ix0, iy1, ix1 = FIRST_ICON
    template = img[iy0:iy1, ix0:ix1]

    result = match_icon(region, template)
    assert result.score > 0.95  # 같은 이미지라 거의 완벽 일치
    # 매칭 위치는 영역 기준 좌표 → 원래 아이콘 위치와 일치
    assert abs(result.x - (ix0 - x0)) <= 2
    assert abs(result.y - (iy0 - y0)) <= 2
    assert result.present()


def test_absent_icon_scores_lower():
    img = _load()
    iy0, ix0, iy1, ix1 = FIRST_ICON
    template = img[iy0:iy1, ix0:ix1]

    # 아이콘이 없는 아래쪽(모래/잔디) 영역에서는 점수가 확연히 낮아야 함
    empty = img[900:1100, 600:900]
    present = match_icon(img[400:720, 0:360], template)
    absent = match_icon(empty, template)
    assert absent.score < present.score
    assert not absent.present()


def test_oversized_template_is_safe():
    img = _load()
    region = img[400:430, 0:30]
    big = img[400:720, 0:360]
    assert match_icon(region, big).score == -1.0
