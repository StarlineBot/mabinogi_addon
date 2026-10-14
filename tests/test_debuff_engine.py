"""DebuffEngine: '아직 안 걸린 디버프만 표시' + 안정화(숨김 즉시 / 재표시 지연).

매칭은 영역을 _DOWNSCALE로 줄여 화면 아이콘(_ONSCREEN_ICON_PX)이 _MATCH_ICON_PX가
되게 한 뒤 수행한다. 그래서 영역을 크게(여유 있게) 잡아도 동작한다. 테스트는 등록
아이콘(28px)과, 화면에 그 디버프가 _ONSCREEN_ICON_PX로 그려진 상황을 가정한다.
"""

import cv2
import numpy as np

from mabinogi_addon import image_io
import mabinogi_addon.tracker.debuff_engine as de
from mabinogi_addon.tracker.debuff_engine import (
    _GONE_SHOW_SEC,
    _ONSCREEN_ICON_PX,
    DEBUFF_DETECT_THRESHOLD,
    DebuffEngine,
)

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


def test_detected_debuff_hidden_after_confirm():
    # 검출 디바운스: 한 프레임만으론 '걸림' 확정 안 함 → _DETECT_CONFIRM_SEC 연속돼야 숨김.
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    assert _shown(eng.tick(_region_with(tpl["a"]), now=0.0)) == ["a", "b"]  # 아직 확정 전
    assert _shown(eng.tick(_region_with(tpl["a"]), now=0.4)) == ["b"]  # 확정 → a 숨김


def test_single_frame_spike_not_latched():
    # 지나가는 이펙트처럼 한 프레임만 매칭되면(다음 프레임 사라짐) '걸림'으로 래치되지 않는다.
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.tick(_region_with(tpl["a"]), now=0.0)  # 단발 매칭
    assert _shown(eng.tick(_empty(), now=0.1)) == ["a", "b"]  # 사라짐 → 확정 안 돼 그대로 표시


def test_reappear_only_after_debounce():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"], reappear_sec=1.5)
    eng.tick(_region_with(tpl["a"]), now=0.0)
    eng.tick(_region_with(tpl["a"]), now=0.4)  # a 확정 → 숨김
    assert _shown(eng.tick(_empty(), now=0.6)) == ["b"]  # 아직 재표시 안 함
    assert _shown(eng.tick(_empty(), now=2.2)) == ["a", "b"]  # 1.5초 경과 → 재표시


def test_redetect_hides_again_after_confirm():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"], reappear_sec=1.5)
    eng.tick(_empty(), now=0.0)  # 둘 다 표시
    eng.tick(_region_with(tpl["b"]), now=0.2)
    assert _shown(eng.tick(_region_with(tpl["b"]), now=0.6)) == ["a"]  # b 확정 → 숨김


def test_short_gap_recovery_keeps_applied_debuff_hidden():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a"])
    present = _region_with(tpl["a"])
    for now in (0.0, 0.151, 0.302):
        eng.tick(present, now=now)
    for cycle in range(10):
        start = cycle * 1.0
        for now in (start + 0.453, start + 0.604):
            assert _shown(eng.tick(_empty(), now=now)) == []
        for now in (start + 0.755, start + 0.906, start + 1.057, start + 1.208):
            assert _shown(eng.tick(present, now=now)) == []
            assert eng._absent_since["a"] is None


def test_new_missing_interval_starts_after_unconfirmed_recovery():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a"])
    present = _region_with(tpl["a"])
    eng.tick(present, now=0.0)
    eng.tick(present, now=0.302)
    eng.tick(_empty(), now=0.453)
    eng.tick(present, now=0.755)
    assert _shown(eng.tick(_empty(), now=0.906)) == []
    assert _shown(eng.tick(_empty(), now=1.208)) == []
    assert _shown(eng.tick(_empty(), now=1.359)) == ["a"]


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
    eng.tick(region, now=0.0)
    assert _shown(eng.tick(region, now=0.4)) == ["b"]  # 확정 후 숨김


def test_set_order_live():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_order(["b", "a"])
    assert _shown(eng.tick(_empty(), now=0.0)) == ["b", "a"]


# ---- 보스 HP바 앵커 게이팅(오탐 방지) ----
from pathlib import Path

_SHOTS = Path(__file__).parent / "data"


def _bottom_region(name, y0=0.80, y1=0.905, x0=0.30, x1=0.72):
    im = image_io.imread(_SHOTS / name)
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


def _black_bar_region(h=40, w=160):
    """빈사 직전 보스 바: 아래쪽이 '평평한 검은 띠'(어둡지만 가로로 매끈)."""
    r = np.random.default_rng(8).integers(0, 255, (h, w, 3), dtype=np.uint8)
    r[22:40, :] = (8, 8, 8)  # 어둡고 매끈한 띠 — 밝은 바 조건엔 탈락하나 '바닥'은 아님
    return r


def _black_bar_with_icon(base):
    """빈사 검은 바 + 상단에 걸린 디버프 아이콘."""
    r = _black_bar_region()
    icon = cv2.resize(base, (ICON, ICON), interpolation=cv2.INTER_AREA)
    r[3 : 3 + ICON, 30 : 30 + ICON] = icon
    return r


def test_overlay_always_shown_regardless_of_bar():
    # 상시 노출: 바가 보이든(보스 존재) 안 보이든(보스 이탈) 오버레이는 계속 표시한다.
    # 예전엔 바가 유예를 넘겨 안 보이면 통째로 숨겼지만(게이팅), 바 인식이 불완전해
    # 멀쩡히 보여야 할 때 오버레이가 사라지는 게 버그처럼 보여 게이팅을 걷어냈다.
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    assert _shown(eng.tick(_bar_region(), now=0.0)) == ["a", "b"]
    assert _shown(eng.tick(_noise(), now=0.3)) == ["a", "b"]
    # 유예(_BAR_GRACE_SEC)를 넘겨 계속 바가 없어도 숨기지 않는다.
    assert _shown(eng.tick(_noise(), now=2.0)) == ["a", "b"]
    # 다시 바가 보여도 그대로 표시.
    assert _shown(eng.tick(_bar_region(), now=2.2)) == ["a", "b"]


def test_no_bar_region_always_detects():
    # 바가 없는 영역(텍스처만)에서도 기존처럼 전부 표시.
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    assert DebuffEngine._bar_present(_noise()) is False
    assert _shown(eng.tick(_noise(), now=0.0)) == ["a", "b"]


# ---- 사라짐 경고(디버프가 보스에서 떨어짐) ----
def _bar_with_icon(base):
    """바(보스 존재) + 상단 텍스처에 디버프 아이콘(걸린 상태)."""
    r = _bar_region()
    icon = cv2.resize(base, (ICON, ICON), interpolation=cv2.INTER_AREA)
    r[3 : 3 + ICON, 30 : 30 + ICON] = icon
    return r


def _gone_ids(res):
    return [e.buff_id for e in res.entries if e.gone]


def test_warn_gone_fires_after_3s_absence_with_bar():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_warn_gone_ids({"a"})
    assert DebuffEngine._bar_present(_bar_with_icon(tpl["a"])) is True
    # a 걸림(바+아이콘) → 디바운스 확정(2틱)으로 적용, applied 기록
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0)
    eng.tick(_bar_with_icon(tpl["a"]), now=0.3)
    # a 떨어짐(바만, 아이콘 없음) — 확정 전엔 경고 없음
    eng.tick(_bar_region(), now=0.5)
    assert _gone_ids(eng.tick(_bar_region(), now=3.4)) == []  # 0.5+3초 전
    # 바 보이는 동안 3초 연속 미검출 → 확정(alert + gone)
    res = eng.tick(_bar_region(), now=3.6)
    assert res.alerts == ["a"]
    assert _gone_ids(res) == ["a"]
    # 노출(확정 후 _GONE_SHOW_SEC) 지나면 경고 해제(일반 '미적용' 표시로 복귀)
    res2 = eng.tick(_bar_region(), now=3.6 + _GONE_SHOW_SEC + 0.1)
    assert _gone_ids(res2) == []
    assert "a" in _shown(res2)  # 여전히 미적용 목록엔 있음


def test_warn_gone_cancelled_if_boss_leaves():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_warn_gone_ids({"a"})
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0)  # a 걸림
    eng.tick(_bar_with_icon(tpl["a"]), now=0.3)  # 확정
    eng.tick(_bar_region(), now=0.5)  # 떨어지기 시작(확정 대기)
    # 보스 이탈(바 없음) 유예 넘김 → 확정 취소, 경고 없음
    eng.tick(_noise(), now=0.8)
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
    eng.tick(_bar_with_icon(tpl["a"]), now=0.3)  # 확정
    eng.tick(_bar_region(), now=0.5)  # 떨어짐(대기)
    eng.tick(_bar_with_icon(tpl["a"]), now=0.8)  # 다시 걸림
    eng.tick(_bar_with_icon(tpl["a"]), now=1.1)  # 재확정 → 대기 취소
    res = eng.tick(_bar_region(), now=1.3)  # 다시 떨어짐(대기 새로 시작)
    assert res.alerts == []  # 직전 대기가 리셋돼 아직 확정 아님


def test_no_bar_region_never_warns():
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_warn_gone_ids({"a"})
    # 바 없는(하위호환) 영역: a가 보였다 안 보여도 경고 안 울림
    eng.tick(_region_with(tpl["a"]), now=0.0)
    eng.tick(_empty(), now=0.2)
    res = eng.tick(_empty(), now=4.0)
    assert res.alerts == [] and _gone_ids(res) == []


def _real_debuff_templates():
    from pathlib import Path as _P

    d = _P("src/mabinogi_addon/assets/debuff/icon")
    out = {}
    for name in ("방해 카드", "모모"):
        t = image_io.imread(d / f"{name}.png")
        if t is not None:
            out[name] = t
    return out


def _user_region(name):
    im = image_io.imread(_SHOTS / name)
    assert im is not None, name
    h, w = im.shape[:2]
    sx, sy = w / 2560.0, h / 1440.0
    y, x = int(1210 * sy), int(1017 * sx)
    return im[y : y + int(79 * sy), x : x + int(524 * sx)]


def test_bar_present_rejects_dark_grass():
    """어두운 녹색 풀밭(채도 높고 균일하나 어두움)은 보스 바로 오인하지 않는다.

    예전엔 매끈+유채색만 보고 True가 됐다(들쑥날쑥 오탐). 밝기 조건 추가로 False.
    """
    assert DebuffEngine._bar_present(_user_region("스크린샷 2026-10-06 224732.png")) is False
    # 대조: 실제 보스 바가 있는 영역은 True
    assert DebuffEngine._bar_present(_user_region("스크린샷 2026-10-09 190901.png")) is True


def test_background_not_matched_when_boss_absent():
    """보스 바가 없으면(빈 바닥) 매칭을 멈춰 배경 오탐을 막는다.

    실게임: 바닥 텍스처가 방해 카드·모모 템플릿에 ≥0.68로 오매칭된다(아래 전제 확인).
    보스 바가 있는 영역으로 bar_seen을 세운 뒤 빈 바닥으로 가면, 매칭이 중단되고
    전부 '미적용'으로 표시돼야 한다(이력 임계 래치 오탐도 풀림).
    """
    tpl = _real_debuff_templates()
    if len(tpl) < 2:
        import pytest

        pytest.skip("디버프 템플릿 없음")
    order = list(tpl)
    # 보스 바가 있는 영역(실게임) — bar_seen 설정용
    boss = image_io.imread(_SHOTS / "스크린샷 2026-10-12 000512.png")
    floor = image_io.imread(_SHOTS / "스크린샷 2026-10-12 024008.png")
    assert boss is not None and floor is not None
    boss_reg = boss[1210:1210 + 79, 1017:1017 + 524]
    floor_reg = floor[1210:1210 + 79, 1017:1017 + 524]
    assert DebuffEngine._bar_present(boss_reg) is True
    assert DebuffEngine._bar_present(floor_reg) is False
    # 전제: 바닥이 실제로 ≥0.68로 오매칭된다(이 테스트가 막으려는 상황)
    probe = DebuffEngine(tpl, order).best_scores(floor_reg)
    assert max(probe.values()) >= DEBUFF_DETECT_THRESHOLD  # 바닥이 실제로 오매칭됨

    eng = DebuffEngine(tpl, order, bar_gating=True)
    eng.tick(boss_reg, now=0.0)  # 바 인식 → bar_seen=True
    eng.tick(floor_reg, now=0.2)  # 바 사라짐(유예 내)
    res = eng.tick(floor_reg, now=2.0)  # 유예 후 → 보스 없음 → 매칭 중단·리셋
    shown = [e.buff_id for e in res.entries]
    assert set(shown) == set(order)  # 바닥 오탐 없이 전부 미적용 표시
    assert res.alerts == []


def test_is_background_real_floor_vs_boss():
    """실게임: 빈 바닥은 '배경'(True), 보스 바가 있으면 '배경 아님'(False)."""
    boss = image_io.imread(_SHOTS / "스크린샷 2026-10-12 000512.png")
    floor = image_io.imread(_SHOTS / "스크린샷 2026-10-12 024008.png")
    assert boss is not None and floor is not None
    boss_reg = boss[1210:1210 + 79, 1017:1017 + 524]
    floor_reg = floor[1210:1210 + 79, 1017:1017 + 524]
    assert DebuffEngine._is_background(floor_reg) is True  # 바닥 → 리셋 허용
    assert DebuffEngine._is_background(boss_reg) is False  # 보스 바 → 리셋 금지


def test_near_death_black_bar_is_not_background():
    """빈사 직전 '평평한 검은 바'는 밝은 바 조건엔 탈락해도 '배경'이 아니다.

    (검은 바도 가로로 매끈한 띠라, 매끈 가로런이 0줄인 실바닥과 명확히 갈린다.)
    """
    r = _black_bar_region()
    assert DebuffEngine._bar_present(r) is False  # 어두워서 밝은 바로는 안 잡힘
    assert DebuffEngine._is_background(r) is False  # 그러나 바닥도 아님(띠가 남음)


def test_applied_debuff_not_reset_on_near_death_black_bar():
    """빈사(검은 바)를 '보스 없음'으로 오판해 걸린 디버프를 리셋하지 않는다.

    리셋하면 '안 걸림'으로 떠서 재갱신하러 보스에게 다가가다 죽을 수 있다 — 위험 시나리오.
    """
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"], bar_gating=True)
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0)  # a 걸림(디바운스 대기)
    assert _shown(eng.tick(_bar_with_icon(tpl["a"]), now=0.4)) == ["b"]  # a 확정 → 숨김
    # 보스가 빈사 → 검은 바. 유예를 한참 넘겨도 a는 미적용으로 리셋되지 않는다.
    eng.tick(_black_bar_with_icon(tpl["a"]), now=0.6)
    assert _shown(eng.tick(_black_bar_with_icon(tpl["a"]), now=3.0)) == ["b"]  # a 계속 숨김


def _icon_on_noise(base):
    """바 없이 노이즈 배경 + 걸린 디버프 아이콘(바닥처럼 보이나 아이콘은 계속 보임)."""
    r = _noise(h=40, w=160)
    icon = cv2.resize(base, (ICON, ICON), interpolation=cv2.INTER_AREA)
    r[3 : 3 + ICON, 30 : 30 + ICON] = icon
    return r


def test_gating_off_by_default_never_resets():
    """기본(게이팅 OFF) = 기존 방식: 바가 없어도 매칭을 멈추거나 리셋하지 않는다.

    아이콘이 계속 보이면(=실제로 걸려 있으면) 바가 없다고 '미적용'으로 되돌리지 않는다.
    바닥 오탐은 감수하되(비치명적) 보스 바 인식에 의존하지 않는 예측 가능한 동작.
    """
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])  # bar_gating 기본 False
    eng.tick(_icon_on_noise(tpl["a"]), now=0.0)
    assert _shown(eng.tick(_icon_on_noise(tpl["a"]), now=0.4)) == ["b"]  # a 확정 → 숨김
    # 바가 전혀 없고 배경 같은 영역이어도 아이콘이 보이는 한 리셋하지 않는다.
    eng.tick(_icon_on_noise(tpl["a"]), now=0.6)
    assert _shown(eng.tick(_icon_on_noise(tpl["a"]), now=3.0)) == ["b"]  # a 계속 숨김


def test_set_bar_gating_toggles_behavior():
    """set_bar_gating(True)면 바 없는 영역에서 아이콘이 보여도 리셋한다(게이팅 ON).

    같은 입력이라도 게이팅 OFF면 유지(위 테스트), ON이면 보스 없음으로 보고 리셋 — 대비.
    """
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_bar_gating(True)
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0)  # 밝은 바 인식 → bar_seen=True
    assert _shown(eng.tick(_bar_with_icon(tpl["a"]), now=0.4)) == ["b"]  # a 숨김
    # 바가 사라지고 배경(아이콘 있어도 밴드 없음 → 확실한 바닥) → 유예 후 리셋.
    eng.tick(_icon_on_noise(tpl["a"]), now=0.6)
    assert set(_shown(eng.tick(_icon_on_noise(tpl["a"]), now=2.0))) == {"a", "b"}


def _percent_feeder(monkeypatch, value_holder):
    """de.read_percent_cached를 value_holder['v']로 대체(테스트용 가짜 판독).

    엔진은 (값, 당첨오프셋)을 받으므로 값이 있으면 오프셋 0을 함께 돌려준다.
    """
    def fake(*a, **k):
        v = value_holder["v"]
        return (v, 0 if v is not None else None)

    monkeypatch.setattr(de, "read_percent_cached", fake)


def test_percent_mode_hides_when_percent_read(monkeypatch):
    """3차: 바 영역에서 퍼센트가 읽히면(보스 존재) 걸린 디버프를 숨긴다."""
    v = {"v": 50}
    _percent_feeder(monkeypatch, v)
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"], gate_mode="percent")
    bar = _bar_region()
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0, bar_region=bar)  # 보스 인식 + a 대기
    assert _shown(eng.tick(_bar_with_icon(tpl["a"]), now=0.4, bar_region=bar)) == ["b"]


def test_percent_mode_holds_on_near_death(monkeypatch):
    """3차 빈사 보호: 퍼센트를 못 읽어도(검은 바) 바 영역에 띠가 남으면 리셋하지 않는다."""
    v = {"v": 50}
    _percent_feeder(monkeypatch, v)
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"], gate_mode="percent")
    bright = _bar_region()
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0, bar_region=bright)  # 보스 인식
    assert _shown(eng.tick(_bar_with_icon(tpl["a"]), now=0.4, bar_region=bright)) == ["b"]
    # 빈사: 퍼센트 None + 바 영역은 '평평한 검은 띠'(is_background=False) → 유지.
    v["v"] = None
    black = _black_bar_region()
    eng.tick(_bar_with_icon(tpl["a"]), now=0.7, bar_region=black)
    assert _shown(eng.tick(_bar_with_icon(tpl["a"]), now=3.0, bar_region=black)) == ["b"]


def test_percent_mode_resets_on_confident_floor(monkeypatch):
    """3차: 퍼센트 못 읽고 바 영역도 '확실한 바닥'이면 유예 후 전부 미적용으로 리셋."""
    v = {"v": 50}
    _percent_feeder(monkeypatch, v)
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"], gate_mode="percent")
    bright = _bar_region()
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0, bar_region=bright)
    assert _shown(eng.tick(_bar_with_icon(tpl["a"]), now=0.4, bar_region=bright)) == ["b"]
    # 보스 사라짐: 퍼센트 None + 바 영역이 노이즈(띠 없음=확실한 바닥) → 유예 후 리셋.
    v["v"] = None
    floor = _noise(h=40, w=160)
    eng.tick(_bar_with_icon(tpl["a"]), now=0.7, bar_region=floor)
    res = eng.tick(_bar_with_icon(tpl["a"]), now=2.0, bar_region=floor)
    assert set(_shown(res)) == {"a", "b"}


def test_percent_mode_throttles_read(monkeypatch):
    """3차: read_percent를 매 틱이 아니라 _PERCENT_READ_INTERVAL마다만 호출(성능)."""
    calls = {"n": 0}

    def rp(*a, **k):
        calls["n"] += 1
        return (50, 0)

    monkeypatch.setattr(de, "read_percent_cached", rp)
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"], gate_mode="percent")
    bar = _bar_region()
    for i in range(10):  # 1.0초(0.1초 간격) — 간격 0.6이면 2회 정도만 판독
        eng.tick(_bar_region(), now=i * 0.1, bar_region=bar)
    assert calls["n"] <= 3


def test_percent_mode_no_bar_region_is_safe(monkeypatch):
    """3차인데 바 영역 미지정(None)이면 게이팅 보류 → 1차처럼 항상 표시(리셋 없음)."""
    _percent_feeder(monkeypatch, {"v": None})
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"], gate_mode="percent")
    assert _shown(eng.tick(_noise(h=40, w=160), now=0.0, bar_region=None)) == ["a", "b"]
    assert _shown(eng.tick(_noise(h=40, w=160), now=2.0, bar_region=None)) == ["a", "b"]


def test_warn_gone_suppressed_when_not_foreground():
    """게임이 포그라운드가 아니면 디버프 '사라짐 경고'를 확정·발동하지 않는다."""
    tpl = _bases()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_warn_gone_ids({"a"})
    eng.tick(_bar_with_icon(tpl["a"]), now=0.0)  # a 걸림(포그라운드)
    eng.tick(_bar_region(), now=0.2, foreground=False)  # 떨어짐(비포커스)
    res = eng.tick(_bar_region(), now=3.2, foreground=False)
    assert res.alerts == [] and _gone_ids(res) == []  # 비포커스 → 경고/소리 없음
