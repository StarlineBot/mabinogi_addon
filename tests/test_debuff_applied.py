"""디버프 오버레이 '걸린 것 + 시간' 보기(docs/debuff-applied-overlay-spec.md, 제작자 먼저, 사용자 결정 11-08).

- 시간 판독: 아이콘 바로 아래 칸의 게임 시간 글자(7px·9px 두 글꼴, 0~9·M) — tests/data 보스 화면 디버프 줄(몽타주로 화면과 같음 확인).
- M 없는 숫자는 줄어드는 것을 봐야 초(게임 글꼴에 따라 분도 M 없이 '4' — 10-30 4K 6장, 11-09 4K는 '4M') — 틀린 숫자 금지.
- 방식 전환: 같은 프레임으로 '안 걸린 것'/'걸린 것' 결과가 서로 보완. 떨어짐: 경고 켠 것은 3초 확정 → 경고 5초 → 빠짐, 끈 것은 바로 빠짐.
"""
import os

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.detect.debuff_time import display_text, read_times

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _region(name):
    from mabinogi_addon.detect.boss_bar import locate_boss_bar, make_validator
    from mabinogi_addon.ui.autofind_v2_controller import debuff_from_boss
    f = image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)
    x, y, w, h = debuff_from_boss(locate_boss_bar(f, make_validator()))
    return f[y:y + h, x:x + w].copy()


# 화면 디버프 줄(아이콘 x → 아이콘 아래 글자, None = 글자 없음). 아이콘은 16px, 18px 간격.
ROWS = [
    ("2026-10-30_windowed_wireweb_1.png", 17, {7: "43", 25: "3M", 61: "6M", 97: "6M", 133: None, 151: "1M", 169: "13"}),
    ("스크린샷 2026-10-18 001801.png", 17, {7: "3M", 25: "4M", 43: "4M", 61: "9M", 151: "9M", 169: None, 223: "4M", 259: "2M"}),
    ("스크린샷 2026-10-09 200614.png", 17, {7: "4M", 25: "4M", 43: "9M", 61: "4M", 79: "9M", 115: "4M", 133: "1M"}),  # 9px 글꼴, 붙은 글자
    ("스크린샷 2026-11-03 234812.png", 17, {7: "4M", 25: "4M", 79: "9M", 97: "9M", 169: "4M"}),
    ("스크린샷 2026-10-16 213733.png", 17, {7: "40", 25: "40", 43: "40", 61: "6", 79: "40", 97: "44"}),  # 초
    ("스크린샷 2026-10-16 210805.png", 17, {43: "0"}),
    ("스크린샷 2026-10-18 001541.png", 17, {7: "32", 25: "4M", 43: "3M", 133: "8M", 187: "7M", 277: "10", 295: "2M"}),
    ("mabinogi_2026_11_09_000141.png", 17, {7: "4M", 25: "4M", 43: None}),  # 4K — 픽셀 글꼴이면 4K도 'M'(사용자 11-09, QA e98aac6)
    ("스크린샷 2026-10-25 150822.png", 17, {7: "5M", 25: "5M", 43: "3M", 61: "8M", 97: "5M", 241: "38", 259: "3M", 277: "2M"}),
]


@pytest.mark.parametrize("name,y,expected", ROWS, ids=[r[0] for r in ROWS])
def test_time_under_each_icon(name, y, expected):
    region = _region(name)
    got = read_times(region, {x: (x, y, 16, 16) for x in expected})
    assert got == expected


def test_4m4m3m_touching_text_is_split_by_icon():
    region = _region("스크린샷 2026-10-09 193901.png")  # '4M4M3M8M3M…' 글자 사이가 붙음
    got = read_times(region, {x: (x, 17, 16, 16) for x in (7, 25, 187)})
    assert got == {7: "4M", 25: "4M", 187: "8M"}


def test_bright_floor_or_effect_gives_nothing():
    region = _region("스크린샷 2026-10-18 001801.png")
    rng = np.random.default_rng(1)
    region[34:46, :] = rng.integers(200, 256, size=region[34:46, :].shape, dtype=np.uint8)  # 밝은 바닥·이펙트 위 글자
    got = read_times(region, {x: (x, 17, 16, 16) for x in (7, 25, 43, 61)})
    assert got == {7: None, 25: None, 43: None, 61: None}  # 틀린 숫자 대신 비움


def test_4k_digits_without_m_are_never_shown_as_seconds_without_countdown():
    from mabinogi_addon.tracker.debuff_engine import DebuffEngine
    eng = DebuffEngine({}, [])
    # 매끈한 큰 글꼴(10-30 4K 6장)은 분도 M 없이 '4'·'9' — 같은 숫자가 계속이면 초가 아님 → 숫자 없음
    assert all(eng._time_label("a", "4", t) == (None, False) for t in (0.0, 0.5, 1.0, 2.0, 3.0, 6.0))
    # 진짜 초: 1초마다 줄어든다 → 줄어드는 걸 본 뒤부터 '42s' 빨강, 0도 '0s'
    assert eng._time_label("b", "43", 0.0) == (None, False)
    assert eng._time_label("b", "42", 1.0) == ("42s", True)
    assert eng._time_label("b", "41", 2.0) == ("41s", True)
    assert eng._time_label("c", "1", 0.0) == (None, False) and eng._time_label("c", "0", 1.0) == ("0s", True)
    # 'NM'은 바로
    assert eng._time_label("d", "4M", 0.0) == ("4m", False)
    assert display_text("9M") == ("9m", False) and display_text("43") == ("43s", True) and display_text(None) is None


def test_overlay_spec_uses_game_time_text():
    from mabinogi_addon.tracker.engine import OverlayEntry
    from mabinogi_addon.ui.overlay import overlay_spec
    entries = [OverlayEntry("a", None, False, time_text="4m"), OverlayEntry("b", None, False, time_text="43s", time_warn=True),
               OverlayEntry("c", None, False), OverlayEntry("d", None, False, gone=True)]
    assert overlay_spec(entries, {"a": False, "b": False, "c": False, "d": False}) == [
        ("a", "4m", False, False), ("b", "43s", True, False), ("c", None, False, False), ("d", None, False, True)]


# ---- 엔진: 방식 전환·떨어짐 -------------------------------------------------------------------------------------
def _engine(order, warn=()):
    from mabinogi_addon.catalog import available_debuff_catalog, build_templates
    from mabinogi_addon.tracker.debuff_engine import DebuffEngine
    cat = {b.id: b for b in available_debuff_catalog()}
    eng = DebuffEngine(build_templates([cat[b] for b in order]), order)
    eng.set_warn_gone_ids(set(warn))
    return eng


ORDER = ["물리 방어력 보호 감소", "방해 카드", "받는 대미지 증가", "모모", "와이어웹", "프라가라흐(물리)", "케라"]  # 사용자 순서
APPLIED = ["물리 방어력 보호 감소", "받는 대미지 증가", "모모", "프라가라흐(물리)", "케라"]  # 001801 화면에 걸린 것


def test_modes_complement_each_other_in_user_order():
    region = _region("스크린샷 2026-10-18 001801.png")
    result = {}
    for mode in ("missing", "applied"):
        eng = _engine(ORDER)
        eng.set_display_mode(mode)
        for t in (0.0, 0.2, 0.4, 0.6):
            res = eng.tick(region, t)
        result[mode] = [e.buff_id for e in res.entries]
    assert not set(result["missing"]) & set(result["applied"])
    assert sorted(result["missing"] + result["applied"]) == sorted(ORDER)  # 합치면 추적 대상 전체
    for ids in result.values():
        assert ids == [b for b in ORDER if b in ids]  # 사용자 순서
    assert result["applied"] == APPLIED and result["missing"] == ["방해 카드", "와이어웹"]


def test_applied_mode_shows_game_time_under_icons():
    region = _region("스크린샷 2026-10-18 001801.png")
    eng = _engine(ORDER)
    eng.set_display_mode("applied")
    for t in (0.0, 0.2, 0.4):
        res = eng.tick(region, t)
    assert [(e.buff_id, e.time_text, e.time_warn) for e in res.entries] == [  # 화면: 3M · 4M · 4M · (없음) · 9M
        ("물리 방어력 보호 감소", "3m", False), ("받는 대미지 증가", "4m", False), ("모모", "4m", False),
        ("프라가라흐(물리)", None, False), ("케라", "9m", False)]  # 프라가라흐는 시간 없음 → 아이콘만


def _without_icons(region):
    out = region.copy()
    out[12:36, :] = out[0:1, :]  # 아이콘 줄을 맨 위 줄 배경으로 덮음(보스바는 그대로 보임)
    return out


def test_falloff_warning_then_removed_and_warn_off_removed_at_once():
    region = _region("스크린샷 2026-10-18 001801.png")
    bare = _without_icons(region)
    eng = _engine(ORDER, warn={"모모"})
    eng.set_display_mode("applied")
    t = 0.0
    for t in (0.0, 0.2, 0.4, 0.6):
        eng.tick(region, t)

    def shown(now):
        res = eng.tick(bare, now)
        return {e.buff_id: e.gone for e in res.entries}, res.alerts
    s, _ = shown(1.0)
    assert s == {b: False for b in APPLIED}  # 깜빡임 방지(0.4초)까지는 그대로
    s, _ = shown(1.5)
    assert s == {"모모": False}  # 경고 켠 '모모'는 떨어짐 확정(3초)까지 그대로, 끈 것은 바로 빠짐
    s, _ = shown(2.0)
    assert s == {"모모": False}
    s, alerts = shown(4.1)
    assert s == {"모모": True} and alerts == ["모모"]  # 확정 → 빨간 테두리+X
    s, _ = shown(8.0)
    assert s == {"모모": True}
    s, _ = shown(9.2)
    assert s == {}  # 경고 5초 뒤 빠짐


# ---- 탭: 제작자만 '표시' 선택 ----------------------------------------------------------------------------------
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("creator", [False, True])
def test_display_choice_for_everyone(app, monkeypatch, creator):
    """0.45.0(사용자 결정 11-10): '표시 [안 걸린 것 | 걸린 것 + 시간]'은 모든 사용자, 기본 '안 걸린 것'."""
    from mabinogi_addon import config, feature_access
    from mabinogi_addon.ui.debuff_tab import DebuffTab
    monkeypatch.setattr(feature_access, "is_creator", lambda: creator)
    tab = DebuffTab()
    try:
        assert tab.display_segments is not None and tab.display_segments.buttons["missing"].isChecked()  # 기본 안 걸린 것
        assert tab.effective_display_mode() == "missing"
        assert tab.header.description.text() == "보스에게 아직 걸리지 않은 디버프를 보여줘요."
        seen = []
        tab.display_mode_changed.connect(seen.append)
        tab.display_segments.buttons["applied"].click()
        assert seen == ["applied"] and config.load_debuff_display_mode() == "applied"
        assert tab.effective_display_mode() == "applied"
        assert tab.header.description.text() == "보스에게 걸린 디버프와 남은 시간을 보여줘요."
        assert "걸린 디버프와 남은 시간" in tab.region_section.unset_label.text()
        tab.display_segments.buttons["missing"].click()
        assert tab.header.description.text() == "보스에게 아직 걸리지 않은 디버프를 보여줘요."
    finally:
        tab.deleteLater()


def test_main_window_passes_display_mode_to_engine(monkeypatch):
    """탭에서 방식을 바꾸면 엔진에 바로(재시작 없이) — 제작자가 아니면 탭이 늘 '안 걸린 것'을 준다."""
    from types import SimpleNamespace

    from mabinogi_addon.tracker.debuff_engine import DebuffEngine
    from mabinogi_addon.ui.main_window import MainWindow
    eng = DebuffEngine({}, [])
    me = SimpleNamespace(_debuff_engine=eng, debuff_tab=SimpleNamespace(effective_display_mode=lambda: "applied"))
    MainWindow._on_debuff_display_mode(me, "applied")
    assert eng.display_mode == "applied"
    me.debuff_tab.effective_display_mode = lambda: "missing"
    MainWindow._on_debuff_display_mode(me, "applied")
    assert eng.display_mode == "missing"
    MainWindow._on_debuff_display_mode(SimpleNamespace(_debuff_engine=None, debuff_tab=me.debuff_tab), "applied")  # 추적 안 하면 무시


def test_seconds_countdown_does_not_jump_to_minutes_on_one_read():
    """실게임 '10s 9s 9m 8s'(QA f5ba724, 재현 못 함) 방어 — 초 카운트다운 중 'NM'은 같은 글자가 한 번 더 읽힐 때만."""
    from mabinogi_addon.tracker.debuff_engine import DebuffEngine
    eng = DebuffEngine({}, [])
    seen = [eng._time_label("a", g, t) for t, g in enumerate(("11", "10", "9", "9M", "8"))]
    assert [s[0] for s in seen] == [None, "10s", "9s", "9s", "8s"]  # 한 번 읽힌 9M은 무시, 9s 유지
    assert eng._suspects == [("a", "9M")]  # 진단 저장 대상
    eng2 = DebuffEngine({}, [])
    seen = [eng2._time_label("b", g, t) for t, g in enumerate(("11", "10", "9M", "9M"))]
    assert [s[0] for s in seen] == [None, "10s", "10s", "9m"]  # 두 번 연속이면 9m
    eng3 = DebuffEngine({}, [])
    assert eng3._time_label("c", "4M", 0) == ("4m", False)  # 카운트다운 아니면 'NM'은 바로


def test_suspect_read_is_saved_for_creator_with_limit(tmp_path, monkeypatch):
    import numpy as np

    from mabinogi_addon.ui import main_window as mw
    monkeypatch.setattr(mw, "_debuff_time_shots", [0])
    region = np.zeros((88, 300, 3), np.uint8)
    base = mw.save_debuff_time_suspect("모모", "9M", region, (25, 17, 16, 16), folder=tmp_path)
    assert (tmp_path / f"{base.name}_icon.png").exists() and (tmp_path / f"{base.name}_region.png").exists()
    for _ in range(mw.DEBUFF_TIME_SHOT_LIMIT + 3):
        mw.save_debuff_time_suspect("모모", "9M", region, (25, 17, 16, 16), folder=tmp_path)
    assert len(list(tmp_path.glob("*_region.png"))) == mw.DEBUFF_TIME_SHOT_LIMIT  # 실행당 상한


def test_engine_hands_suspect_to_saver(monkeypatch):
    region = _region("스크린샷 2026-10-18 001801.png")
    eng = _engine(ORDER)
    eng.set_display_mode("applied")
    got = []
    eng.on_time_suspect = lambda bid, game, reg, box: got.append((bid, game, reg.shape, box))
    for t in (0.0, 0.2, 0.4):
        eng.tick(region, t)
    eng._time_state["모모"] = [12, 0.3, True, 0.4, None]  # 모모가 초 카운트다운 중이었다고 하고 화면은 '4M'
    res = eng.tick(region, 0.6)
    assert got and got[0][0] == "모모" and got[0][1] == "4M" and got[0][3] is not None
    assert [e.time_text for e in res.entries if e.buff_id == "모모"] == ["12s"]  # 한 번은 초 그대로


@pytest.mark.parametrize("creator", [False, True])
def test_suspect_autosave_stays_creator_only(app, monkeypatch, creator):
    """'걸린 것 + 시간'은 모든 사용자(0.45.0)지만 초→분 의심 판독 자동 저장(진단)은 제작자만 그대로."""
    from types import SimpleNamespace

    from mabinogi_addon import config, feature_access
    from mabinogi_addon.ui import main_window as mw
    monkeypatch.setattr(feature_access, "is_creator", lambda: creator)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "테스트"})
    monkeypatch.setattr(mw, "create_live_source", lambda *a, **k: SimpleNamespace(close=lambda: None, grab=lambda: None))
    raw = config._read_local_config()
    raw["debuffTracker"] = {"captureRegion": {"x": 10, "y": 10, "w": 300, "h": 60}, "enabled": True}
    config._write_local_config(raw)
    w = mw.MainWindow()
    try:
        monkeypatch.setattr(w.debuff_tab, "tracked_ids", lambda: ["마법 방어력 보호 감소"], raising=False)
        w._start_debuff_tracking()
        engine = w._debuff_engine
        if engine is None:
            pytest.skip("디버프 추적을 시작할 등록 디버프가 없음(환경)")
        assert (getattr(engine, "on_time_suspect", None) is mw.save_debuff_time_suspect) is creator
        assert w.debuff_tab.display_segments is not None  # 표시 선택은 모두에게
    finally:
        w._force_quit = True
        w.close()
