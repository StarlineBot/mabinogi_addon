"""하단 체력/마나/스태미나 바 비율 판독 회귀 테스트.

- 실게임 캡처(커밋된 스크린샷)에서 영역을 잘라 HP/MP/스태미나 채움 비율을 읽고,
  바 위에 겹쳐 적힌 '현재/최대' 수치로 계산한 실제 비율과 맞는지 본다.
- 색조와 무관하게 '위→아래' 순서로 hp/mp/sta에 매핑되는지(합성 바)도 확인한다.
"""

from pathlib import Path

import cv2
import pytest
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.detect.stat_bars import read_stat_bars

_SHOTS = Path(__file__).parent / "data"


def _crop(name, y0, y1, x0, x1):
    im = image_io.imread(_SHOTS / name)
    assert im is not None, name
    h, w = im.shape[:2]
    return im[int(h * y0) : int(h * y1), int(w * x0) : int(w * x1)]


def test_reads_hp_full_mp_partial_sta_full():
    # 이 샷: HP 7605/7605(100%), MP 6483/7874(≈82.3%), STA 5085/5085(100%).
    crop = _crop("스크린샷 2026-10-09 190901.png", 0.972, 0.995, 0.362, 0.408)
    rs = read_stat_bars(crop)
    assert [r.stat_id for r in rs] == ["hp", "mp", "sta"]
    ratios = {r.stat_id: r.ratio for r in rs}
    assert ratios["hp"] >= 0.97
    assert abs(ratios["mp"] - 0.823) <= 0.06  # 밝기 절벽 비율 ≈ 실제 비율
    assert ratios["sta"] >= 0.97


def test_reads_all_full():
    crop = _crop("스크린샷 2026-10-09 185117.png", 0.972, 0.995, 0.362, 0.408)
    rs = read_stat_bars(crop)
    assert len(rs) == 3
    assert all(r.ratio >= 0.97 for r in rs)


def _synthetic(ratios, hues):
    """위→아래로 색조 hues, 채움 ratios 인 가짜 3바 영역(채움=밝음/소모=어두움)."""
    h_each, w, gap = 10, 120, 3
    img = np.zeros(((h_each + gap) * len(ratios), w, 3), np.uint8)
    for i, (ratio, hue) in enumerate(zip(ratios, hues)):
        y = i * (h_each + gap)
        bright = cv2.cvtColor(
            np.uint8([[[hue, 200, 220]]]), cv2.COLOR_HSV2BGR
        )[0, 0]
        dark = cv2.cvtColor(np.uint8([[[hue, 200, 60]]]), cv2.COLOR_HSV2BGR)[0, 0]
        img[y : y + h_each, :] = dark
        img[y : y + h_each, : int(w * ratio)] = bright
    return img


def test_names_bars_by_hue_regardless_of_order():
    # 0.49.0(하늘색 인터페이스, 사용자 제보 11-14): 이름은 위→아래 순서가 아니라 색조로(HP ~163·MP ~114·STA ~23).
    img = _synthetic([0.5, 0.75, 1.0], hues=[115, 23, 163])
    rs = read_stat_bars(img)
    assert [r.stat_id for r in rs] == ["hp", "mp", "sta"]
    got = {r.stat_id: r.ratio for r in rs}
    assert abs(got["mp"] - 0.5) <= 0.06
    assert abs(got["sta"] - 0.75) <= 0.06
    assert got["hp"] >= 0.95


def test_nearly_full_snaps_to_100():
    # 오른쪽 끝 1~2px가 캡/안티앨리어싱으로 덜 밝아도 꽉 참(100%)으로 스냅한다.
    # (7606/7606 같은 풀 체력이 99%로 읽히던 버그 방지)
    img = _synthetic([0.985], hues=[163])  # 98.5% 채움 → 사실상 꽉 참
    rs = read_stat_bars(img)
    assert rs[0].ratio == 1.0


def test_partial_not_snapped():
    # 뚜렷한 소모 구간이 있으면 스냅하지 않고 실제 비율을 돌려준다.
    img = _synthetic([0.80], hues=[115])
    rs = read_stat_bars(img)
    assert abs(rs[0].ratio - 0.80) <= 0.06


def test_empty_region_returns_nothing():
    assert read_stat_bars(np.zeros((4, 10, 3), np.uint8)) == []


# ---- 하늘색 인터페이스(사용자 제보 11-14, 2560×1440, MP 실제 6908/7774 = 88.9%) ----
SKY = "tests/data/스크린샷 2026-11-14 230836.png"


@pytest.mark.parametrize("box", [(931, 1403, 105, 32), (928, 1398, 110, 40)])  # 바만 / 테두리 포함
def test_sky_blue_interface_reads_mp_without_border(box):
    from mabinogi_addon import image_io
    from mabinogi_addon.detect.stat_bars import read_stat_bars
    f = image_io.imread(SKY, cv2.IMREAD_COLOR)
    x, y, w, h = box
    got = {r.stat_id: r.ratio for r in read_stat_bars(f[y:y + h, x:x + w], require_complete=True)}
    assert got["hp"] == 1.0 and got["sta"] == 1.0
    assert abs(got["mp"] - 6908 / 7774) <= 0.02  # 테두리(H 92~99·S 89~100)를 MP로 섞지 않음


def test_sky_blue_interface_locates_three_bars():
    from mabinogi_addon import image_io
    from mabinogi_addon.detect.stat_bars import locate_stat_bars, read_stat_bars
    f = image_io.imread(SKY, cv2.IMREAD_COLOR)
    box = locate_stat_bars(f)
    assert box is not None
    x, y, w, h = box
    assert abs(x - 932) <= 3 and abs(y - 1403) <= 3
    assert [r.stat_id for r in read_stat_bars(f[y:y + h, x:x + w], require_complete=True)] == ["hp", "mp", "sta"]


def test_bands_named_by_hue_and_unknown_band_dropped():
    from mabinogi_addon.detect.stat_bars import read_stat_bars
    rows = [((60, 200, 200), 6), ((0, 0, 0), 2), ((163, 176, 207), 8), ((0, 0, 0), 2),
            ((114, 128, 182), 8), ((0, 0, 0), 2), ((23, 220, 233), 8)]  # 맨 위 = 어느 바도 아닌 초록 띠
    hsv = np.concatenate([np.full((n, 120, 3), c, np.uint8) for c, n in rows])
    region = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    got = read_stat_bars(region, require_complete=True)
    assert [(r.stat_id, r.ratio) for r in got] == [("hp", 1.0), ("mp", 1.0), ("sta", 1.0)]


# ---- 인터페이스 색별(사용자 제보 11-15, 2560×1440) — 빨강·노랑·베이지 등 테두리 색이 바 색조에 섞이지 않게 ----
_IFACE = {  # 파일 → MP 기대값(나머지 바는 가득)
    "스크린샷 2026-11-15 010135.png": 1.0,  # 빨강
    "스크린샷 2026-11-15 010144.png": 1.0,
    "스크린샷 2026-11-15 010202.png": 1.0,
    "스크린샷 2026-11-15 010211.png": 1.0,
    "스크린샷 2026-11-15 010216.png": 1.0,  # 노랑
    "스크린샷 2026-11-15 010223.png": 1.0,  # 베이지
    "스크린샷 2026-11-14 230836.png": 6908 / 7774,  # 하늘
}


def _assert_full_read(f, box, mp):
    from mabinogi_addon.detect.stat_bars import read_stat_bars
    x, y, w, h = box
    got = read_stat_bars(f[y:y + h, x:x + w], require_complete=True)
    assert [r.stat_id for r in got] == ["hp", "mp", "sta"]
    got = {r.stat_id: r.ratio for r in got}
    assert got["hp"] == 1.0 and got["sta"] == 1.0
    assert abs(got["mp"] - mp) <= 0.02


@pytest.mark.parametrize("name", sorted(_IFACE))
def test_interface_colours_locate_three_bars(name):
    from mabinogi_addon.detect.stat_bars import locate_stat_bars
    f = image_io.imread(_SHOTS / name, cv2.IMREAD_COLOR)
    box = locate_stat_bars(f)
    assert box is not None
    x, y, w, h = box
    assert abs(x - 932) <= 3 and abs(y - 1403) <= 3 and abs(w - 103) <= 4  # 테두리 장식·이음새로 넓어지지 않음
    _assert_full_read(f, box, _IFACE[name])


@pytest.mark.parametrize("box", [(932, 1403, 103, 32), (928, 1398, 110, 40)])  # 바만 / 테두리 포함
@pytest.mark.parametrize("name", sorted(_IFACE))
def test_interface_colours_read_three_bars(name, box):
    f = image_io.imread(_SHOTS / name, cv2.IMREAD_COLOR)
    _assert_full_read(f, box, _IFACE[name])
