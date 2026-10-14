"""보스 HP% 판독 회귀 테스트 (기획서 12).

실게임 스샷(값 알고 있음)으로 정수 HP%를 정확히 읽는지 고정. 바 배경색이 HP에 따라
달라도(보라/초록/노랑/빨강/금색) **색거리 + 오른쪽끝 고정칸**으로 극성 무관하게 읽는다.
region 은 보스 HP바 박스(오른쪽 끝 = 바 오른쪽 끝).
"""

import os

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
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
    img = image_io.imread(path, cv2.IMREAD_COLOR)
    assert img is not None, f"스샷 로드 실패: {path}"
    if img.shape[0] < 1300:
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


# 손으로 잡은 큰 박스(523×40) 높이 정규화 회귀: 40px 그대로면 46%가 4로 오독되고,
# 바 높이(화면 비율, 1440→37px)로 세로 중심 크롭하면 46으로 정확히 읽힌다.
@pytest.mark.parametrize(
    "entry", ["eotgallin_poinche_hp004_002.png", "eotgallin_poinche_hp004_109.png"]
)
def test_manual_box_height_normalized_reads_46(entry):
    from mabinogi_addon.detect.boss_bar import normalize_box_height

    if not os.path.exists(_POINCHE_ZIP):
        pytest.skip("데이터 zip 없음")
    with zipfile.ZipFile(_POINCHE_ZIP) as z:
        frame = cv2.imdecode(np.frombuffer(z.read(entry), np.uint8), cv2.IMREAD_COLOR)
    assert frame is not None and frame.shape[0] == 40
    assert read_percent(frame) == 4  # 40px 그대로면 오독(회귀 재현)
    th = normalize_box_height((0, 0, frame.shape[1], 40), 1440)[3]  # 바 높이 37
    top = (frame.shape[0] - th) // 2
    assert read_percent(frame[top : top + th]) == 46  # 정규화하면 정확


# 저HP(빨간 바) 보조 경로 회귀: 기본 마스크(채도)가 회색 배경에 flooded돼 None이던 저HP
# 프레임을, 밝기 보조 마스크로 다시 읽어 빨간 바 구간 값(≤20)을 판독한다. 정상 경로엔 개입
# 안 하고(오독 없음), 못 읽는 프레임은 None(틀린 값보다 안전).
def _norm37(im):
    from mabinogi_addon.detect.boss_bar import normalize_box_height

    th = normalize_box_height((0, 0, im.shape[1], im.shape[0]), 1440)[3]
    top = (im.shape[0] - th) // 2
    return im[top : top + th]


def test_low_hp_fallback_reads_red_bar():
    if not os.path.exists(_POINCHE_ZIP):
        pytest.skip("데이터 zip 없음")
    with zipfile.ZipFile(_POINCHE_ZIP) as z:
        names = [n for n in z.namelist() if "hpxxx_" in n]
        vals = []
        for n in names:
            im = cv2.imdecode(np.frombuffer(z.read(n), np.uint8), cv2.IMREAD_COLOR)
            vals.append(read_percent(_norm37(im)))
    readable = [v for v in vals if v is not None]
    assert len(readable) >= 20, f"저HP 판독 너무 적음: {len(readable)}/{len(vals)}"
    assert all(v <= 20 for v in readable), f"빨간 바 구간 밖 오독: {sorted(set(readable))}"
    assert 15 in readable and 16 in readable, "15·16% 미판독(15% 경고 영향)"
    assert any(v is None for v in vals)  # 아주 낮은 일부(8·6%대)는 None(안전)


def test_low_hp_fallback_does_not_touch_normal_frames():
    """정상(채도 경로로 읽히는) 프레임은 보조 경로를 타지 않아 결과가 그대로다."""
    for name, (right, expected) in _CASES.items():
        got = read_percent(_bar_box(name, right))
        assert got == expected, f"{name}: 보조 경로 개입으로 바뀜 {got} != {expected}"


def test_empty_region_returns_none():
    assert read_percent(np.zeros((0, 0, 3), dtype=np.uint8)) is None


def test_gray_region_returns_none():
    assert read_percent(np.zeros((36, 150), dtype=np.uint8)) is None
