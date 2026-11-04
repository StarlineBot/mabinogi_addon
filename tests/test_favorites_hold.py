"""0.40.0 즐겨찾기 버프가 종료 직전 연장 후 사라지던 문제(사용자 실게임 재현 + app.log로 확정).

- 종료 직전 깜빡이는 프레임에 즐겨찾기 줄을 다시 맞추면 그 줄이 빠지고, 남은 줄이 멀쩡하면 다시 넣지 않았다(실측 16초).
  그 사이 연장하면 남은 시간이 3초→374초로 뛰어 '시계와 맞으면 살아 있음' 대체 판정도 실패 → 종료.
- 다시 맞춤 결과가 한 프레임만 비어도 기억 줄 전체가 지워졌다("등록 버프 없음" 반복).
- 예전 자동 찾기 영역은 맨 위 즐겨찾기 줄이 영역 위 끝에 걸려 아이콘이 잘렸다.
자료: 2560 '스크린샷 2026-11-04 014744'(비바체 즐겨찾기 6분 14초), 4K mabinogi_2026_11_04_010804(즐겨찾기 7줄).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.catalog import build_templates, load_catalog
from mabinogi_addon.detect.favorites import widen_to_favorites
from mabinogi_addon.detect.status_panel import anchor_template, locate_status_region
from mabinogi_addon.tracker import BuffEngine

SHOT_2560 = "tests/data/스크린샷 2026-11-04 014744.png"
SHOT_4K = "tests/data/mabinogi_2026_11_04_010804.png"
STEP = 0.2  # 버프 판독 틱 간격(초)


def _region(path):
    frame = image_io.imread(path, cv2.IMREAD_COLOR)
    x, y, w, h = widen_to_favorites(frame, locate_status_region(frame, anchor_template()))
    return frame[y:y + h, x:x + w].copy()


def _engine():
    cat = load_catalog()
    return BuffEngine(build_templates(cat), [b.id for b in cat], appear_frames=1, favorites=True)


@pytest.fixture
def vivace():
    """014744: 비바체 즐겨찾기 줄. 남은 시간 화면값은 screen[0]으로 바꿔 가며(종료 직전 → 연장) 읽힌다.
    처음부터 가짜 화면값을 읽게 한다(자료의 실제 값 6분 14초를 먼저 읽으면 내부 시계가 이미 374초라 '연장'이 안 생긴다)."""
    region = _region(SHOT_2560)
    probe = _engine()
    for i in range(6):
        probe.tick(region, now=i * STEP)
    row = probe.favorites.rows["vivace"]
    engine = _engine()
    screen = [13.0]
    original = engine._read_row_time

    def read(reg, icon_y):
        return screen[0] if abs(icon_y - row.y) <= 2 else original(reg, icon_y)
    engine._read_row_time = read
    for i in range(6):
        screen[0] = 13.0 - i * STEP
        engine.tick(region, now=i * STEP)
    assert engine._machines["vivace"].remaining(1.0) == pytest.approx(12.0, abs=0.5)
    blink = region.copy()
    blink[row.y:row.y + row.size, row.x:row.x + row.size] = 20  # 종료 직전 깜빡임: 아이콘이 잠깐 안 보임
    return SimpleNamespace(engine=engine, region=region, blink=blink, row=row, screen=screen)


def _run(v, start, end, *, frame=None, screen=None):
    entry = None
    t = start
    while t < end - 1e-9:
        if screen is not None:
            v.screen[0] = screen(t)
        result = v.engine.tick(frame if frame is not None else v.region, now=t)
        entry = next((e for e in result.entries if e.buff_id == "vivace"), None)
        assert entry is not None, f"{t:.1f}초에 비바체가 오버레이에서 사라짐"
        t += STEP
    return entry


def test_blink_then_extension_10s_later_keeps_the_buff(vivace, caplog):
    """① 종료 직전 한 줄이 깜빡임 → ② 10초 뒤 연장(남은 시간 위로 크게 뜀) → 오버레이에 계속 표시되고 연장 값으로 이어진다."""
    caplog.set_level(logging.INFO, logger="mabinogi_addon.favorites")
    v = vivace
    _run(v, 1.2, 2.0, screen=lambda t: 13.0 - t)
    _run(v, 2.0, 3.2, frame=v.blink, screen=lambda t: 13.0 - t)  # 깜빡임 1.2초(6프레임) — 이때 다시 맞춤이 일어남
    assert "vivace" in v.engine.favorites.rows  # 못 찾은 기억 줄을 바로 지우지 않음
    _run(v, 3.2, 12.0, screen=lambda t: 13.0 - t)
    entry = _run(v, 12.0, 16.0, screen=lambda t: 374.0 - (t - 12.0))  # 종료 1초 전에 연장(6분 14초)
    assert entry.remaining == pytest.approx(370.0, abs=1.5)
    assert not entry.alerting  # 연장 = 점멸 해제


def test_row_dropped_during_blink_comes_back_before_extension(vivace):
    """깜빡임이 유지 시간(약 2초)보다 길어 줄이 빠져도, 아이콘이 돌아오면 몇 프레임 안에 다시 채운다(예전엔 16초 동안 안 채움)."""
    v = vivace
    _run(v, 1.2, 2.0, screen=lambda t: 30.0 - t)
    _run(v, 2.0, 5.0, frame=v.blink, screen=lambda t: 30.0 - t)  # 3초 깜빡임 — 대체 판정(시계와 맞음)으로 표시는 유지
    assert "vivace" not in v.engine.favorites.rows  # 유지 시간을 넘으면 뺀다
    _run(v, 5.0, 7.0, screen=lambda t: 30.0 - t)
    assert "vivace" in v.engine.favorites.rows  # 아이콘이 돌아오면 다시 채움
    entry = _run(v, 7.0, 10.0, screen=lambda t: 374.0 - (t - 7.0))
    assert entry.remaining == pytest.approx(371.0, abs=1.5)


def test_extension_on_same_row_is_kept_even_when_row_is_not_remembered(vivace):
    """③-보강: 기억 줄에서 빠진 상태라도 같은 자리에 그 아이콘이 그대로 있고 시간이 위로 크게 뛰면 종료가 아니라 연장."""
    v = vivace
    _run(v, 1.2, 2.0, screen=lambda t: 13.0 - t)
    v.engine.favorites.rows.pop("vivace")  # 기억에서 빠짐(예전 다시 맞춤 버그 상황)
    v.engine.favorites.SCAN_EVERY = 10 ** 6  # 다시 채우기를 꺼서 엔진의 '같은 줄 아이콘 + 시간 위로 뜀 = 연장'만 본다
    entry = _run(v, 2.0, 8.0, screen=lambda t: 374.0 - (t - 2.0))  # '잠깐 안 보임' 유예보다 길게
    assert "vivace" not in v.engine.favorites.rows
    assert entry.remaining == pytest.approx(368.0, abs=1.5)


@pytest.mark.parametrize("path", [SHOT_2560, SHOT_4K])
def test_one_fully_covered_frame_keeps_remembered_rows(path, caplog):
    """③ 한 프레임 전체가 가려져(다시 맞춤 결과가 빔) 기억 줄 전체가 지워지던 것 — 이제 유지된다."""
    caplog.set_level(logging.INFO, logger="mabinogi_addon.favorites")
    region = _region(path)
    engine = _engine()
    for i in range(6):
        engine.tick(region, now=i * STEP)
    before = dict(engine.favorites.rows)
    assert before
    covered = region.copy()
    covered[:engine.favorites.separator - 2] = 0  # 즐겨찾기 칸 전체가 까맣게(맵 이동·이펙트)
    engine.tick(covered, now=6 * STEP)
    assert set(engine.favorites.rows) == set(before)
    for i in range(7, 14):
        engine.tick(region, now=i * STEP)
    assert {b: r.y for b, r in engine.favorites.rows.items()} == {b: r.y for b, r in before.items()}
    assert not any("등록 버프 없음" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("cut", [0, 4, 8, 12])
def test_top_row_cut_by_region_warns_and_shows_notice(cut, caplog):
    """④ 예전 영역: 맨 위 즐겨찾기 줄이 영역 위 끝에 걸림 → app.log 경고 + 버프 탭 '자동 찾기 다시' 안내."""
    caplog.set_level(logging.INFO, logger="mabinogi_addon.favorites")
    frame = image_io.imread(SHOT_4K, cv2.IMREAD_COLOR)
    x, y, w, h = 3546, 276, 294, 1884  # 4K 버프 영역(즐겨찾기 맨 위 줄 = 영역 y 496)
    engine = _engine()
    for i in range(8):
        engine.tick(frame[y + 496 + cut:y + h, x:x + w], now=i * STEP)
    assert engine.favorites.top_cut
    assert sum("영역 위 끝에 걸려" in r.getMessage() for r in caplog.records) == 1  # 한 번만
    # 넉넉한 영역(원래 자동 찾기)은 경고 없음
    ok = _engine()
    for i in range(8):
        ok.tick(frame[y:y + h, x:x + w], now=i * STEP)
    assert not ok.favorites.top_cut
    # 버프 탭 상태 줄
    from mabinogi_addon.ui import main_window as mw
    fake = SimpleNamespace(
        buff_controller=SimpleNamespace(item_count=3), _engine=engine,
        _watcher=SimpleNamespace(is_game_active=lambda: True),
        _STATUS_WARN="warn", _STATUS_OK="ok", _STATUS_MUTED="muted", _WAITING_TEXT="", _INACTIVE_TEXT="")
    original = mw.config.load_capture_region
    mw.config.load_capture_region = lambda *a, **k: {"x": 0, "y": 0, "w": 1, "h": 1}
    try:
        text, color, icon = mw.MainWindow._buff_status(fake)
    finally:
        mw.config.load_capture_region = original
    assert text == "즐겨찾기 맨 위 줄이 잘려요 · 자동 찾기를 다시 해 주세요"
    assert (color, icon) == ("warn", "region")


def test_similar_icon_moving_up_does_not_keep_the_ended_buff_as_ghost():
    """0.40.0 QA(d6bc4d6): 목록에서 버프가 끝나 아랫줄이 올라올 때, 올라온 버프 아이콘이 비슷하면(dark_erg↔flame_of_resurrection 0.737)
    '같은 줄 아이콘 그대로 + 시간 위로 뜀 = 연장'으로 보아 끝난 버프가 그 시간을 받아 유령으로 남았다. 그 줄에 다른 버프가 잡히면 연장이 아니다."""
    frame = image_io.imread("tests/data/2026-11-03_나눔고딕_1080_행진곡59초빨강_밝은배경.png", cv2.IMREAD_COLOR)
    region = frame[262:962, 1628:1918].copy()  # 1080 상태 목록(즐겨찾기 읽기 끔 = 전체가 목록)
    cat = load_catalog()
    templates = build_templates(cat)
    engine = BuffEngine(templates, [b.id for b in cat], appear_frames=1)
    pad, height = engine._row_pad_top, engine._row_height
    before = region.copy()
    before[449:465, 4:20] = templates["dark_erg"]  # dark_erg 줄(2분 44초)
    after = region.copy()
    after[449 - pad:449 + height, 20:] = region[545 - pad:545 + height, 20:]  # 아랫줄(29분 23초)이 올라옴
    after[449:465, 4:20] = templates["flame_of_resurrection"]
    t = 0.0
    while t < 2.0:
        result = engine.tick(before, now=t)
        t += STEP
    dark = next(e for e in result.entries if e.buff_id == "dark_erg")
    assert dark.remaining == pytest.approx(164, abs=1.5)
    while t < 12.0:  # dark_erg가 끝나 그 줄이 지워지고 10초
        result = engine.tick(after, now=t)
        t += STEP
    ids = {e.buff_id for e in result.entries}
    assert "dark_erg" not in ids and "flame_of_resurrection" in ids


def test_unknown_favorites_do_not_keep_remapping(monkeypatch):
    """0.40.0 QA(d6bc4d6): 앱이 모르는 버프가 즐겨찾기에 섞이면 '기억 줄 < 칸 수'가 늘 참이라 5프레임마다 map_rows(9~13ms)가 돌았다.
    다시 채움은 유지 중이거나 유지 시간을 넘겨 빠진 줄이 있을 때만 — 014744(기억 2줄 / 칸 8줄)를 100틱 돌려도 첫 맞춤 뒤로 늘지 않는다."""
    from mabinogi_addon.detect import favorites as fav
    calls = []
    original = fav.map_rows
    monkeypatch.setattr(fav, "map_rows", lambda *a, **k: calls.append(1) or original(*a, **k))
    region = _region(SHOT_2560)
    engine = _engine()
    for i in range(10):
        engine.tick(region, now=i * STEP)
    reader = engine.favorites
    assert reader.row_count is not None and len(reader.rows) < reader.row_count  # 모르는 즐겨찾기가 섞인 화면
    first = len(calls)
    for i in range(10, 110):
        engine.tick(region, now=i * STEP)
    assert len(calls) == first


@pytest.mark.parametrize("period", [2, 6, 12])
def test_long_blinking_row_does_not_keep_remapping(monkeypatch, caplog, period):
    """0.42.0(사용자 app.log 0.40.2 21:29~21:31): 한 줄이 2분 동안 깜빡이면 빠졌다 다시 찾기를 되풀이하며 포기 시계가 매번 처음부터라
    '다시 맞춤'이 계속 반복됐다(GIVE_UP_FRAMES 무력화). 같은 자리로 두 번 돌아온 줄은 붙잡아 두고 그 줄 때문에 다시 맞추지 않는다.
    예전 코드: 12프레임 주기 → 다시 맞춤 로그 50줄·map_rows 288회, 2프레임 주기 → map_rows 361회(2분)."""
    from mabinogi_addon.detect import favorites as fav
    caplog.set_level(logging.INFO, logger="mabinogi_addon.favorites")
    calls = []
    original = fav.map_rows
    monkeypatch.setattr(fav, "map_rows", lambda *a, **k: calls.append(1) or original(*a, **k))
    region = _region(SHOT_2560)
    engine = _engine()
    for i in range(6):
        engine.tick(region, now=i * STEP)
    row = engine.favorites.rows["vivace"]
    blink = region.copy()
    blink[row.y:row.y + row.size, row.x:row.x + row.size] = 20
    for i in range(6, 606):  # 2분
        engine.tick(blink if (i // period) % 2 == 0 else region, now=i * STEP)
    remaps = [r for r in caplog.records if "다시 맞춤" in r.getMessage()]
    assert len(remaps) <= 6 and len(calls) <= 30
    assert engine.favorites.rows["vivace"].y == row.y and "mana_pierce" in engine.favorites.rows
    assert any("붙잡아 둠" in r.getMessage() for r in caplog.records)
