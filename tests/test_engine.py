"""BuffEngine 통합 테스트: 실제 상태창 스크린샷으로 캡처→탐지→시간판독→트래커."""

import os

import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.catalog import build_templates, load_catalog
from mabinogi_addon.tracker import BuffEngine

_SHOT = "tests/data/스크린샷 2026-10-06 224732.png"
REGION = (395, 775, 0, 380)  # (y0, y1, x0, x1) 버프 패널 전체


def _region():
    if not os.path.exists(_SHOT):
        pytest.skip("스크린샷 없음")
    img = image_io.imread(_SHOT, cv2.IMREAD_COLOR)
    if img is None or img.shape[0] < 775:
        pytest.skip("해상도 예상과 다름")
    y0, y1, x0, x1 = REGION
    return img[y0:y1, x0:x1]


def _engine(anchor_id=None):
    cat = load_catalog()
    return BuffEngine(
        build_templates(cat),
        [b.id for b in cat],
        anchor_id=anchor_id,
        appear_frames=1,  # 한 프레임에 활성화(테스트)
    )


def test_pipeline_detects_and_reads_time():
    eng = _engine()
    res = eng.tick(_region(), now=0.0)
    assert res.frame_valid
    by_id = {e.buff_id: e for e in res.entries}

    assert by_id["vivace"].remaining == 121  # 2분 1초
    assert by_id["magic_attack"].remaining == 1790  # 29분 50초
    assert by_id["magic_speed"].remaining == 7186  # 1시간 59분 46초
    assert not by_id["vivace"].alerting


def test_internal_clock_advances_between_ticks():
    region = _region()
    eng = _engine()
    eng.tick(region, now=0.0)
    eng.tick(region, now=0.0)  # 같은 화면 다시 → 판독값 121 그대로
    # 10초 경과(화면은 그대로 121이지만 now만 흐름). 정적 화면의 121은 내부 시계보다
    # 위로 '튄' 값이라 위로-튐 가드가 한 프레임만으론 반영하지 않는다(실게임엔 없는
    # 인공 상황 — 실제론 화면도 함께 줄어든다). 따라서 내부 시계가 10초만큼 줄어든다.
    res2 = eng.tick(region, now=10.0)
    after = {e.buff_id: e.remaining for e in res2.entries}
    assert abs(after["vivace"] - 111.0) < 0.5  # 121 → 10초 경과 → ~111


def test_set_order_reorders_entries_live():
    region = _region()
    eng = _engine()
    res = eng.tick(region, now=0.0)
    ids = [e.buff_id for e in res.entries]
    assert len(ids) >= 2
    # 순서를 뒤집어 라이브 반영 → 다음 틱부터 역순
    eng.set_order(list(reversed(ids)))
    res2 = eng.tick(region, now=0.2)
    ids2 = [e.buff_id for e in res2.entries]
    assert ids2 == list(reversed(ids))


def test_set_alert_before_affects_alerting():
    region = _region()
    eng = _engine()
    eng.tick(region, now=0.0)
    # vivace(121초 남음)에 큰 알림 기준을 주면 임박 처리
    eng.set_alert_before({"vivace": 200})
    res = eng.tick(region, now=0.2)
    by_id = {e.buff_id: e for e in res.entries}
    assert by_id["vivace"].alerting is True


def test_anchor_never_seen_does_not_gate():
    # 앵커를 지정해도 한 번도 보인 적 없으면(영역에 앵커가 없는 설정 등) 게이팅하지
    # 않는다 — 안전장치. 이 화면엔 앵커(premium_battle)가 없으므로 정상 프레임으로
    # 취급되어 기존처럼 버프가 활성화돼야 한다.
    eng = _engine(anchor_id="premium_battle")
    res = eng.tick(_region(), now=0.0)
    assert res.frame_valid is True
    assert res.entries  # 버프가 정상적으로 잡힘


def test_anchor_gates_after_first_seen(monkeypatch):
    # 앵커를 한 번이라도 본 뒤에는, 앵커가 사라진 프레임을 '판정 불가'로 동결한다.
    from mabinogi_addon.tracker import engine as engine_mod

    eng = _engine(anchor_id="premium_battle")

    # 1) 앵커가 보이는 프레임을 가짜로 주입 → anchor_seen=True, 정상 프레임
    class _Det:
        def __init__(self, buff_id):
            self.buff_id = buff_id
            self.y = 0

    monkeypatch.setattr(
        engine_mod, "detect_buffs", lambda *a, **k: [_Det("premium_battle")]
    )
    res_seen = eng.tick(_region(), now=0.0)
    assert res_seen.frame_valid is True

    # 2) 이후 앵커가 사라진 프레임 → 판정 불가(동결)
    monkeypatch.setattr(engine_mod, "detect_buffs", lambda *a, **k: [])
    res_gone = eng.tick(_region(), now=1.0)
    assert res_gone.frame_valid is False


def test_second_alert_routes_to_alerts2():
    """2차(막차) 알림은 alerts가 아니라 alerts2로 분리되어 나온다.

    vivace(화면 121초)에 1차 임계 100·2차 90을 주고, 임계 위(ACTIVE)로 등장시킨 뒤
    내부 시계를 흘려 1차→2차를 차례로 교차시킨다. 1차는 alerts, 2차는 alerts2로 담겨야
    앱이 '연장2.mp3'(막차)를 따로 재생할 수 있다."""
    region = _region()
    cat = load_catalog()
    eng = BuffEngine(
        build_templates(cat),
        [b.id for b in cat],
        appear_frames=1,
        alert_before={"vivace": 100},
        alert_before2={"vivace": 90},
    )
    # 등장(rem 121 > 100) → 아직 알림 없음
    res0 = eng.tick(region, now=0.0, foreground=True)
    assert "vivace" not in res0.alerts and "vivace" not in res0.alerts2
    # rem 96 ≤ 100 → 1차만
    res1 = eng.tick(region, now=25.0, foreground=True)
    assert "vivace" in res1.alerts
    assert "vivace" not in res1.alerts2
    # rem 86 ≤ 90 → 2차만(1차는 이미 1회 울려 재발 안 함)
    res2 = eng.tick(region, now=35.0, foreground=True)
    assert "vivace" not in res2.alerts
    assert "vivace" in res2.alerts2
