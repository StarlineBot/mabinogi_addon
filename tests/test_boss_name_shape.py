"""0.31.0 보스 이름 2단계 식별(글자 높이 맞춤 비교) — 해상도·글자 굵기가 달라도 이름을 알아본다.

1단계(픽셀 그대로 비교)가 실패할 때만 이름 글자 묶음을 높이 24px로 맞춰 비교한다(boss_name_matcher.identify_by_shape).
보정 자료: tests/data 보스 바 64장(아래 표, 상자는 자동 찾기 결과·자동 찾기가 거절하는 2장은 손으로).
- 1단계가 식별하던 47장은 결과 그대로.
- 고목의 페타크 3장(10-11 111640 4K·213927·213942) 새로 식별(0.72).
- 목록 밖 보스는 None: 망집의 키리아(10-25 142736, 0.368 — 시제품 기준 0.35면 페타크로 오인), 궁극의 글라스 기브넨 7장(0.233). 브론타나스는 0.33.0에 등록(그 5장은 brontanas로 기대값 변경).
  펠롬 보조 바 '어둠의 에르그'도 0.53으로 페타크와 닮아 기준을 0.6으로(test_pellom_live_samples가 확인).
- 작은 글자 페타크(10-11 123333, 0.387)는 키리아와 점수로 못 나눠 None(그 화면은 HP 판독도 확정 안 됨).
"""
import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.detect import boss_name_matcher as bn

# (파일, 보스 바 상자, 식별 결과) — 2026-10-31 보정
CASES = [
    ('2026-10-11_111640.png', (1649, 1946, 521, 37), 'gomok_petak'),
    ('2026-10-11_123333.png', (1658, 1967, 521, 37), None),
    ('2026-10-30_windowed_wireweb_1.png', (1011, 1218, 521, 36), 'gomok_petak'),
    ('2026-10-30_windowed_wireweb_2.png', (1011, 1218, 521, 36), 'brontanas'),  # 0.33.0 명세 변경: 브론타나스 등록(예전 None)
    ('2026-10-30_windowed_wireweb_3.png', (1011, 1218, 521, 36), 'lenen_miir'),
    ('mabinogi_2026_10_30_213520.png', (1658, 1967, 521, 37), None),
    ('mabinogi_2026_10_30_213927.png', (1658, 1968, 521, 37), 'gomok_petak'),
    ('mabinogi_2026_10_30_213942.png', (1658, 1968, 521, 37), 'gomok_petak'),
    ('mabinogi_2026_10_30_214016.png', (1658, 1968, 521, 37), 'brontanas'),  # 0.33.0 명세 변경: 브론타나스 등록(예전 None)
    ('mabinogi_2026_10_30_214051.png', (1658, 1968, 521, 37), 'lenen_miir'),
    ('mabinogi_2026_10_30_214648.png', (1658, 1968, 521, 37), 'lenen_miir_hoehan'),
    ('mabinogi_2026_10_31_0055251.png', (1658, 1967, 521, 37), 'lenen_miir_hoehan'),
    ('스크린샷 2026-10-07 013118.png', (1018, 1248, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-09 185117.png', (1018, 1248, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-09 185152.png', (1016, 1246, 521, 37), 'brontanas'),  # 0.33.0 명세 변경: 브론타나스 등록(예전 None)
    ('스크린샷 2026-10-09 185217.png', (1018, 1248, 521, 37), 'gomok_petak'),
    ('스크린샷 2026-10-09 185247.png', (1018, 1248, 521, 37), 'lenen_miir_hoehan'),
    ('스크린샷 2026-10-09 190901.png', (1018, 1248, 521, 37), None),
    ('스크린샷 2026-10-09 190905.png', (1018, 1248, 521, 37), None),
    ('스크린샷 2026-10-09 190909.png', (1018, 1248, 521, 37), None),
    ('스크린샷 2026-10-09 190911.png', (1018, 1248, 521, 37), None),
    ('스크린샷 2026-10-09 190915.png', (1018, 1248, 521, 37), None),
    ('스크린샷 2026-10-09 190926.png', (1018, 1248, 521, 37), None),
    ('스크린샷 2026-10-09 191035.png', (1016, 1246, 521, 37), None),
    ('스크린샷 2026-10-09 193901.png', (1018, 1248, 521, 37), 'eotgallin_poinche'),
    ('스크린샷 2026-10-09 200614.png', (1018, 1248, 521, 37), 'pellom'),
    ('스크린샷 2026-10-09 200715.png', (1018, 1248, 521, 37), 'gomok_petak'),
    ('스크린샷 2026-10-09 200724.png', (1018, 1248, 521, 37), 'gomok_petak'),
    ('스크린샷 2026-10-09 201512.png', (1018, 1248, 521, 37), 'pellom'),
    ('스크린샷 2026-10-10 190116.png', (1018, 1248, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-12 000512.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-12 200511.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-12 200625.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-14 000646.png', (1018, 1248, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-15 213313.png', (1016, 1246, 521, 37), 'gomok_petak'),
    ('스크린샷 2026-10-15 213734.png', (1016, 1246, 521, 37), 'brontanas'),  # 0.33.0 명세 변경: 브론타나스 등록(예전 None)
    ('스크린샷 2026-10-16 210734.png', (1018, 1248, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 210747.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 210757.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 210805.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 210815.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 211332.png', (1018, 1248, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 211343.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 211352.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 211414.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 211420.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 211426.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 211435.png', (1018, 1248, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 211456.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 211458.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 212007.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 213335.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 213733.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 213830.png', (1016, 1246, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-16 214902.png', (1018, 1248, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-18 001116.png', (1018, 1248, 521, 37), 'pellom'),
    ('스크린샷 2026-10-18 001216.png', (1016, 1246, 521, 37), 'pellom'),
    ('스크린샷 2026-10-18 001307.png', (1016, 1246, 521, 37), 'pellom'),
    ('스크린샷 2026-10-18 001541.png', (1016, 1246, 521, 37), 'pellom'),
    ('스크린샷 2026-10-18 001801.png', (1016, 1246, 521, 37), 'pellom'),
    ('스크린샷 2026-10-25 142736.png', (1018, 1248, 521, 37), None),
    ('스크린샷 2026-10-25 150822.png', (1018, 1248, 521, 37), 'eotgallin_poinche'),
    ('스크린샷 2026-10-25 233749.png', (1018, 1248, 521, 37), 'lenen_miir'),
    ('스크린샷 2026-10-26 175307.png', (1016, 1246, 521, 37), 'lenen_miir'),
]


def _name(name, box):
    frame = image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)
    x, y, w, h = box
    return frame[y:y + h, x:x + int(w * 0.60)]  # boss_tab과 같은 이름 칸


@pytest.mark.parametrize("name, box, expected", CASES, ids=[c[0] for c in CASES])
def test_identify_matches_calibration(name, box, expected):
    assert bn.identify(_name(name, box)) == expected


def test_shape_step_only_runs_when_pixel_step_fails(monkeypatch):
    calls = []
    original = bn.identify_by_shape
    monkeypatch.setattr(bn, "identify_by_shape", lambda *a: calls.append(1) or original(*a))
    assert bn.identify(_name("2026-10-30_windowed_wireweb_3.png", (1011, 1218, 521, 36))) == "lenen_miir"
    assert calls == []  # 1단계에서 식별 → 2단계 계산 안 함
    assert bn.identify(_name("mabinogi_2026_10_30_213927.png", (1658, 1968, 521, 37))) == "gomok_petak"
    assert calls == [1]


@pytest.mark.parametrize("name, expected", [
    ("mabinogi_2026_10_31_0055251.png", "lenen_miir_hoehan"),
    ("mabinogi_2026_10_30_214648.png", "lenen_miir_hoehan"),
    ("mabinogi_2026_10_30_214051.png", "lenen_miir"),
])
def test_4k_works_without_uhd_variants(name, expected):
    """4K 이름 변형(name_uhd_*)을 빼도 2단계만으로 4K 회한·레넨을 알아본다(해상도 대응이 변형에 기대지 않음)."""
    variants = {bid: [sample for sample, path in zip(samples, sorted((bn._BOSS_DIR / bid).glob("name_*.png")))
                      if "uhd" not in path.name] for bid, samples in bn._VARIANTS.items()}
    assert bn.identify(_name(name, (1658, 1968, 521, 37)), bn._TEMPLATES, variants=variants) == expected


def test_lookalike_names_stay_unidentified():
    """'○○의 ○○○' 모양이 닮은 목록 밖 이름: 키리아·에르그(펠롬 보조 바)."""
    assert bn.identify(_name("스크린샷 2026-10-25 142736.png", (1018, 1248, 521, 37))) is None
    assert bn.identify(_name("스크린샷 2026-10-18 001801.png", (1016, 1280, 521, 37))) is None


def test_shape_thresholds_and_speed():
    import time
    assert (bn.SHAPE_MIN_SCORE, bn.SHAPE_MIN_MARGIN) == (0.6, 0.08)
    binary = bn._binary(_name("mabinogi_2026_10_30_213942.png", (1658, 1968, 521, 37)))
    bn.identify_by_shape(binary, bn._TEMPLATES, bn._VARIANTS)  # 기준 모양 준비(처음 한 번)
    start = time.perf_counter()
    for _ in range(20):
        bn.identify_by_shape(binary, bn._TEMPLATES, bn._VARIANTS)
    assert (time.perf_counter() - start) / 20 < 0.005  # 1회 5ms 이하
