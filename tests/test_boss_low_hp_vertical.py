"""보스바 저HP '1' 오독 — 등록 영역이 바와 세로로 1~6px 어긋날 때(QA 4f106aa, docs/status.md '정정(QA 11-08)').

20% 이하 회색 바탕에서 영역이 어긋나면 고정 숫자 띠가 숫자를 잘라 '17.74'·'12.84'를 1로 읽었다.
88px 수집 80장을 세로 시작 38~52 · 높이 33/37/41로 옮겨 읽으면 146칸이 1 → recheck_low_hp(영역 ±6px에서 흰 글자 다시)로 0칸,
바뀐 146칸 모두 화면 값(몽타주 확인)과 같음 · 맞던 칸이 틀려진 것 0. 한 자리·20% 이하일 때만 — 평소 판독은 그대로.
"""
import zipfile

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect import boss_hp_reader as r

PAD = 6


def _img(zip_name, name):
    with zipfile.ZipFile(f"tests/data/{zip_name}") as z:
        return cv2.imdecode(np.frombuffer(z.read(name), np.uint8), cv2.IMREAD_COLOR)


def _read(im, start, h):
    """앱과 같게: 등록 영역(시작 start, 높이 h)의 오른쪽 42%를 읽고, 한 자리면 ±6px 여유에서 다시."""
    reg = im[start:start + h]
    value, frac = r.read_percent_frac(reg[:, int(reg.shape[1] * 0.58):])
    pad = im[max(0, start - PAD):start + h + PAD]
    return value, frac, r.recheck_low_hp(pad[:, int(pad.shape[1] * 0.58):], value, frac)


GOMOK = "gomok_petak_hp019_158.zip"
UPPER = "unknown_hpxxx_show001_upper_197.zip"


@pytest.mark.parametrize("zip_name,name,start,h,expected", [  # 화면 값(몽타주 확인)
    ("eotgallin_poinche_hp098_058.zip", "unknown_hpxxx_041.png", 38, 41, (19, "55")),
    (GOMOK, "gomok_petak_hp017_159.png", 38, 37, (17, "74")),
    (GOMOK, "gomok_petak_hpxxx_184.png", 43, 41, (12, None)),  # 화면 12.84 — 2560 '8' 모양이 달라 소수는 못 읽음(정수만)
    (UPPER, "gomok_petak_hp001_show015_drop_162.png", 43, 41, (13, "00")),
    (UPPER, "gomok_petak_hp018_128.png", 38, 37, (18, "23")),
])
def test_shifted_region_one_is_read_again(zip_name, name, start, h, expected):
    value, _frac, again = _read(_img(zip_name, name), start, h)
    assert value == 1  # 어긋난 영역 그대로면 '1'(수정 전 현상)
    assert again == expected


@pytest.mark.parametrize("zip_name,name,truth", [
    (GOMOK, "gomok_petak_hpxxx_184.png", 12), (GOMOK, "gomok_petak_hp017_159.png", 17),
    ("eotgallin_poinche_hp098_058.zip", "unknown_hpxxx_041.png", 19), (UPPER, "gomok_petak_hp001_show015_drop_162.png", 13),
])
def test_vertical_sweep_has_no_one(zip_name, name, truth):
    """세로 옮겨 읽기(시작 38~52, 높이 37): '1'이 남지 않고, 다시 읽어 바뀐 값은 모두 화면 값."""
    im = _img(zip_name, name)
    for start in range(38, 53):
        value, _frac, (again, _f) = _read(im, start, 37)
        assert again != 1, start
        if again != value:
            assert again == truth, start


def test_recheck_only_extends_low_one_digit_values():
    im = _img(GOMOK, "gomok_petak_hpxxx_184.png")  # 화면 12.84
    pad = im[37:90]
    pad = pad[:, int(pad.shape[1] * 0.58):]
    assert r.recheck_low_hp(pad, 1) == (12, None)
    assert r.recheck_low_hp(pad, 7) == (7, None)  # 다시 읽은 12가 7로 시작하지 않음 — 바꾸지 않는다
    assert r.recheck_low_hp(pad, 13, "50") == (13, "50")  # 두 자리는 다시 읽지 않음
    assert r.recheck_low_hp(pad, 40) == (40, None)  # 20% 넘음
    assert r.recheck_low_hp(pad, None) == (None, None)
