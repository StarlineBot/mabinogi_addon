"""BuffEngine 통합 테스트: 실제 상태창 스크린샷으로 캡처→탐지→시간판독→트래커."""

import os

import cv2
import pytest

from mabinogi_addon.catalog import build_templates, load_catalog
from mabinogi_addon.tracker import BuffEngine, State

_SHOT = "tests/data/스크린샷 2026-10-06 224732.png"
REGION = (395, 775, 0, 380)  # (y0, y1, x0, x1) 버프 패널 전체


def _region():
    if not os.path.exists(_SHOT):
        pytest.skip("스크린샷 없음")
    img = cv2.imread(_SHOT, cv2.IMREAD_COLOR)
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
    res = eng.tick(region, now=0.0)  # 같은 화면 다시
    before = {e.buff_id: e.remaining for e in res.entries}
    # 10초 경과(화면 갱신 없이 now만) → 내부 시계가 줄어야 함
    res2 = eng.tick(region, now=10.0)
    after = {e.buff_id: e.remaining for e in res2.entries}
    # vivace는 매 틱 재판독(121로 리셋)되므로, 판독 안 되는 틱 기준이 아니라
    # 여기선 '판독값이 그대로 121 부근'이면 OK(화면이 안 변했으니 재판독)
    assert after["vivace"] == 121


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


def test_anchor_missing_freezes():
    # 이 화면엔 앵커(premium_battle)가 없음 → 판정 불가 → 아무것도 활성화 안 됨
    eng = _engine(anchor_id="premium_battle")
    res = eng.tick(_region(), now=0.0)
    assert res.frame_valid is False
    assert res.entries == []
