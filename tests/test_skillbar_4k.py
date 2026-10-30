"""0.30.4 4K 단축바 자동 찾기: 4K 화살표(◀▶ 2줄)는 회색·검은 테두리 거의 없이 그려져 기본 앵커와 0.91~0.93,
그리고 이 화면들은 화살표가 두 블록 사이(첫 블록 바로 뒤)에 있어 격자가 화살표 왼쪽 562px(창 모드 1182px).

4K 변형 앵커는 213520·214016 두 장으로만 만들고(scripts/build_skillbar_uhd_anchor.py), 나머지 5장은 따로 검증한다.
"""
import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector

TRAIN = {"mabinogi_2026_10_30_213520.png", "mabinogi_2026_10_30_214016.png"}
SHOTS = {
    "image55.png": (2, 8, 1168, 89),  # 화면 전체가 4px 위
    "mabinogi_2026_10_30_213520.png": (2, 12, 1168, 89),
    "mabinogi_2026_10_30_213927.png": (2, 12, 1168, 89),
    "mabinogi_2026_10_30_213942.png": (2, 12, 1168, 89),
    "mabinogi_2026_10_30_214016.png": (2, 12, 1168, 89),
    "mabinogi_2026_10_30_214051.png": (2, 12, 1168, 89),
    "mabinogi_2026_10_30_214648.png": (2, 12, 1168, 89),
    # 예전 자료 중 화살표가 가운데인 배치(0.30.4에 새로 찾음)
    "스크린샷 2026-10-09 193901.png": (2, 12, 1168, 89),
    "스크린샷 2026-10-11 095841.png": (0, 10, 1168, 89),
    # 창 모드(화살표 오른쪽) 그대로
    "2026-10-30_windowed_wireweb_1.png": (3, 43, 1168, 89),
    "2026-10-30_windowed_wireweb_2.png": (3, 43, 1168, 89),
    "2026-10-30_windowed_wireweb_3.png": (3, 43, 1168, 89),
}


@pytest.mark.parametrize("name", sorted(SHOTS))
def test_skillbar_found(name):
    frame = image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)
    trace = {}
    assert run_detector("skillbar", frame, detector_assets("skillbar"), trace) == SHOTS[name]


@pytest.mark.parametrize("name", sorted(n for n in SHOTS if n.startswith(("image55", "mabinogi")) and n not in TRAIN))
def test_4k_anchor_holdout_scores(name):
    """세트에 안 쓴 4K 장: 변형 앵커 최고 0.99 이상, 둘째 후보는 기준(0.97) 아래."""
    frame = image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)
    trace = {}
    run_detector("skillbar", frame, detector_assets("skillbar"), trace)
    scores = sorted((c["score"] for c in trace["uhd_candidates"]), reverse=True)
    assert scores[0] >= 0.99 and scores[1] < 0.97


def test_uhd_assets_travel_in_diagnostics():
    assets = detector_assets("skillbar")
    assert {"anchor", "mask", "anchor_uhd", "mask_uhd"} <= set(assets)
    assert assets["anchor_uhd"].shape[:2] == assets["mask_uhd"].shape == assets["anchor"].shape[:2]
