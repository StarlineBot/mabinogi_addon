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

from mabinogi_addon.detect.boss_bar import (
    has_wide_bar_row,
    locate_boss_bar,
    make_validator,
)
from mabinogi_addon.detect.boss_hp_reader import read_percent


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


# --- 박스 높이 정규화: 큰 HP바(글라스 기브넨 45px)로 설정해도 공유 영역이 커져 다른
#     보스 HP가 1/10로 읽히던 문제. 세로 중심 유지 + 높이 고정으로 어느 보스에서 설정해도
#     같은 박스가 나와야 한다(= 어느 보스를 읽어도 정확). ---

_GLASS = "스크린샷 2026-10-09 190901.png"  # HP바가 큰(45px) 미등록 보스
_GOMOK25 = "스크린샷 2026-10-09 200715.png"  # 고목 25% (박스 h=38로 잡히던 장면)
_LENEN100 = "스크린샷 2026-10-07 013118.png"  # 레넨 100%


def _read_with(box, name):
    img = _img(name)
    x, y, w, h = box
    return read_percent(img[y : y + h, x : x + w])


def test_glass_box_reads_other_boss_correctly():
    """큰 HP바(글라스)에서 찾은 박스로 레넨(100%)을 읽어도 100이어야 한다(10 아님)."""
    box = locate_boss_bar(_img(_GLASS), make_validator())
    assert box is not None
    assert _read_with(box, _LENEN100) == 100, f"정규화 전이면 10으로 읽힘 (box={box})"


def test_gomok25_box_reads_pelrom_correctly():
    """고목 25% 장면(h=38) 박스로 펠롬 42%를 읽어도 42여야 한다(4 아님)."""
    box = locate_boss_bar(_img(_GOMOK25), make_validator())
    assert box is not None
    assert _read_with(box, "스크린샷 2026-10-09 201512.png") == 42, f"box={box}"


def test_normalized_box_height_consistent_across_bosses():
    """어느 보스에서 설정하든 박스 y·h가 ±1px 이내로 같아야 한다(세로 중심·고정 높이)."""
    boxes = [
        locate_boss_bar(_img(n), make_validator())
        for n in (_GLASS, _LENEN100, _GOMOK25)
    ]
    assert all(b is not None for b in boxes), boxes
    ys = [b[1] for b in boxes]
    hs = [b[3] for b in boxes]
    assert max(ys) - min(ys) <= 1, f"y 불일치 {ys}"
    assert max(hs) - min(hs) <= 1, f"h 불일치 {hs}"


def test_locate_trims_attached_chat():
    """바 왼쪽에 채팅 글자가 붙어 박스가 과하게 넓어지던 것(x=890 폭=649)을
    가장자리 행 중앙값으로 좌우를 정해 실제 바에 맞춘다(디버프 영역에 채팅이 섞이지 않도록)."""
    box = locate_boss_bar(_img("스크린샷 2026-10-09 193901.png"))
    assert box is not None
    gx, gy, gw, gh = box
    assert gx >= 980, f"왼쪽 경계가 여전히 채팅 포함 {box}"
    assert gw <= 560, f"폭이 여전히 과도(채팅 포함) {box}"


# --- 주변 UI(추가 단축바 등) 배치와 무관하게 검출 (행 최장연속→채움확장 방식) ---
# 덩어리(연결 컴포넌트) 방식은 바 옆에 단축바·채팅·버프 아이콘이 붙으면 한 덩어리로 묶여
# 크기 필터에서 탈락(None)했다. 바 '자체 특징'으로 바꿔 아래 실샷·합성이 모두 검출돼야 한다.


@pytest.mark.parametrize(
    "name",
    [
        "스크린샷 2026-10-14 000646.png",  # 레넨 100% — 옆 버프 그리드가 붙어 덩어리 방식은 None이던 제보 샷
        "스크린샷 2026-10-12 200625.png",  # 레넨 99.45% (이펙트) — 덩어리 방식은 None이던 장면
    ],
)
def test_locate_despite_adjacent_ui(name):
    box = locate_boss_bar(_img(name), make_validator())
    assert box is not None, f"{name}: 주변 UI 때문에 못 찾음(회귀)"
    assert 1006 <= box[0] <= 1030, f"{name}: x 이상 {box}"
    assert 480 <= box[2] <= 560, f"{name}: 폭 이상 {box}"


def _synth_skillbar(w: int, h: int = 40) -> np.ndarray:
    """현실적 추가 단축바 합성: 채도 높은 아이콘(44×36) + 사방 어두운 테두리/간격.

    아이콘 사이·위아래가 어두워 (1) 긴 가로 연속이 없어 '씨앗'이 안 되고, (2) 바로 옆/위/
    아래에 붙여도 경계 행의 채움이 낮아 바 높이 확장에 섞이지 않는다 → 검출이 흔들리면 안 됨.
    """
    strip = np.zeros((h, w, 3), np.uint8)
    colors = [(40, 40, 200), (40, 200, 40), (200, 40, 40), (40, 180, 180), (180, 40, 180)]
    x, ci, cell = 6, 0, 56  # 아이콘 44 + 간격 12
    while x + 44 <= w:
        strip[4 : 4 + 36, x : x + 44] = colors[ci % len(colors)]
        x, ci = x + cell, ci + 1
    return strip


@pytest.mark.parametrize("where", ["right", "left", "above", "below"])
def test_locate_ignores_adjacent_skillbar(where):
    """레넨 샷에 추가 단축바를 바 오른쪽/왼쪽(2px 간격)·바로 위·바로 아래에 붙여도,
    검출 박스가 그대로여야 한다(주변 UI 배치 무관)."""
    frame = _img("스크린샷 2026-10-14 000646.png")
    base = locate_boss_bar(frame, make_validator())
    assert base is not None
    bx, by, bw, bh = base
    strip = _synth_skillbar(bw)
    sh = strip.shape[0]
    pos = {
        "right": (bx + bw + 2, by),
        "left": (bx - 2 - bw, by),
        "above": (bx, by - 2 - sh),
        "below": (bx, by + bh + 2),
    }[where]
    px, py = pos
    f = frame.copy()
    f[py : py + sh, px : px + bw] = strip
    got = locate_boss_bar(f, make_validator())
    assert got == base, f"{where}: 단축바 때문에 검출이 바뀜 {got} != {base}"


# --- 존재 판정 값싼 사전 컷(has_wide_bar_row): 비싼 make_validator 호출 전 평상시 프레임을
#     빠르게 거르는 용도. '진짜 보스바는 절대 끊지 않는다'(통과)가 핵심 불변식. ---


def test_has_wide_bar_row_passes_real_boss_box():
    """실제 보스바 박스는 사전 컷을 통과해야 한다(끊으면 보스를 놓침)."""
    img = _img("스크린샷 2026-10-14 000646.png")
    box = locate_boss_bar(img, make_validator())
    assert box is not None
    x, y, w, h = box
    assert has_wide_bar_row(img[y : y + h, x : x + w]) is True


def test_has_wide_bar_row_rejects_empty():
    """빈/없는 프레임은 넓은 가로 연속이 없어 즉시 False(검증기 호출 안 함)."""
    assert has_wide_bar_row(np.zeros((36, 523, 3), np.uint8)) is False
    assert has_wide_bar_row(None) is False
