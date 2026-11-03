"""0.40.0 버프 시간 판독 — 게임 글꼴 '나눔고딕' 글자 세트(전장의 서곡 '10초 전 알림' 문의).

원인(QA 확정): 시간 글자 세트가 '마비노기옛체'용뿐이라, 게임 옵션 글꼴이 나눔고딕이면 시간을 전혀 못 읽었다.
'1'·'0'만 겨우 맞는 10초쯤에서 첫 판독 → 바로 1차 알림. 나눔고딕 세트(time/nanum)로 화면 값 그대로 읽는다.
2560(개발자 PC)·1080(문의자) 모두 글자 높이 9px로 같고, 1080은 획이 조금 굵게 뭉친 모양이 있어 변형으로 함께 둔다.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.catalog import build_templates, load_catalog
from mabinogi_addon.detect import time_reader as tr
from mabinogi_addon.detect.status_panel import anchor_template, locate_status_region
from mabinogi_addon.tracker import BuffEngine

D = "tests/data/2026-11-03_나눔고딕_"
BOX_1080 = (1628, 262, 290, 700)  # 문의자 화면 오른쪽 상태 목록
EXPECTED = {
    D + "2560_234053.png": {"vivace": 118, "han_adrenaline": 174, "sharp": 293},  # 1분 58초 · 2분 54초 · 4분 53초
    D + "2560_234056.png": {"vivace": 115, "han_adrenaline": 172, "sharp": 291},
    D + "2560_234058.png": {"vivace": 113, "han_adrenaline": 169, "sharp": 288},
    D + "2560_234114.png": {"vivace": 97, "han_adrenaline": 154, "sharp": 273},
    D + "2560_234129.png": {"vivace": 82, "han_adrenaline": 139, "sharp": 258},
    D + "2560_234409.png": {"han_adrenaline": 177, "sharp": 296},
    D + "2560_234413.png": {"han_adrenaline": 172, "sharp": 290},  # 4분 50초('0')
    D + "2560_234539_마법공격력1시간59분56초.png": {"han_adrenaline": 86, "sharp": 205,
                                                   "magic_attack": 7196, "magic_speed": 7196},
    D + "1080_전장의서곡55초빨강.png": {"overture_of_the_battlefield": 55, "march": 55, "vivace": 55},
    D + "1080_행진곡59초빨강_밝은배경.png": {"overture_of_the_battlefield": 59, "march": 59, "vivace": 59,
                                         "han_adrenaline": 137, "enduring_will": 164,
                                         "music_boost": 1763},  # 29분 23초
    D + "1080_시간없는목록.png": {},  # 시간이 하나도 없는 목록 — 엉뚱한 값을 읽지 않는다
}


def _region(path):
    frame = image_io.imread(path, cv2.IMREAD_COLOR)
    box = BOX_1080 if "_1080_" in path else locate_status_region(frame, anchor_template())
    x, y, w, h = box
    return frame[y:y + h, x:x + w]


def _engine():
    cat = load_catalog()
    return BuffEngine(build_templates(cat), [b.id for b in cat], appear_frames=1)


def _entries(engine, region, ticks=4, start=0.0, step=0.001):
    result = None
    for i in range(ticks):
        result = engine.tick(region, now=start + i * step)
    return {e.buff_id: e.remaining for e in result.entries if e.remaining is not None}


# 0.40.0 배포 검증 #179 명세 변경: 급소 관통(penet)과 공격력 증가(melee_attack)는 같은 아이콘이라 실행 환경마다 어느 줄
# (급소 관통 2분 43초=163 / 공격력 증가 29분 23초=1763)에 붙는지 바뀐다 — 두 버프는 화면 값 둘 중 하나면 맞는 것으로 본다.
SAME_ICON = {D + "1080_행진곡59초빨강_밝은배경.png": {"penet": {163, 1763}, "melee_attack": {163, 1763}}}


@pytest.mark.parametrize("path", list(EXPECTED), ids=lambda p: p.rsplit("_나눔고딕_", 1)[-1][:-4])
def test_nanum_times_read_as_shown(path):
    engine = _engine()
    got = _entries(engine, _region(path))
    for bid, allowed in SAME_ICON.get(path, {}).items():
        if bid in got:
            assert round(got.pop(bid)) in allowed, bid
    assert got == pytest.approx(EXPECTED[path], abs=0.5)
    assert not engine.time_unreadable


def test_nanum_set_is_complete_and_same_glyph_size_at_2560_and_1080():
    assert "nanum" in tr.set_names()
    labels = {tr._label(k) for k in tr._SETS["nanum"]}
    assert labels == {*"0123456789", "cho", "bun", "hour", "day"}
    # 숫자 템플릿 = 9px 글자 + 위아래 여백 1px — 2560·1080 변형 모두 같은 높이
    assert {img.shape[0] for k, img in tr._SETS["nanum"].items() if tr._label(k).isdigit()} == {11}
    assert tr.GLYPH_THRESHOLD == 0.7  # 기준값은 낮추지 않는다


def test_unreadable_time_glyphs_show_notice_and_log(monkeypatch, caplog):
    """세트가 없으면(예전 동작) 시간 칸에 글자가 있는데 못 읽는 줄이 이어진다 → 안내 상태 + app.log 한 줄. 다시 읽히면 풀린다."""
    caplog.set_level(logging.INFO, logger="mabinogi_addon.tracker.engine")
    region = _region(D + "2560_234053.png")
    nanum = tr._SETS["nanum"]
    monkeypatch.delitem(tr._SETS, "nanum")
    engine = _engine()
    _entries(engine, region, ticks=30, step=1.1)  # 시간 판독은 1초 간격
    assert engine.time_unreadable
    assert sum("읽지 못하고 있어요" in r.getMessage() for r in caplog.records) == 1  # 한 번만
    monkeypatch.setitem(tr._SETS, "nanum", nanum)
    got = _entries(engine, region, ticks=30, start=40, step=1.1)
    assert not engine.time_unreadable and set(got) >= {"vivace", "sharp"}
    assert any("다시 읽고" in r.getMessage() for r in caplog.records)


def test_buffs_without_time_never_count_as_unreadable():
    engine = _engine()
    _entries(engine, _region(D + "1080_시간없는목록.png"), ticks=40, step=1.1)
    assert not engine.time_unreadable and engine._unread_streak == 0


def test_buff_tab_status_shows_the_notice():
    from mabinogi_addon.ui import main_window as mw
    fake = SimpleNamespace(
        buff_controller=SimpleNamespace(item_count=3), _engine=SimpleNamespace(
            anchor_seen=True, favorites=None, time_unreadable=True),
        _watcher=SimpleNamespace(is_game_active=lambda: True),
        _STATUS_WARN="warn", _STATUS_OK="ok", _STATUS_MUTED="muted", _WAITING_TEXT="", _INACTIVE_TEXT="")
    original = mw.config.load_capture_region
    mw.config.load_capture_region = lambda *a, **k: {"x": 0, "y": 0, "w": 1, "h": 1}
    try:
        text, color, icon = mw.MainWindow._buff_status(fake)
        assert text == "시간 글자를 읽지 못하고 있어요 (게임 글꼴 설정을 확인해 주세요)" and color == "warn"
        fake._engine.time_unreadable = False
        assert mw.MainWindow._buff_status(fake)[0] == "추적 중 — 버프 3개 표시"
    finally:
        mw.config.load_capture_region = original


def _only_untimed_rows(path):
    """QA 재현: 시간 있는 줄의 시간 칸을 지워 '시간 없는 버프 줄만 남은' 화면(마을 등)을 만든다."""
    frame = image_io.imread(path, cv2.IMREAD_COLOR)
    x, y, w, h = locate_status_region(frame, anchor_template())
    region = frame[y:y + h, x:x + w].copy()
    engine = _engine()
    timed = []
    original = engine._read_row_time_raw

    def record(reg, icon_y):
        value = original(reg, icon_y)
        if value is not None:
            timed.append(icon_y)
        return value
    engine._read_row_time_raw = record
    _entries(engine, region, ticks=3)
    assert timed  # 지울 시간 줄이 있었다
    for icon_y in timed:
        top = max(0, icon_y - engine._row_pad_top)
        region[top:icon_y + engine._row_height, engine._time_x0:] = 0
    return region


@pytest.mark.parametrize("name", ["스크린샷 2026-10-16 211332.png",  # 마비노기옛체
                                  "스크린샷 2026-11-03 234912.png", "스크린샷 2026-11-03 234931.png"])  # 나눔고딕
def test_untimed_rows_on_bright_floor_never_raise_the_notice(name, caplog):
    """0.40.0 QA(Confirmed): 반투명 상태창 뒤 밝은 바닥을 글자로 세어, 시간 없는 줄(마나실드·멤버십 '…')만 남으면
    6초 만에 '시간 글자를 읽지 못하고 있어요'가 떴다. 이제 시간 글자처럼 생긴 잉크만 센다."""
    caplog.set_level(logging.INFO, logger="mabinogi_addon.tracker.engine")
    region = _only_untimed_rows("tests/data/" + name)
    engine = _engine()
    _entries(engine, region, ticks=60, step=1.1)
    assert not engine.time_unreadable and engine._unread_streak == 0
    assert not any("읽지 못하고 있어요" in r.getMessage() for r in caplog.records)


def test_time_text_shape_check():
    from mabinogi_addon.tracker.engine import looks_like_time_text
    import numpy as np
    blank = np.zeros((28, 154), np.uint8)
    assert not looks_like_time_text(blank)
    floor = blank.copy()
    floor[:, 140:] = 255  # 오른쪽 끝 밝은 바닥(줄 높이 전체)
    assert not looks_like_time_text(floor)
    text = blank.copy()
    for x0 in (100, 108, 116):  # 9px 높이 글자 3개(숫자·숫자·단위 자리)
        text[8:17, x0:x0 + 5] = 255
        text[10:15, x0 + 1:x0 + 4] = 0
    assert looks_like_time_text(text)
    assert looks_like_time_text(np.maximum(text, floor))  # 밝은 바닥이 옆에 있어도 글자 줄은 알아본다
