"""보스바 오버레이(보스바 오버레이 명세, 제작자 전용) — 값 규칙·띠 높이·한 칸 위 보스바·실화면 판독·그리기·구역."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.detect.boss_bar import BAR_BAND_MAX, BAR_BAND_MIN, bar_band_height, make_validator
from mabinogi_addon.tracker.boss_bar_value import BossBarValue

_app = QApplication.instance() or QApplication([])
_cache = {}


def _img(name):
    if name not in _cache:
        _cache[name] = image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)
    return _cache[name]


PELLOM = [("스크린샷 2026-10-18 001116.png", (1018, 1248, 521, 37), 99),
          ("스크린샷 2026-10-18 001216.png", (1016, 1246, 521, 37), 87),
          ("스크린샷 2026-10-18 001307.png", (1016, 1246, 521, 37), 75),
          ("스크린샷 2026-10-18 001541.png", (1016, 1246, 521, 37), 42),
          ("스크린샷 2026-10-18 001801.png", (1016, 1246, 521, 37), 8)]
GLASS = [(f"스크린샷 2026-10-09 {n}.png", v) for n, v in
         (("190901", 98), ("190905", 97), ("190909", 94), ("190911", 93), ("190915", 92), ("190926", 90))]


# ---- 값 규칙(명세 3절-2·못 읽음) ----------------------------------------------------------------
def test_rising_spike_needs_two_equal_reads_falling_is_immediate():
    v = BossBarValue()
    assert v.update(87, "pellom", 0).value == 87
    assert v.update(20, "pellom", 0.3).value == 20   # 내려가는 값은 바로
    assert v.update(87, "pellom", 0.6).value == 20   # 5%p 넘게 오름 한 번 → 무시
    assert v.update(87, "pellom", 0.9).value == 87   # 같은 값 2번 연속 → 반영


def test_single_misread_up_is_ignored_and_small_rise_passes():
    v = BossBarValue()
    v.update(50, None, 0)
    assert v.update(56, None, 0.3).value == 50
    assert v.update(50, None, 0.6).value == 50
    assert v.update(55, None, 0.9).value == 55  # 5%p 이하 오름은 바로(회복 기믹)
    assert v.update(61, None, 1.2).value == 55 and v.update(62, None, 1.5).value == 55  # 다른 값이면 다시 대기


def test_unreadable_dims_then_hides_after_1_8s():
    v = BossBarValue()
    v.update(41, None, 0)
    s = v.update(None, None, 1.0)
    assert (s.value, s.stale) == (41, True)
    assert v.update(None, None, 1.8).value == 41
    assert v.update(None, None, 1.81).value is None  # 1.8초 넘게 못 읽음 → 숨김
    v.update(41, None, 2.0)
    assert v.tick(3.9).value is None  # 판독이 멈춰도 시간으로 숨김


def test_boss_change_resets_and_name_flicker_keeps_boss():
    v = BossBarValue()
    v.update(30, "pellom", 0)
    assert v.update(29, None, 0.3).boss == "pellom"  # 이름 식별 한 번 깜빡 → 같은 보스
    s = v.update(95, "lenen_miir", 0.6)  # 다른 등록 보스 → 처음부터(오름 확인 없이)
    assert (s.value, s.boss) == (95, "lenen_miir")
    assert v.update(120, "lenen_miir", 0.9).stale  # 범위 밖 = 못 읽음


# ---- 띠 높이(명세 3절-3) ---------------------------------------------------------------------------
def _ext(name, box, up=45, down=6):
    x, y, w, h = box
    return _img(name)[y - up:y + h + down, x:x + w]


@pytest.mark.parametrize("name,box,_v", PELLOM)
def test_band_height_of_real_boss_bars(name, box, _v):
    assert 36 <= bar_band_height(_ext(name, box), 45 + 18) <= 39


def test_raid_boss_45px_bar_still_counts():
    h = bar_band_height(_ext(GLASS[0][0], (1018, 1248, 521, 37)), 45 + 18)
    assert h == 45 and BAR_BAND_MIN <= h <= BAR_BAND_MAX  # 궁극의 글라스 기브넨(미등록 레이드 보스)


def test_thin_bar_is_not_a_boss_bar():
    frame = _ext(*PELLOM[1][:2]).copy()
    frame[:45 + 12] = 20  # 바 위아래를 지워 12px 띠만 남김(얇은 일반 체력바 모양)
    frame[45 + 24:] = 20
    assert bar_band_height(frame, 45 + 18) == 12


def test_validator_percent_mode_and_bool_mode_agree():
    frame = _img(GLASS[0][0])[1248:1285, 1018:1539]
    assert make_validator()(frame) is True
    assert make_validator(return_percent=True)(frame) == 98
    assert make_validator(return_percent=True)(np.zeros((37, 521, 3), np.uint8)) is None


# ---- 보스 탭 판독(실화면) --------------------------------------------------------------------------
class _Watcher:
    active = True

    def is_game_active(self):
        return self.active

    def is_self_active(self):
        return False


@pytest.fixture
def tab(monkeypatch):
    from mabinogi_addon import feature_access
    from mabinogi_addon.ui import boss_tab as bt
    monkeypatch.setattr(feature_access, "is_creator", lambda: True)
    monkeypatch.setattr(bt.BossTab, "INLINE_JOBS", True)
    config.save_boss_bar_overlay({"enabled": True})
    t = bt.BossTab(_Watcher())
    t._timer.stop()
    t.bar_section._timer.stop()
    monkeypatch.setattr(t, "_show_preview", lambda *a: None)
    monkeypatch.setattr(t, "_play", lambda *a: None)
    state = {}

    def show(name, box):
        x, y, w, h = box
        state["img"] = _img(name)
        t._region = {"x": x, "y": y, "w": w, "h": h}
        monkeypatch.setattr(t, "_grab_region", lambda: dict(t._region))
    monkeypatch.setattr(t, "_grab_rect", lambda x, y, w, h: state["img"][y:y + h, x:x + w].copy())
    t.show_screen = show
    yield t
    t.shutdown()


def _shown(tab):
    return tab.bar_section.value.shown()


def test_registered_pellom_five_screens(tab):
    for name, box, hp in PELLOM:
        tab.show_screen(name, box)
        tab._tick()
        s = _shown(tab)
        assert (s.value, s.boss, s.stale) == (hp, "pellom", False), name
    ov = tab.bar_section._overlay
    assert ov.state()[:2] == ("펠롬", 8) and ov.state()[3] == tab._bosses["pellom"].thresholds  # 패턴 구간 선


def test_unregistered_boss_uses_presence_percent_and_name_boss(tab):
    for i, (name, hp) in enumerate(GLASS):  # 98 → 90 내려가는 연속 장면
        tab.show_screen(name, (1018, 1248, 521, 37))
        for _ in range(3 if i == 0 else 1):  # 바가 없던 동안 존재 확인은 3틱에 한 번(기존 동작) — 첫 장면만 최대 3틱
            tab._tick()
        assert (_shown(tab).value, _shown(tab).boss) == (hp, None), name
    assert tab.bar_section._overlay.state()[0] == "보스"
    assert tab.bar_section._overlay.state()[3] == ()  # 미등록 보스는 패턴 선 없음


def test_misread_screen_dims_last_value_instead_of_new_number(tab):
    tab.show_screen("스크린샷 2026-10-09 185217.png", (1018, 1248, 521, 37))  # 고목 페타크 100
    tab._tick()
    assert _shown(tab).value == 100
    tab.show_screen("2026-10-11_123333.png", (1658, 1967, 521, 37))  # 예전에 100을 30으로 읽던 화면 → 못 읽음
    tab._tick()
    s = _shown(tab)
    assert (s.value, s.stale) == (100, True)
    assert tab.bar_section._overlay.state()[2] is True  # 흐림 + …


def test_region_on_erg_bar_uses_the_boss_bar_one_row_above(tab):
    name, (x, y, w, h), hp = PELLOM[1]
    tab.show_screen(name, (x, y + tab.BAR_PITCH, w, h))  # 영역이 '어둠의 에르그' 자리(기믹으로 밀린 경우와 같은 모양)
    tab._tick()
    assert (_shown(tab).value, _shown(tab).boss) == (hp, "pellom")


def test_no_boss_screen_hides(tab):
    tab.show_screen("스크린샷 2026-10-18 001216.png", (1016, 1246, 521, 37))
    tab._tick()
    assert _shown(tab).value == 87
    tab.show_screen("mabinogi_2026_11_04_010804.png", (1016, 1246, 521, 37))  # 보스 없는 화면
    import time
    tab._tick()
    assert _shown(tab).stale
    tab.bar_section.value.tick(time.monotonic() + 2.0)
    tab.bar_section._show()
    assert not tab.bar_section._overlay.isVisible()


def test_overlay_off_keeps_old_capture_and_reading(monkeypatch, tab):
    tab.bar_section.enable.setChecked(False)
    sizes = []
    img = _img(PELLOM[0][0])
    monkeypatch.setattr(tab, "_grab_rect", lambda x, y, w, h: sizes.append((x, y, w, h)) or img[y:y + h, x:x + w].copy())
    tab.show_screen(*PELLOM[0][:2])
    monkeypatch.setattr(tab, "_grab_rect", lambda x, y, w, h: sizes.append((x, y, w, h)) or img[y:y + h, x:x + w].copy())
    tab._tick()
    assert sizes == [(1018, 1248, 521, 37)]  # 오버레이를 안 쓰면 늘린 캡처 없음
    assert tab._last_raw_hp == 99


def test_overlay_on_captures_one_taller_rect(monkeypatch, tab):
    sizes = []
    img = _img(PELLOM[0][0])
    tab.show_screen(*PELLOM[0][:2])
    monkeypatch.setattr(tab, "_grab_rect", lambda x, y, w, h: sizes.append((x, y, w, h)) or img[y:y + h, x:x + w].copy())
    tab._tick()
    assert sizes == [(1018, 1248 - 45, 521, 37 + 45 + 6)]
    assert tab._last_raw_hp == 99 and tab._stable_hp is None or tab._stable_hp == 99  # 기존 판독은 그대로


# ---- 구역·제작자 전용 ----------------------------------------------------------------------------
def test_non_creator_has_no_section_and_no_overlay_reading(monkeypatch):
    from mabinogi_addon import feature_access
    from mabinogi_addon.ui import boss_tab as bt
    monkeypatch.setattr(feature_access, "is_creator", lambda: False)
    config.save_boss_bar_overlay({"enabled": True})
    t = bt.BossTab(_Watcher())
    try:
        t.show()
        t.bar_section._tick()
        assert t.bar_section.isHidden()
        assert not t.bar_section.wanted() and not t._bar_overlay_on()
        assert t.bar_section._overlay is None
    finally:
        t.shutdown()
        t.close()


def test_section_visible_for_creator_and_paused_hides(tab):
    tab.show()
    tab.bar_section._tick()
    assert tab.bar_section.isVisible()
    tab.show_screen(*PELLOM[1][:2])
    tab._tick()
    assert tab.bar_section._overlay.isVisible()
    tab.set_paused(True)
    assert not tab.bar_section._overlay.isVisible() and not tab._bar_overlay_on()
    tab.close()


def test_settings_saved_and_overlay_redraws_only_on_change(tab):
    sec = tab.bar_section
    sec.scale_spin.setValue(150)
    sec.opacity_spin.setValue(80)
    cfg = config.load_boss_bar_overlay()
    assert (cfg["scale"], cfg["opacity"], cfg["enabled"]) == (150, 80, True)
    from mabinogi_addon.ui.boss_bar_overlay import BossBarOverlay
    ov = BossBarOverlay(150)
    try:
        assert ov.width() == 360 * 1.5 + 4
        assert ov.set_state("펠롬", 87, False, (90, 60, 30)) is True
        assert ov.set_state("펠롬", 87, False, (90, 60, 30)) is False  # 같으면 다시 그리지 않음
        assert ov.has_content()
        ov.set_state(None, None)
        assert not ov.has_content()
        ov.set_locked(False)
        assert ov.has_content()  # 잠금 해제 = 예시 바
    finally:
        ov.close()
