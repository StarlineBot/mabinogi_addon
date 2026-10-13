"""보스 HP% 판독 회귀 테스트 (기획서 12).

실게임 스샷(값 알고 있음)으로 정수 HP%를 정확히 읽는지 고정. 바 배경색이 HP에 따라
달라도(보라/초록/노랑/빨강/금색) **색거리 + 오른쪽끝 고정칸**으로 극성 무관하게 읽는다.
region 은 보스 HP바 박스(오른쪽 끝 = 바 오른쪽 끝).
"""

import os

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect.boss_hp_reader import read_percent

# 파일(2026-10-09) → (바 오른쪽 끝 x, 실제 HP 정수%). 바 높이 y 1248~1284.
_CASES = {
    "190901": (1539, 98),  # 보라
    "190905": (1539, 97),
    "190909": (1539, 94),
    "190911": (1539, 93),
    "190915": (1539, 92),
    "190926": (1539, 90),
    "191035": (1539, 96),
    "185117": (1539, 100),
    "185247": (1539, 100),
    "200614": (1540, 99),  # 펠롬 보라
    "200724": (1539, 25),  # 고목 빨강
    "193901": (1540, 40),  # 포인셰 금색
    "201512": (1541, 42),  # 펠롬 노랑 ← 밝은 바(어두운 글자) 핵심 케이스
}
_Y0, _Y1 = 1248, 1284
_LEFT_PAD = 150  # 오른쪽에서 이만큼 왼쪽까지가 숫자 영역


def _bar_box(name: str, right: int):
    path = f"tests/data/스크린샷 2026-10-09 {name}.png"
    if not os.path.exists(path):
        pytest.skip("스샷 없음")
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None or img.shape[0] < 1300:
        pytest.skip("해상도 예상과 다름")
    return img[_Y0:_Y1, right - _LEFT_PAD:right]


@pytest.mark.parametrize(("name", "data"), list(_CASES.items()))
def test_read_hp_percent(name, data):
    right, expected = data
    assert read_percent(_bar_box(name, right)) == expected


# 박스 오른쪽 끝이 바 끝과 몇 px 어긋나도(자동정렬) 맞게 읽어야 한다 —
# 라이브에서 기본 영역이 정확히 안 맞던 문제 회귀 방지.
@pytest.mark.parametrize("off", [-4, -2, 2, 4])
def test_read_tolerates_misalignment(off):
    # 대표 케이스 몇 개만(전 케이스×오프셋은 느림)
    for name in ("185117", "193901", "201512", "190926"):
        right, expected = _CASES[name]
        got = read_percent(_bar_box(name, right + off))
        assert got == expected, f"{name} off={off}: {got} != {expected}"


# 2자리 소수 "XX.00 %" 회귀: 소수가 .00일 때 정렬 창이 왼쪽으로 밀려 units 자리를 빠뜨린
# 1자리 오독(예: 48.00 → 4)이, 그 1자리 점수가 우연히 1.00이라 정답 2자리를 이기던 문제.
# (수집모드로 모은 실프레임 crop 묶음. crop 은 이미 보스바 영역이라 그대로 판독.)
import zipfile  # noqa: E402

_POINCHE_ZIP = "tests/data/eotgallin_poinche_hp004_115.zip"
# (zip 내 파일, 실제 표시 정수%) — 몽타주로 눈으로 확인한 값. hp004_000 은 실제 48.00%.
_DECIMAL_CASES = [
    ("eotgallin_poinche_hp004_000.png", 48),  # 48.00 % — 예전엔 4로 오독
    ("eotgallin_poinche_hp047_001.png", 47),  # 47.43 %
    ("eotgallin_poinche_hp052_103.png", 52),  # 52.25 %
]


@pytest.mark.parametrize("entry,expected", _DECIMAL_CASES)
def test_two_decimal_percent(entry, expected):
    if not os.path.exists(_POINCHE_ZIP):
        pytest.skip("데이터 zip 없음")
    with zipfile.ZipFile(_POINCHE_ZIP) as z:
        buf = np.frombuffer(z.read(entry), np.uint8)
    crop = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    assert crop is not None, entry
    assert read_percent(crop) == expected, f"{entry}: .00 소수 오독 재발"


def test_empty_region_returns_none():
    assert read_percent(np.zeros((0, 0, 3), dtype=np.uint8)) is None


def test_gray_region_returns_none():
    assert read_percent(np.zeros((36, 150), dtype=np.uint8)) is None
