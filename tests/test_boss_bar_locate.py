"""보스 체력바 영역 자동 찾기 회귀 테스트 (tests/data 스샷 기준).

색이 아니라 '연속 솔리드 가로 바' 구조로 찾는지 검증:
- 레넨 미이르(보라)·고목 페타크(노랑/빨강) 등 **색이 다른 보스**를 같은 로직으로 정확 검출.
- 보스전이 아닌(마을 등) 스샷은 None(→ 호출 측 '보스바 노출 확인' 안내).

스샷이 없는 환경에서는 skip.
"""

import os

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect.boss_bar import locate_boss_bar, make_validator


def _img(name: str):
    path = f"tests/data/{name}"
    if not os.path.exists(path):
        pytest.skip(f"스샷 없음: {name}")
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        pytest.skip(f"스샷 로드 실패: {name}")
    return img


# (파일명, 기대 bbox) — 색이 다른 보스들: 레넨(보라), 고목 페타크(노랑/빨강)
_PRESENT = [
    ("스크린샷 2026-10-12 000512.png", (1016, 1246, 521, 37)),  # 레넨(보라)
    ("스크린샷 2026-10-12 200511.png", (1016, 1246, 521, 37)),  # 레넨(보라)
    ("스크린샷 2026-10-09 190901.png", (1018, 1244, 521, 45)),  # 레넨(보라)
    ("스크린샷 2026-10-09 200724.png", (1018, 1247, 521, 38)),  # 고목 페타크(빨강)
]


@pytest.mark.parametrize("name,box", _PRESENT)
def test_locate_boss_bar(name, box):
    got = locate_boss_bar(_img(name))
    assert got is not None, f"{name}: 보스바를 못 찾음"
    ex, ey, ew, eh = box
    gx, gy, gw, gh = got
    assert abs(gx - ex) <= 12 and abs(gy - ey) <= 12, f"{name}: 위치 {got} != {box}"
    assert abs(gw - ew) <= 30, f"{name}: 폭 {gw} != {ew}"


def test_boss_bar_handles_empty():
    assert locate_boss_bar(None) is None
    assert locate_boss_bar(np.zeros((0, 0, 3), np.uint8)) is None
    assert locate_boss_bar(np.zeros((30, 30, 3), np.uint8)) is None


# --- 검증기(make_validator): '이름 글자 + % 판독'이면 모든 보스 통과(등록 여부 무관) ---


def test_validator_accepts_unregistered_boss():
    """이름 템플릿이 없는 보스(글라스 기브넨)도 자동 찾기가 돼야 한다(디버프 트래커는
    모든 보스에서 쓴다). 지난 커밋은 등록 5개 보스만 식별해 여기서 None으로 회귀했었다."""
    box = locate_boss_bar(_img("스크린샷 2026-10-09 190901.png"), make_validator())
    assert box is not None, "미등록 보스에서 검증 실패(회귀)"
    assert 480 <= box[2] <= 560, f"폭 이상 {box}"


@pytest.mark.parametrize(
    "name", ["스크린샷 2026-10-09 200614.png", "스크린샷 2026-10-09 201512.png"]
)
def test_validator_splits_pelrom_upper_bar(name):
    """펠롬은 보스 HP바 밑에 '어둠의 에르그' 바가 붙어 한 덩어리(h≈66)로 잡힌다.
    위(보스 HP바)만 분리해 검증을 통과해야 한다(병합 상태면 % 판독 실패로 None이었다)."""
    box = locate_boss_bar(_img(name), make_validator())
    assert box is not None, f"{name}: 펠롬 상단 바 분리 실패"
    assert box[3] <= 50, f"{name}: 2단 병합(h={box[3]}) — 분리 안 됨"


def test_locate_trims_attached_chat():
    """바 왼쪽에 채팅 글자가 붙어 박스가 과하게 넓어지던 것(x=890 폭=649)을
    열 채움으로 다듬어 실제 바에 가깝게 좁힌다(디버프 영역에 채팅이 섞이지 않도록)."""
    box = locate_boss_bar(_img("스크린샷 2026-10-09 193901.png"))
    assert box is not None
    gx, gy, gw, gh = box
    assert gx >= 980, f"왼쪽 경계가 여전히 채팅 포함 {box}"
    assert gw <= 560, f"폭이 여전히 과도(채팅 포함) {box}"
