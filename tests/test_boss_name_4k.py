"""0.31.0 4K 보스 이름 식별·HP 판독(사용자 제보: 4K에서 보스 패턴·1분 헤일로가 전혀 안 뜸).

- 4K 이름 글자는 굵게 그려져 기존 템플릿과 회한 0.40·레넨 0.46(< 0.6) → 이름 변형(scripts/build_boss_name_uhd.py, 214648로 만듦).
  접두어 함정 때문에 회한 전체와 '레넨의 미이르'까지를 둘 다 변형으로 둔다. 0055251·214051은 만들 때 안 쓴 장.
- 4K HP '86.15%'를 '8'(점수 0.59)로 읽던 것: 4K '8'·'6' 샘플 추가 + 실행 중에도 점수 0.6 미만은 None.
"""
import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.detect import boss_hp_reader, boss_name_matcher

BAR_4K = (1658, 1968, 521, 37)
CASES = {  # 파일 → (바 상자, 보스 id, HP 정수)
    "mabinogi_2026_10_31_0055251.png": (BAR_4K, "lenen_miir_hoehan", 86),  # 세트에 안 쓴 장
    "mabinogi_2026_10_30_214648.png": (BAR_4K, "lenen_miir_hoehan", 100),
    "mabinogi_2026_10_30_214051.png": (BAR_4K, "lenen_miir", 100),  # 일반 레넨 4K — 세트에 안 쓴 장
    "2026-10-30_windowed_wireweb_3.png": ((1011, 1218, 521, 36), "lenen_miir", 99),  # 창 모드 그대로
    "mabinogi_2026_10_30_213520.png": ((1658, 1967, 521, 37), None, 76),  # 목록 밖 보스(불완전한 공상)
    # 0.31.0 2단계(글자 높이 맞춤) 식별: 213927·213942는 고목의 페타크(바 확인 — 예전 표의 '목록 밖'은 잘못 적은 것)
    "mabinogi_2026_10_30_213927.png": (BAR_4K, "gomok_petak", 100),
    "mabinogi_2026_10_30_213942.png": (BAR_4K, "gomok_petak", 99),
    "mabinogi_2026_10_30_214016.png": (BAR_4K, "brontanas", 100),  # 브론타나스 — 0.33.0 명세 변경: 등록(예전 목록 밖 None)
}


def _bar(name, box):
    frame = image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)
    x, y, w, h = box
    return frame[y:y + h, x:x + w]


@pytest.mark.parametrize("name", sorted(CASES))
def test_4k_boss_identified_and_hp_read(name):
    box, boss, percent = CASES[name]
    bar = _bar(name, box)
    assert boss_name_matcher.identify(bar[:, :int(bar.shape[1] * 0.60)]) == boss
    assert boss_hp_reader.read_percent(bar[:, int(bar.shape[1] * 0.58):]) == percent  # boss_tab과 같은 자르기
    assert boss_hp_reader.read_percent(bar) == percent


def test_hoehan_variant_does_not_swallow_plain_lenen():
    """회한 4K 바에서 ': 회한'을 지우면 일반 레넨으로(접두어 함정)."""
    bar = _bar("mabinogi_2026_10_30_214648.png", BAR_4K).copy()
    bar[:, 118:180] = bar[0, 300]
    assert boss_name_matcher.identify(bar[:, :312]) == "lenen_miir"


def test_low_score_reading_is_none_not_wrong():
    """4K 샘플 없이 읽으면 '86'을 '8'(0.59)로 겨우 맞추던 판독 → 이제 값 대신 None."""
    legacy = boss_hp_reader._load_digits(exclude=boss_hp_reader.UHD_DIGIT_SAMPLES)
    bar = _bar("mabinogi_2026_10_31_0055251.png", BAR_4K)
    assert boss_hp_reader.read_percent(bar, legacy) is None
    assert boss_hp_reader.VALUE_MIN_SCORE == 0.6
