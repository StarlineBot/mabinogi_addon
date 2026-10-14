"""회귀: 다른 렌더링(스케일링된 화면)용 템플릿 세트 + 세트 자동선택.

게임 UI 글자(7px)는 모니터·스케일링(울트라와이드 레터박스 등)에 따라 픽셀 패턴이
달라, 개발자 네이티브로 만든 기본 세트('default')로는 못 읽는다(점수 ~0.5로 깔림).
그 렌더링에서 뜬 'scaled' 세트를 넣고, 리더가 세트별 신뢰도로 맞는 세트를 고른다.
tests/data/buff_scaled.png = 그 스케일링 렌더링의 버프 패널(실데이터).
"""

import os

import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.detect import score_sets, set_names
from mabinogi_addon.detect.time_reader import read_time

_SHOT = "tests/data/buff_scaled.png"

# (y0, y1, 기대 초)  시간 영역 x는 엔진과 같게 150부터.
CASES = [
    (16, 25, 6 * 60 + 47),  # 6분 47초
    (40, 49, 8 * 60 + 20),  # 8분 20초
    (64, 73, 28 * 60 + 47),  # 28분 47초
    (88, 97, 29 * 60 + 3),  # 29분 3초
    (184, 193, 3600 + 52),  # 1시간 0분 52초
]


def _strip(y0, y1):
    if not os.path.exists(_SHOT):
        pytest.skip("스케일링 샘플 없음")
    img = image_io.imread(_SHOT, cv2.IMREAD_COLOR)
    return img[y0 - 2 : y1 + 2, 150:]


def test_scaled_set_present():
    assert "scaled" in set_names()


@pytest.mark.parametrize("y0,y1,expected", CASES)
def test_scaled_set_reads_scaled_render(y0, y1, expected):
    # 'scaled' 세트로는 맞게 읽힌다.
    assert read_time(_strip(y0, y1), set_name="scaled") == expected
    # 기본 세트로는 이 렌더링을 못 맞춘다(틀리거나 None) → 세트가 필요한 이유.
    assert read_time(_strip(y0, y1), set_name="default") != expected


@pytest.mark.parametrize("y0,y1,expected", CASES)
def test_auto_selection_prefers_scaled(y0, y1, expected):
    # 세트 자동선택 신호: 'scaled'가 정답 + 더 높은 신뢰도로 이긴다.
    scored = score_sets(_strip(y0, y1))
    val_s, conf_s = scored["scaled"]
    _val_d, conf_d = scored["default"]
    assert val_s == expected
    assert conf_s > conf_d  # default는 None(0.0)이거나 더 낮다
