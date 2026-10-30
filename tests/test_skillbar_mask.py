"""단축바 자동 찾기 마스크는 UI 픽셀만(QA 0.30.0): 예전 마스크는 ◀▶ 화살표 둘레의 게임 배경(촬영 때 베이지)까지 포함해
어두운 배경(창 모드 3번 장)에서 0.952 < 기준 0.97로 실패했다. 새 마스크 = 예전 마스크 ∩ (템플릿 회색값 >215 또는 <55),
1020 → 526px. tests/data 전체 비교: 예전에 찾던 장면은 같은 위치, 새로 찾는 장면도 모두 표준 위치(오탐 없음).
"""
import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector

SHOTS = [("2026-10-30_windowed_wireweb_1.png", (3, 43, 1168, 89)),
         ("2026-10-30_windowed_wireweb_2.png", (3, 43, 1168, 89)),
         ("2026-10-30_windowed_wireweb_3.png", (3, 43, 1168, 89)),  # 어두운 배경 — 예전 실패
         ("스크린샷 2026-10-06 223724.png", (0, 10, 1168, 89)),
         ("스크린샷 2026-10-16 213830.png", (0, 10, 1168, 89))]


def test_mask_covers_only_arrow_and_outline_pixels():
    assets = detector_assets("skillbar")
    gray = cv2.cvtColor(assets["anchor"], cv2.COLOR_BGR2GRAY)
    on = assets["mask"] > 0
    assert 500 <= int(on.sum()) <= 560
    assert np.all((gray[on] > 215) | (gray[on] < 55))  # 배경색(중간 회색값) 픽셀은 없음


@pytest.mark.parametrize("name, box", SHOTS)
def test_skillbar_found_regardless_of_background(name, box):
    frame = image_io.imread(f"tests/data/{name}")
    trace = {}
    assert run_detector("skillbar", frame, detector_assets("skillbar"), trace) == box
    scores = sorted((c["score"] for c in trace["candidates"]), reverse=True)
    assert scores[0] >= 0.99 and scores[1] < 0.95  # 둘째 후보와 여유
