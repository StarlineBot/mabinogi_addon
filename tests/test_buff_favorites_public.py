"""0.33.0 버프 즐겨찾기 읽기 전체 공개(기획서 3.1.1 끝 2026-10-31 결정)와 목록 방식 거짓 종료 알림(status Confirmed) 회귀.

제작자가 아닌 사용자(목록 방식 고정)가 버프 영역에 즐겨찾기 칸을 포함하면 회색(꺼짐) 즐겨찾기가 템플릿과 맞아 '있음'·시간 없음으로
처리되고, 내부 시계가 마지막 판독값에서 줄어 종료 알림이 울렸다(아이콘이 계속 보여 해제도 안 됨). 이제 모두 구분선 위·아래를 함께 읽고,
구분선을 아직 모를 때는 시간을 못 읽는 줄의 알림을 보류하며, 확인한 구분선을 저장해 다음 실행 첫 프레임부터 쓴다.
"""
import numpy as np
import pytest

from mabinogi_addon.detect import detect_buffs
from mabinogi_addon.detect.buff_detector import Detection
from mabinogi_addon.detect.status_panel import anchor_template
from mabinogi_addon.tracker import engine as engine_mod
from mabinogi_addon.tracker.engine import BuffEngine
from test_buff_favorites import LIT, NAMES, TOP, _region, templates  # noqa: F401  (픽스처)


@pytest.mark.parametrize("stamp", sorted(LIT))
def test_confirmed_list_mode_bug_and_public_reading(stamp, templates):
    region = _region(stamp, TOP)  # 즐겨찾기 칸을 포함한 영역(자동 찾기 영역 69장 중 57장이 이런 모양 — 0.26.0 QA)
    off = set(NAMES) - LIT[stamp]
    listed = {d.buff_id for d in detect_buffs(region, templates, (0, 50))}
    assert off & listed, "재현: 목록 방식은 꺼진 즐겨찾기를 '있음'으로 검출(제보와 같은 조건)"
    engine = BuffEngine(templates, list(NAMES), anchor_id="premium_battle", favorites=True)
    for i in range(6):
        result = engine.tick(region, 100.0 + i * 0.05)
    shown = {entry.buff_id for entry in result.entries}
    assert not shown & off  # 꺼진 즐겨찾기는 하나도 '있음'이 아님
    assert shown == LIT[stamp]


def _run(engine, frames, start=0.0, step=0.5):
    alerts, now = [], start
    for region, count in frames:
        for _ in range(count):
            alerts += engine.tick(region, now).alerts
            now += step
    return alerts, now


@pytest.mark.parametrize("favorites, expect_alert", [(False, True), (True, False)])
def test_favorite_turning_off_gives_no_false_end_alert(favorites, expect_alert, templates):
    """213313(푸른 내상 켜짐 27초) → 233749(같은 즐겨찾기 꺼짐)를 이어 보면, 목록 방식은 회색 아이콘을 계속 '있음'으로 봐
    시계가 20초를 지나 종료 알림을 냈다(재현). 즐겨찾기 함께 읽기는 꺼짐 = 없음이라 알림이 없다."""
    engine = BuffEngine(templates, list(NAMES), anchor_id="premium_battle", favorites=favorites,
                        alert_before={name: 20 for name in NAMES})
    alerts, _ = _run(engine, [(_region("213313"), 6), (_region("233749"), 30)])
    assert ("blue" in alerts) is expect_alert


def test_saved_separator_used_from_first_frame_on_dark_map(templates):
    """어두운 맵(190909)에서 구분선 줄을 지워도(선을 못 찾는 경우) 저장해 둔 선으로 첫 프레임부터 나눈다."""
    region = _region("190909").copy()
    probe = BuffEngine(templates, list(NAMES), anchor_id="premium_battle", favorites=True)
    for i in range(6):
        probe.tick(region, i * 0.05)
    separator = probe.favorites.separator
    region[separator - 2:separator + 3] = 0  # 선이 안 보이는 프레임
    engine = BuffEngine(templates, list(NAMES), anchor_id="premium_battle", favorites=True,
                        favorites_separator=separator)
    engine.tick(region, 0.0)
    assert engine.favorites.boundary == separator
    off = set(NAMES) - LIT["190909"]
    split = {d.buff_id for d in engine._split_favorites(region, detect_buffs(region, templates, (0, 50)))}
    assert not split & off


def _scripted(monkeypatch, engine, script):
    """목록 검출·시간 판독을 각본대로(구분선 없는 빈 영역): script = [(검출 여부, 판독값), ...]."""
    steps = iter(script)
    current = {}

    def detect(*_a, **_k):
        current["step"] = next(steps)
        return [Detection("x", 1.0, 40)] if current["step"][0] else []
    monkeypatch.setattr(engine_mod, "detect_buffs", detect)
    monkeypatch.setattr(engine, "_read_row_time", lambda *_a: current["step"][1])


def test_alert_held_for_rows_without_time_until_separator_known(monkeypatch):
    region = np.zeros((300, 300, 3), np.uint8)  # 구분선 없음(어두운 맵 첫 프레임처럼)
    # 시간을 읽던 버프가 회색 즐겨찾기처럼 시간 없이 계속 보이면: 보류(알림 없음)
    held = BuffEngine({"x": anchor_template()}, ["x"], favorites=True, alert_before={"x": 30})
    _scripted(monkeypatch, held, [(True, 40.0)] * 4 + [(True, None)] * 60)
    alerts = [a for i in range(64) for a in held.tick(region, i * 0.5).alerts]
    assert alerts == []
    # 진짜 목록 버프는 임박 구간에서 시간을 읽으므로 그대로 울린다
    real = BuffEngine({"x": anchor_template()}, ["x"], favorites=True, alert_before={"x": 30})
    _scripted(monkeypatch, real, [(True, 40.0 - i * 0.5) for i in range(40)])
    alerts = [a for i in range(40) for a in real.tick(region, i * 0.5).alerts]
    assert alerts == ["x"]


def test_list_buff_wins_over_lookalike_off_favorite():
    """233749: 꺼진 '정화의 고동'이 마나 피어스 템플릿과 0.714로 맞아(줄 기준 0.7) 목록의 진짜 마나 피어스가 빠지던 것(0.33.0 점검)."""
    from mabinogi_addon.catalog import available_catalog, build_templates
    from mabinogi_addon.detect.status_panel import locate_status_region
    from test_buff_favorites import _load
    image = _load("233749")
    x, y, w, h = locate_status_region(image, anchor_template())
    region = np.ascontiguousarray(image[y:y + h, x:x + w])
    catalog = build_templates(available_catalog())
    engine = BuffEngine(catalog, list(catalog), anchor_id="premium_battle", favorites=True)
    for i in range(6):
        result = engine.tick(region, i * 0.05)
    assert "mana_pierce" in {entry.buff_id for entry in result.entries}
    assert "mana_pierce" not in engine.favorites.rows
