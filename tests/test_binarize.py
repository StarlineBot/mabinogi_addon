"""이진화 회귀 테스트: 빨간(임박) 글자도 살아남아야 한다."""

import os

import cv2
import pytest

from mabinogi_addon.detect.binarize import binarize

# 비바체 '57초'가 빨간색으로 떠 있는 스크린샷(2556x1436)
_RED_SHOT = "tests/data/스크린샷 2026-10-06 225315.png"
RED_TIME_REGION = (603, 627, 255, 345)  # (y0, y1, x0, x1) '57초' 영역


def _red_crop():
    if not os.path.exists(_RED_SHOT):
        pytest.skip("빨간 글자 스크린샷 없음")
    img = cv2.imread(_RED_SHOT, cv2.IMREAD_COLOR)
    if img is None or img.shape[0] < 700:
        pytest.skip("해상도 예상과 다름")
    y0, y1, x0, x1 = RED_TIME_REGION
    return img[y0:y1, x0:x1]


def test_red_text_survives_value_binarization():
    crop = _red_crop()
    value_bin = binarize(crop)
    assert value_bin.sum() > 0  # 빨간 글자 픽셀이 남아야 함


def test_value_beats_grayscale_on_red():
    crop = _red_crop()
    value_bin = binarize(crop)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, gray_bin = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY)
    # 그레이스케일은 빨강을 거의 놓치고, 최대채널은 확연히 더 많이 잡는다
    assert value_bin.sum() > gray_bin.sum() * 3


def test_background_removed():
    crop = _red_crop()
    value_bin = binarize(crop)
    # 글자는 영역의 일부만 차지 → 대부분 배경(0)이어야 함
    white_ratio = value_bin.mean() / 255
    assert white_ratio < 0.5
