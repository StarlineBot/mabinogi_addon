"""DebuffEngine: '아직 안 걸린 디버프만 표시' + 안정화(숨김 즉시 / 재표시 지연).

매칭은 영역을 _DOWNSCALE로 줄여 화면 아이콘(_ONSCREEN_ICON_PX)이 _MATCH_ICON_PX가
되게 한 뒤 수행한다. 그래서 영역을 크게(여유 있게) 잡아도 동작한다. 테스트는 등록
아이콘(28px)과, 화면에 그 디버프가 _ONSCREEN_ICON_PX로 그려진 상황을 가정한다.
"""

import cv2
import numpy as np

from mabinogi_addon.tracker.debuff_engine import _ONSCREEN_ICON_PX, DebuffEngine

ICON = _ONSCREEN_ICON_PX  # 화면상 디버프 아이콘 크기(px)


def _bases():
    rng = np.random.default_rng(0)
    a = rng.integers(0, 255, (28, 28, 3), dtype=np.uint8)
    b = rng.integers(0, 255, (28, 28, 3), dtype=np.uint8)
    return {"a": a, "b": b}


def _region_with(base):
    """여유 있는(줄보다 큰) 영역에 화면 크기(ICON) 아이콘을 배치."""
    region = np.zeros((28, 140, 3), np.uint8)
    icon = cv2.resize(base, (ICON, ICON), interpolation=cv2.INTER_AREA)
    region[6 : 6 + ICON, 30 : 30 + ICON] = icon
    return region


def _empty():
    return np.zeros((28, 140, 3), np.uint8)


def _shown(result):
    return [e.buff_id for e in result.entries]


def test_detected_debuff_hidden_immediately():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    assert _shown(eng.tick(_region_with(tpl["a"]), now=0.0)) == ["b"]


def test_reappear_only_after_debounce():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"], reappear_sec=1.5)
    eng.tick(_region_with(tpl["a"]), now=0.0)  # a 숨김
    assert _shown(eng.tick(_empty(), now=0.5)) == ["b"]  # 아직 재표시 안 함
    assert _shown(eng.tick(_empty(), now=2.1)) == ["a", "b"]  # 1.5초 경과 → 재표시


def test_redetect_hides_again_immediately():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"], reappear_sec=1.5)
    eng.tick(_empty(), now=0.0)  # 둘 다 표시
    assert _shown(eng.tick(_region_with(tpl["b"]), now=0.2)) == ["a"]


def test_order_and_no_duration_no_alert():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["b", "a"])
    res = eng.tick(_empty(), now=0.0)
    assert _shown(res) == ["b", "a"]  # 등록 순서 유지
    assert all(e.remaining is None and not e.alerting for e in res.entries)
    assert res.alerts == []


def test_works_with_loose_region():
    # 영역을 디버프 줄보다 훨씬 크게 잡아도(여백 많아도) 화면 아이콘 크기로 매칭된다.
    tpl = _bases()
    region = np.zeros((120, 300, 3), np.uint8)  # 아주 넉넉한 영역
    icon = cv2.resize(tpl["a"], (ICON, ICON), interpolation=cv2.INTER_AREA)
    region[50 : 50 + ICON, 40 : 40 + ICON] = icon
    eng = DebuffEngine(tpl, ["a", "b"])
    assert _shown(eng.tick(region, now=0.0)) == ["b"]


def test_set_order_live():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_order(["b", "a"])
    assert _shown(eng.tick(_empty(), now=0.0)) == ["b", "a"]


# ---- 보스 HP바 앵커 게이팅(오탐 방지) ----
from pathlib import Path

_SHOTS = Path(__file__).parent / "data"


def _bottom_region(name, y0=0.80, y1=0.905, x0=0.30, x1=0.72):
    im = cv2.imread(str(_SHOTS / name))
    assert im is not None, name
    h, w = im.shape[:2]
    return im[int(h * y0) : int(h * y1), int(w * x0) : int(w * x1)]


def test_bar_present_real_boss_vs_town():
    """실게임 캡처: 보스 체력바가 있으면 True, 마을(풀밭)은 False(색 무관)."""
    boss = _bottom_region("스크린샷 2026-10-09 190901.png")
    town = _bottom_region("스크린샷 2026-10-06 223724.png")
    assert DebuffEngine._bar_present(boss) is True
    assert DebuffEngine._bar_present(town) is False


def _noise(h=28, w=140):
    return np.random.default_rng(7).integers(0, 255, (h, w, 3), dtype=np.uint8)


def _bar_region(h=40, w=160):
    """위쪽 텍스처(디버프 영역) + 아래쪽 매끈한 가로 띠(보스 HP바 모의)."""
    r = np.random.default_rng(8).integers(0, 255, (h, w, 3), dtype=np.uint8)
    r[22:40, :] = (160, 60, 120)  # 매끈한 바 띠(폭 전체, 세로로 두껍게)
    return r


def test_bar_gating_suppresses_when_boss_absent():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    # 바가 보이면 정상 탐지(디버프 없음 → 전부 미적용 표시)
    assert _shown(eng.tick(_bar_region(), now=0.0)) == ["a", "b"]
    # 바를 본 뒤 바가 사라지면(보스 없음) → 아무것도 표시 안 함(오탐 차단)
    assert _shown(eng.tick(_noise(), now=0.2)) == []


def test_backward_compat_no_bar_region_always_detects():
    # 바를 한 번도 못 본 영역(텍스처만) → 게이팅 안 함 → 기존처럼 전부 표시
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    assert DebuffEngine._bar_present(_noise()) is False
    assert _shown(eng.tick(_noise(), now=0.0)) == ["a", "b"]
