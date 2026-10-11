"""하단 체력/마나/스태미나 바 비율 판독 회귀 테스트.

- 실게임 캡처(커밋된 스크린샷)에서 영역을 잘라 HP/MP/스태미나 채움 비율을 읽고,
  바 위에 겹쳐 적힌 '현재/최대' 수치로 계산한 실제 비율과 맞는지 본다.
- 색조와 무관하게 '위→아래' 순서로 hp/mp/sta에 매핑되는지(합성 바)도 확인한다.
"""

from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon.detect.stat_bars import read_stat_bars

_SHOTS = Path(__file__).parent / "data"


def _crop(name, y0, y1, x0, x1):
    im = cv2.imread(str(_SHOTS / name))
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


def test_maps_top_to_bottom_order_regardless_of_color():
    # 색을 일부러 섞어도(파랑·노랑·분홍) 위→아래 순서로 hp/mp/sta.
    img = _synthetic([0.5, 0.75, 1.0], hues=[115, 23, 163])
    rs = read_stat_bars(img)
    assert [r.stat_id for r in rs] == ["hp", "mp", "sta"]
    assert abs(rs[0].ratio - 0.5) <= 0.06
    assert abs(rs[1].ratio - 0.75) <= 0.06
    assert rs[2].ratio >= 0.95


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
