"""보스 이름 식별 회귀 테스트 (기획서 12.2).

등록된 보스는 식별하고, 미등록 보스는 None. 접두어 함정(레넨의 미이르 vs
레넨의 미이르:회한)에서 더 긴(구체적) 이름을 택하는지 확인.
"""

import os

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.detect.boss_name_matcher import identify

_NAME_REGION = (1250, 1290, 1018, 1300)  # y0, y1, x0, x1


def _region(name: str):
    path = f"tests/data/스크린샷 2026-10-09 {name}.png"
    if not os.path.exists(path):
        pytest.skip("스샷 없음")
    img = image_io.imread(path, cv2.IMREAD_COLOR)
    if img is None or img.shape[0] < 1300:
        pytest.skip("해상도 예상과 다름")
    y0, y1, x0, x1 = _NAME_REGION
    return img[y0:y1, x0:x1]


def test_identifies_registered_boss():
    assert identify(_region("185117")) == "lenen_miir"


def test_identifies_gomok_petak():
    assert identify(_region("185217")) == "gomok_petak"


def test_identifies_eotgallin_poinche():
    # 193901 = "엇갈린 운명의 포인셰" (영상 1440p에서 추출한 템플릿)
    assert identify(_region("193901")) == "eotgallin_poinche"


def test_identifies_pellom():
    # 195115 = "펠롬" (초록 바, 짧은 2글자 이름) — 오매칭 없이 식별
    assert identify(_region("195115")) == "pellom"


def test_prefix_trap_picks_longer_name():
    # 185247 = "레넨의 미이르 : 회한" — 접두어 'lenen_miir'도 맞지만 더 긴 쪽을 택해야
    assert identify(_region("185247")) == "lenen_miir_hoehan"


def test_unregistered_boss_returns_none():
    # 185152 = "브론타나스"(미등록)
    assert identify(_region("185152")) is None


def test_empty_region_returns_none():
    assert identify(np.zeros((0, 0, 3), dtype=np.uint8)) is None
