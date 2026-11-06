"""보스바 두 줄 구간(고목의 페타크 위·고대의 의지 아래) % 튐 — QA d52528a, 수집 gomok_petak_hp019_158.zip.

① 노란 바탕 '55.00 %'·보라 바탕 '100.00 %' 판독(이 화면 글자 모양 샘플 추가: scripts/build_boss_digits_20261106.py).
② 위 줄이 보스바면 위 줄 % 판독이 실패해도 아래 줄(다른 바) 값으로 되돌아가지 않음(이번 판독 비움 → 표시는 직전 값 흐리게).
③ 두 줄 구간에선 바가 등록 영역보다 5px 아래 — 확신 없는 판독은 세로 위치를 옮겨 다시 읽음('100'을 10으로 읽던 것).
"""
import zipfile

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.detect.boss_hp_reader import read_percent, read_percent_scored
from test_boss_bar_overlay import _Watcher, tab  # noqa: F401

ZIP = "tests/data/gomok_petak_hp019_158.zip"


def _shot(stamp):
    return image_io.imread(f"tests/data/스크린샷 2026-11-06 {stamp}.png", cv2.IMREAD_COLOR)


@pytest.mark.parametrize("stamp,y,expected", [
    ("233618", 1214, 55),   # 위 줄 노란 바탕 55.00 %
    ("233616", 1182, 55),
    ("233838", 1252, 100),  # 아래 줄 보라 바탕 100.00 % (예전 10)
    ("233838", 1213, 14),   # 위 줄 빨간 14.99 %(예전에도 읽힘)
    ("233618", 1253, 91),   # 아래 줄 91.85 %
])
def test_reader_on_two_row_screens(stamp, y, expected):
    crop = _shot(stamp)[y:y + 37, 1018:1539]
    assert read_percent(crop) == expected
    value, key = read_percent_scored(crop)
    assert value == expected


def _frame(name):
    with zipfile.ZipFile(ZIP) as z:
        return cv2.imdecode(np.frombuffer(z.read(name), np.uint8), cv2.IMREAD_COLOR)


def _reading(tab, img, lower_value):
    low = img[45:82]
    out = {"boss_id": None, "raw_hp": None, "bar_pct": lower_value, "bar": True, "frame": low}
    return tab._overlay_reading(img, 45, 37, out)


@pytest.mark.parametrize("name", [
    "gomok_petak_hp090_show055_jump_087.png", "gomok_petak_hp006_show090_drop_091.png",
    "gomok_petak_hp006_show061_drop_097.png", "gomok_petak_hp047_show010_jump_106.png",
    "gomok_petak_hp090_show012_jump_109.png", "gomok_petak_hp027_show006_jump_113.png",
    "gomok_petak_hp064_show010_jump_118.png",
    "gomok_petak_hp010_show055_drop_036.png", "gomok_petak_hp010_show055_drop_061.png",
    "gomok_petak_hp010_show055_drop_065.png",
])
def test_collected_jump_drop_frames_show_upper_boss_value(tab, name):
    """예전: 55 → 90 → 61 → 10 → 12 → 6 → 10(아래 줄 '고대의 의지' 값이 섞임). 이제 위 줄 보스(고목의 페타크) 55만."""
    img = _frame(name)
    lower = read_percent(img[45:82])
    r = _reading(tab, img, lower)
    assert r["value"] == 55 and r["boss"] == "gomok_petak" and r["rule"] == "upper", (name, lower, r)


def test_upper_low_hp_red_still_read(tab):
    r = _reading(tab, _frame("gomok_petak_hp010_show014_upper_162.png"), 10)
    assert r["value"] == 14 and r["rule"] == "upper"  # 빨간 14.40 %


def test_upper_unreadable_does_not_fall_back_to_lower_value(tab):
    img = _frame("gomok_petak_hp090_show055_jump_087.png").copy()
    upper = img[0:45]
    fill = upper[25, 400].copy()  # 노란 채움색
    upper[3:44, 420:521] = fill  # 위 줄 % 글자를 지움(못 읽는 상태)
    r = _reading(tab, img, read_percent(img[45:82]))
    assert r["value"] is None and r["rule"] == "upper_unread" and r["boss"] == "gomok_petak"


def test_lower_100_read_after_vertical_realign_when_no_upper_bar(tab):
    img = _frame("gomok_petak_hp010_show055_drop_036.png").copy()
    img[0:44] = (60, 70, 65)  # 위 줄을 어두운 바탕으로 덮음(아래 줄만)
    low = img[45:82]
    assert read_percent(low) == 10  # 등록 영역(5px 위로 어긋남) 그대로는 '10'
    out = {"boss_id": None, "raw_hp": None, "bar_pct": 10, "bar": True, "frame": low}
    r = tab._overlay_reading(img, 45, 37, out)
    assert r["value"] == 100 and r["rule"] is None, (r["rule"], r.get("band"), r["raw"])
