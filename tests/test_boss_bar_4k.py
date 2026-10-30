"""0.30.1 4K(3840×2160) 보스 체력바: 게임 UI는 1440 높이를 넘는 화면에서 커지지 않는다(보스바 521×37, 2560과 같음).

- 자동 찾기 크기 기준이 화면 비율이라 4K에서 최소 폭 691px(> 521) → 후보 0개였다 → UI 배율(min(H,1440)/1440).
- 판독 상자 높이 정규화도 화면 비율(4K 56px)이라 100.00%를 1%로 읽었다 → 같은 UI 배율로 37px.
- 채도 높은 바닥(213520 파란 얼음, 바 채움도 파랑)과 바가 한 덩어리 → 색조·밝기로 나눠 다시 찾기.
- 글자 위치가 기준과 다른 화면(10-11 123333, 100.00%를 30으로·점수 0.48)은 자동 찾기로 확정하지 않는다.
"""
import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect import boss_hp_reader
from mabinogi_addon.detect.boss_bar import normalize_box_height, ui_scale

SHOTS = {  # 파일 → (상자, 화면 HP 정수)
    "mabinogi_2026_10_30_213520.png": ((1658, 1967, 521, 37), 76),  # 파란 얼음 바닥, 76.52%
    "mabinogi_2026_10_30_213927.png": ((1658, 1968, 521, 37), 100),
    "mabinogi_2026_10_30_213942.png": ((1658, 1968, 521, 37), 99),  # 99.99%
    "mabinogi_2026_10_30_214016.png": ((1658, 1968, 521, 37), 100),
    "mabinogi_2026_10_30_214051.png": ((1658, 1968, 521, 37), 100),
    "mabinogi_2026_10_30_214648.png": ((1658, 1968, 521, 37), 100),
}


@pytest.mark.parametrize("name", sorted(SHOTS))
def test_4k_boss_bar_found_and_read(name):
    frame = image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)
    box, percent = SHOTS[name]
    assert run_detector("boss", frame, detector_assets("boss"), {}) == box
    x, y, w, h = box
    assert boss_hp_reader.read_percent(frame[y:y + h, x:x + w]) == percent


def test_misaligned_4k_text_is_not_confirmed_by_autofind():
    frame = image_io.imread("tests/data/2026-10-11_123333.png", cv2.IMREAD_COLOR)
    trace = {}
    assert run_detector("boss", frame, detector_assets("boss"), trace) is None
    # 0.31.0: 실행 중 판독도 점수 0.6 미만은 못 읽음(None)이라 이유가 '판독 불가'로 한 단계 앞에서 나온다(확정 안 함은 같음)
    assert any(v.get("rejection") in ("percent_low_confidence", "percent_unreadable") for v in trace.get("validation", []))


def test_box_height_uses_ui_scale_not_screen_ratio():
    assert ui_scale(2160) == 1 and ui_scale(1440) == 1 and ui_scale(1080) == 0.75
    assert normalize_box_height((0, 1940, 521, 80), 2160)[3] == 37  # 4K: 예전 56
    assert normalize_box_height((0, 1200, 521, 40), 1440)[3] == 37  # 2560×1440 그대로
    assert normalize_box_height((0, 1200, 521, 40), 1410)[3] == 36  # 창 모드 그대로
    # 손으로 잡은 박스(논리좌표): 4K@150% → 논리 1440, 물리 37px = 논리 25px / 4K@200% → 논리 1080, 18~19px
    assert normalize_box_height((0, 1300, 347, 30), 1440, 1.5)[3] == 25
    assert normalize_box_height((0, 980, 260, 30), 1080, 2.0)[3] in (18, 19)
    # 4K@100%에서 그린 큰 박스도 세로 중심은 그대로 두고 37px로 → 100.00%를 100으로
    frame = image_io.imread("tests/data/mabinogi_2026_10_30_214016.png", cv2.IMREAD_COLOR)
    x, y, w, h = normalize_box_height((1658, 1958, 521, 57), 2160)
    assert h == 37 and boss_hp_reader.read_percent(frame[y:y + h, x:x + w]) == 100


def test_4k_halo_timer_read_with_one_pixel_margin():
    """214648(회한 '14:46'): 글자 윗변이 읽기 창 윗변과 겹쳐 후보 0개였다 → 1px 여유 + 4K 굵은 글자 참조 추가."""
    from mabinogi_addon.detect import halo_timer
    frame = image_io.imread("tests/data/mabinogi_2026_10_30_214648.png", cv2.IMREAD_COLOR)
    trace = {}
    assert run_detector("halo_timer", frame, detector_assets("halo_timer"), trace) is not None
    height, width = frame.shape[:2]
    assert halo_timer.read_seconds(frame[:height // 4, width // 4:3 * width // 4]) == 14 * 60 + 46
