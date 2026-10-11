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
    # 뚜렷한 고대비 패턴 아이콘(랜덤 노이즈는 축소·영역폭에 따라 매칭 점수가 불안정).
    a = np.zeros((28, 28, 3), dtype=np.uint8)
    a[4:24, 4:24] = (255, 60, 60)  # 파란 사각 블록
    a[10:18, 10:18] = (40, 230, 230)  # 가운데 노란 점
    b = np.zeros((28, 28, 3), dtype=np.uint8)
    b[2:26, 2:26] = (40, 220, 40)  # 초록 테두리 블록
    b[8:20, 8:20] = (0, 0, 0)  # 가운데 구멍
    return {"a": a, "b": b}


# 보스 HP바가 보일 때만 탐지하도록 게이팅하므로, 탐지 로직 테스트 영역에는 항상
# '보스 HP바 프레임'(테두리 사각형)을 포함시킨다. 상단 텍스처 영역에 디버프 아이콘을 둔다.
# detect.bar_frame.locate_bar_frame이 찾을 수 있게: 폭 넉넉, 상/하단 어두운 테두리.
_BAR_FILL = (160, 60, 120)  # BGR, 바 채움


def _bar_base(h=70, w=420):
    """상단 텍스처(디버프 영역) + 가운데 보스 HP바 프레임(어두운 테두리 + 채움)."""
    r = np.random.default_rng(8).integers(0, 255, (h, w, 3), dtype=np.uint8)
    r[34:60, 40:380] = _BAR_FILL  # 바 채움
    r[34:36, 40:380] = (20, 20, 20)  # 상단 테두리(어둡게 → 강한 가로엣지)
    r[58:60, 40:380] = (20, 20, 20)  # 하단 테두리
    return r


def _region_with(base):
    """보스 바가 있는 영역의 상단에 화면 크기(ICON) 디버프 아이콘을 배치(걸린 상태)."""
    region = _bar_base()
    icon = cv2.resize(base, (ICON, ICON), interpolation=cv2.INTER_AREA)
    region[6 : 6 + ICON, 60 : 60 + ICON] = icon  # 바 위쪽 텍스처 영역
    return region


def _empty():
    """보스 바는 있고(= 보스 존재) 디버프 아이콘은 없는 영역."""
    return _bar_base()


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
    region = np.random.default_rng(3).integers(0, 255, (120, 460, 3), dtype=np.uint8)
    # 보스 HP바 프레임(테두리+채움) — 가장자리 아닌 안쪽에 둬 상/하단 테두리가 잡히게.
    region[80:106, 50:420] = _BAR_FILL
    region[80:82, 50:420] = (20, 20, 20)
    region[104:106, 50:420] = (20, 20, 20)
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
def _noise(h=70, w=420):
    """바(프레임)가 없는 텍스처만 — 보스 없음(마을·필드)."""
    return np.random.default_rng(7).integers(0, 255, (h, w, 3), dtype=np.uint8)


def _bar_region(h=70, w=420):
    return _bar_base()


def test_bar_gating_suppresses_after_grace():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    # 바가 보이면 정상 탐지(디버프 없음 → 전부 미적용 표시)
    assert _shown(eng.tick(_bar_region(), now=0.0)) == ["a", "b"]
    # 바가 잠깐 사라져도(유예 안) 깜빡이지 않게 직전처럼 유지
    assert _shown(eng.tick(_noise(), now=0.3)) == ["a", "b"]
    # 유예(_BAR_GRACE_SEC)를 넘겨 계속 없으면 → 보스 없음 확정, 숨김
    assert _shown(eng.tick(_noise(), now=2.0)) == []
    # 다시 바가 보이면 즉시 복귀
    assert _shown(eng.tick(_bar_region(), now=2.2)) == ["a", "b"]


def test_no_bar_region_shows_nothing():
    # 보스 HP바를 한 번도 못 봤으면(마을·필드 = 전투 전) 아무것도 표시하지 않는다.
    # (게임 시작 직후 바닥 텍스처에 디버프/모모가 오탐되던 버그 방지)
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    assert DebuffEngine._bar_present(_noise()) is False
    assert _shown(eng.tick(_noise(), now=0.0)) == []
    # 바가 나타나면 그때부터 정상 탐지
    assert _shown(eng.tick(_bar_base(), now=0.1)) == ["a", "b"]


# ---- 사라짐 경고(디버프가 보스에서 떨어짐) ----
def _bar_with_icon(base):
    """바(보스 존재) + 상단 텍스처에 디버프 아이콘(걸린 상태)."""
    r = _bar_base()
    icon = cv2.resize(base, (ICON, ICON), interpolation=cv2.INTER_AREA)
    r[6 : 6 + ICON, 60 : 60 + ICON] = icon
    return r


def _gone_ids(res):
    return [e.buff_id for e in res.entries if e.gone]


def test_warn_gone_fires_after_3s_absence_with_bar():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_warn_gone_ids({"a"})
    assert DebuffEngine._bar_present(_bar_with_icon(tpl["a"])) is True
    # a 걸림(바+아이콘) → 적용(숨김), applied 기록
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0)
    # a 떨어짐(바만, 아이콘 없음) — 확정 전엔 경고 없음
    eng.tick(_bar_region(), now=0.2)
    assert _gone_ids(eng.tick(_bar_region(), now=2.9)) == []
    # 바 보이는 동안 3초 연속 미검출 → 확정(alert + gone)
    res = eng.tick(_bar_region(), now=3.2)
    assert res.alerts == ["a"]
    assert _gone_ids(res) == ["a"]
    # 노출(확정 후 3초) 지나면 경고 해제(일반 '미적용' 표시로 복귀)
    res2 = eng.tick(_bar_region(), now=6.3)
    assert _gone_ids(res2) == []
    assert "a" in _shown(res2)  # 여전히 미적용 목록엔 있음


def test_warn_gone_cancelled_if_boss_leaves():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_warn_gone_ids({"a"})
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0)  # a 걸림
    eng.tick(_bar_region(), now=0.2)  # 떨어지기 시작(확정 대기)
    # 보스 이탈(바 없음) 유예 넘김 → 확정 취소, 경고 없음
    eng.tick(_noise(), now=0.5)
    res = eng.tick(_noise(), now=2.0)
    assert res.alerts == [] and _gone_ids(res) == []
    # 그 뒤 바가 다시 와도(확정 대기 리셋됨) 과거 떨어짐으로 울리지 않음
    res2 = eng.tick(_bar_region(), now=2.3)
    assert res2.alerts == []


def test_warn_gone_cancelled_if_reapplied():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_warn_gone_ids({"a"})
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0)  # 걸림
    eng.tick(_bar_region(), now=0.2)  # 떨어짐(대기)
    eng.tick(_bar_with_icon(tpl["a"]), now=1.0)  # 3초 전에 다시 걸림 → 취소
    res = eng.tick(_bar_region(), now=1.2)  # 다시 떨어짐(대기 새로 시작)
    assert res.alerts == []  # 직전 대기가 리셋돼 아직 확정 아님


