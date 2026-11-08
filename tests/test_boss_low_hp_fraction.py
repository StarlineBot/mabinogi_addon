"""보스바 저HP(20% 이하) 소수 — 회색 빈 바 위 흰 숫자를 밝기 마스크 + 흰 글자 샘플로 읽기(사용자 11-08 '15% 아래로도 소수', QA dee7b93).

채움이 숫자 칸 왼쪽에서 끝나면 숫자가 회색 위 흰 글자라 채도 마스크로는 소수를 못 읽었다(20% 이하 소수 20/278, 앱 입력 비교표).
이제 같은 화면의 흰 글자로 정수가 같게 강하게 읽히고 '.' 왼쪽 글자 수가 정수 자리 수와 같을 때만 소수 두 칸(둘 다 강한 점수)을 읽는다.
정수 경로·결과는 그대로(비교표 3628줄 정수 변화 0), 앞자리만 남은 오독(74.10을 7로)에는 소수를 붙이지 않는다.
"""
import zipfile

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect import boss_hp_reader as r


def _crop(zip_name, name, row):
    with zipfile.ZipFile(f"tests/data/{zip_name}") as z:
        im = cv2.imdecode(np.frombuffer(z.read(name), np.uint8), cv2.IMREAD_COLOR)
    c = {"all": im, "low": im[45:82], "up": im[6:43]}[row]
    return c[:, int(c.shape[1] * 0.58):]  # 앱 입력(등록 보스: 오른쪽 42%)


POINCHE = "eotgallin_poinche_hp004_115.zip"
GOMOK = "unknown_hpxxx_show001_upper_197.zip"


@pytest.mark.parametrize("zip_name,name,row,text", [  # 화면 글자(몽타주로 확인)
    (POINCHE, "eotgallin_poinche_hp017_033.png", "all", "17.64"),  # 채움 끝이 7과 '.' 사이(빨간 테두리 한 줄이 글자 줄로 잡히던 것)
    (POINCHE, "eotgallin_poinche_hpxxx_035.png", "all", "16.16"),
    (POINCHE, "eotgallin_poinche_hpxxx_040.png", "all", "12.00"),
    (POINCHE, "eotgallin_poinche_hpxxx_045.png", "all", "9.08"),
    (POINCHE, "eotgallin_poinche_hpxxx_055.png", "all", "0.61"),
    ("gomok_petak_hp019_158.zip", "gomok_petak_hp014_160.png", "low", "14.88"),  # 2560 두 줄 — '2'·'4' 모양이 조금 다름
    (GOMOK, "gomok_petak_hp000_178.png", "low", "0.07"),
    (GOMOK, "gomok_petak_hpxxx_show017_unread_057.png", "low", "0.11"),
    (GOMOK, "gomok_petak_hp001_show015_drop_162.png", "low", "13.00"),
    (GOMOK, "unknown_hpxxx_071.png", "low", "7.57"),
])
def test_low_hp_fraction_from_white_text(zip_name, name, row, text):
    crop = _crop(zip_name, name, row)
    whole, frac = r.read_percent_frac(crop)
    assert f"{whole}.{frac}" == text
    assert whole == r.read_percent(crop)  # 정수는 그대로


@pytest.mark.parametrize("zip_name,name,whole", [
    (GOMOK, "gomok_petak_hpxxx_045.png", 7),  # 화면 74.10 — 앞자리만 남은 정수 오독(예전부터)에 소수를 붙이지 않음
    (GOMOK, "gomok_petak_hp007_show015_upper_164.png", 7),  # 화면 71.32
    ("gomok_petak_hp019_158.zip", "gomok_petak_hp010_show014_upper_162.png", 10),  # 화면 100.00
])
def test_truncated_integer_gets_no_fraction(zip_name, name, whole):
    assert r.read_percent_frac(_crop(zip_name, name, "low")) == (whole, None)


def test_white_text_samples_cover_all_digits_and_only_for_fraction():
    assert sorted(r._GRAY_SAMPLES) == list("0123456789")
    assert set(r._BRIGHT_SAMPLES) == {"8"}  # 정수 보조 판독 샘플은 예전 그대로(정수 결과 불변)
    crop = _crop(POINCHE, "eotgallin_poinche_hp017_033.png", "all")
    assert r.read_percent_frac(crop, r._DIGITS) == (17, None)  # 템플릿을 넘기면 예전 그대로


def test_text_rows_ignore_bar_border_line():
    numbers = np.zeros((40, 90), np.uint8)
    numbers[0, :31] = 255  # 빨간 바 위 흰 테두리 한 줄
    numbers[14:28, 10:20] = 255
    assert r._text_rows(numbers) == (14, 27)
