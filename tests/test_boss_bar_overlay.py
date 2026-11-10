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
def test_rising_spike_needs_two_equal_reads_and_big_drop_needs_a_second_read():
    v = BossBarValue()
    assert v.update(87, "pellom", 0).value == 87
    assert v.update(20, "pellom", 0.3).value == 87   # 10%p 넘는 하락 한 번 → 보류(오독일 수 있음)
    assert v.rule == "drop"
    assert v.update(87, "pellom", 0.6).value == 87   # 원래 값으로 돌아옴 → 하락 무시
    assert v.update(20, "pellom", 0.9).value == 87
    assert v.update(19, "pellom", 1.2).value == 19   # 두 번째로 크게 낮은 값(비슷함) → 반영
    assert v.update(30, "pellom", 1.5).value == 19   # 5%p 넘게 오름 한 번 → 무시
    assert v.update(30, "pellom", 1.8).value == 30   # 같은 값 2번 연속 → 반영
    assert v.update(25, "pellom", 2.1).value == 25   # 작은 하락은 바로


def test_misread_46_as_4_does_not_stick():
    """11-05 수집: 47 → 4(46.96 오독) → 45에서 4가 바로 반영돼 45가 '급상승'으로 막혔다."""
    v = BossBarValue()
    v.update(47, "pellom", 0)
    assert v.update(4, "pellom", 0.3).value == 47
    assert v.update(45, "pellom", 0.6).value == 45


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
        tab._tick()  # 10%p 넘는 하락은 한 번 더 읽혀야 반영(장면마다 실제로는 여러 틱)
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
@pytest.mark.parametrize("creator", [False, True])
def test_section_for_everyone_default_off_and_collection_creator_only(monkeypatch, creator):
    """0.45.0(사용자 결정 11-10): 보스바 오버레이 구역은 모든 사용자, 기본 꺼짐(켜기 전 판독 추가·오버레이 없음).
    '진단 · 보스 HP바 수집'은 제작자 전용 그대로. 화면에 '베타'·'제작자 테스트' 표기 없음."""
    from mabinogi_addon import feature_access
    from mabinogi_addon.ui import boss_tab as bt
    monkeypatch.setattr(feature_access, "is_creator", lambda: creator)
    t = bt.BossTab(_Watcher())
    try:
        t.show()
        t.bar_section._tick()
        assert not t.bar_section.isHidden() and t.bar_section.title() == "보스바 오버레이"
        assert "베타" not in t.bar_section.title() and "제작자" not in t.bar_section.title()
        assert not t.bar_section.enable.isChecked()  # 기본 꺼짐
        assert not t.bar_section.wanted() and not t._bar_overlay_on() and t.bar_section._overlay is None
        assert t._diagnostics_allowed() is creator  # 수집·진단은 제작자만
        t.bar_section.enable.setChecked(True)
        assert t.bar_section.wanted()
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
        assert ov.width() == 640 * 1.5 + 4  # 새 기준 640×39 = 100%
        assert ov.set_state("펠롬", 87, False, (90, 60, 30)) is True
        assert ov.set_state("펠롬", 87, False, (90, 60, 30)) is False  # 같으면 다시 그리지 않음
        assert ov.has_content()
        ov.set_state(None, None)
        assert not ov.has_content()
        ov.set_locked(False)
        assert ov.has_content()  # 잠금 해제 = 예시 바
    finally:
        ov.close()


# ---- 문제 순간 수집(명세 6절) -------------------------------------------------------------------
def test_tracker_reports_rule_start_once():
    v = BossBarValue()
    v.update(50, None, 0)
    assert v.rule is None
    v.update(70, None, 0.3)
    assert v.rule == "jump"
    v.update(None, None, 0.6)
    assert v.rule == "unread"
    v.update(None, None, 0.9)
    assert v.rule is None  # 계속 못 읽는 동안은 다시 시작으로 치지 않는다


@pytest.fixture
def collecting(tab, tmp_path):
    tab._shot_dir = tmp_path
    tab.diagnostics_btn.setChecked(True)
    tab.collect_chk.setChecked(True)
    return tab


def _files(path, suffix=".png"):
    return sorted(p.name for p in path.iterdir() if p.suffix == suffix)


def test_rule_start_auto_saves_extended_rect_with_reason_and_json(collecting, tmp_path, monkeypatch):
    import json
    tab = collecting
    monkeypatch.setattr(tab, "_frame_changed", lambda frame: False)  # 바 바뀜 자동 저장은 빼고 규칙 저장만 본다
    tab.show_screen("스크린샷 2026-10-09 185217.png", (1018, 1248, 521, 37))  # 페타크 100
    tab._tick()
    assert _files(tmp_path) == []
    tab.show_screen("2026-10-11_123333.png", (1658, 1967, 521, 37))  # 못 읽음 시작 → 저장
    tab._tick()
    tab._tick()  # 계속 못 읽음 → 다시 저장하지 않음
    names = _files(tmp_path)
    assert len(names) == 1 and names[0].startswith("gomok_petak_hpxxx_show100_unread_")
    img = image_io.imread(str(tmp_path / names[0]), cv2.IMREAD_COLOR)
    assert img.shape[0] == 37 + 45 + 6  # 오버레이가 읽은 늘린 사각형(한 칸 위 포함)
    meta = json.loads((tmp_path / names[0]).with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["rule"] == "unread" and meta["shown"] == 100 and meta["area"] == [1658, 1967 - 45, 521, 88]


def test_upper_row_switch_is_tagged(collecting, tmp_path, monkeypatch):
    tab = collecting
    monkeypatch.setattr(tab, "_frame_changed", lambda frame: False)
    name, (x, y, w, h), _ = PELLOM[1]
    tab.show_screen(name, (x, y + tab.BAR_PITCH, w, h))
    tab._tick()
    assert [n for n in _files(tmp_path) if "_upper_" in n]


def test_unregistered_boss_saved_in_collect_mode_and_cap(collecting, tmp_path):
    tab = collecting
    tab._auto_saved = tab.AUTO_LIMIT - 1
    for i, (name, _hp) in enumerate(GLASS[:3]):
        tab.show_screen(name, (1018, 1248, 521, 37))
        for _ in range(3 if i == 0 else 1):
            tab._tick()
    names = _files(tmp_path)
    assert len(names) == 1 and names[0].startswith("unknown_")  # 미등록 보스도, 상한 200에서 멈춤
    assert "200장" in tab.collect_label.text()


def test_snapshot_saves_recent_ten_readings(collecting, tmp_path):
    tab = collecting
    tab.collect_chk.setChecked(False)
    for i in range(12):
        name, box, _ = PELLOM[i % 5]
        tab.show_screen(name, box)
        tab._tick()
    tab._save_snapshot()
    names = _files(tmp_path)
    assert len(names) == tab.RECENT_SHOTS and all("_show" in n for n in names)
    assert len(_files(tmp_path, ".json")) == tab.RECENT_SHOTS


def test_snapshot_without_overlay_keeps_old_single_shot(collecting, tmp_path):
    tab = collecting
    tab.collect_chk.setChecked(False)
    tab.bar_section.enable.setChecked(False)
    tab.show_screen(*PELLOM[0][:2])
    tab._tick()
    tab._save_snapshot()
    assert _files(tmp_path) == ["pellom_hp099_000.png"] and _files(tmp_path, ".json") == []


def test_shots_are_written_off_the_ui_thread(collecting, tmp_path, monkeypatch):
    import threading
    tab = collecting
    monkeypatch.setattr(type(tab), "INLINE_JOBS", False)
    threads = []
    original = image_io.imwrite
    monkeypatch.setattr(image_io, "imwrite", lambda *a, **k: threads.append(threading.current_thread()) or original(*a, **k))
    tab._queue_shots([{"frame": np.zeros((10, 10, 3), np.uint8), "boss": None, "raw": None}], auto=False)
    tab._shot_writer.shutdown(wait=True)
    assert threads and threads[0] is not threading.main_thread()



# ---- 수집 묶음 재생(11-05 제작자 수집: 궁극의 글라스 기브넨 100→7, 펠롬 100→25) --------------------------------
ZIP = "eotgallin_poinche_hp098_058.zip"
# 미등록 보스(궁극의 글라스 기브넨) 실제 정수 %(화면 확인) — 그 전 000~016은 바가 없거나 가려짐
GLASS_TRUE = dict(zip(range(17, 47), (100, 99, 98, 96, 95, 94, 93, 91, 85, 84, 80, 77, 76, 76, 75, 59, 42, 21, 26, 25, 24,
                                      23, 21, 20, 19, 14, 14, 9, 7, 7)))


def _replay_frames(tmp_path):
    import re
    import zipfile
    with zipfile.ZipFile(f"tests/data/{ZIP}") as z:
        names = [n for n in z.namelist() if re.match(r"(unknown|pellom)_hp.*_(\d{3})\.png$", n)]
        z.extractall(tmp_path, names)
    names.sort(key=lambda n: int(n[-7:-4]))
    return [(n, image_io.imread(str(tmp_path / n), cv2.IMREAD_COLOR)) for n in names]


def _truth(name, prev):
    import re
    idx = int(name[-7:-4])
    if name.startswith("unknown"):
        return GLASS_TRUE.get(idx)
    if idx == 107:
        return 46  # 46.96 % — 예전 판독 4
    m = re.match(r"pellom_hp(\d{3})_", name)
    return int(m.group(1)) if m else prev  # 못 읽는 순간(가려짐) = 직전 값 흐리게


def test_replay_frames_split_by_boss_cover_all():
    """재생은 보스별 두 묶음(미등록 보스 000~046 → 펠롬 047~138, 이어진 구간) — 묶음 합 = 수집 139장 전부(QA dc81399: 한 건 35~59초)."""
    import re
    import zipfile
    with zipfile.ZipFile(f"tests/data/{ZIP}") as z:
        names = sorted((n for n in z.namelist() if re.match(r"(unknown|pellom)_hp.*_(\d{3})\.png$", n)), key=lambda n: int(n[-7:-4]))
    split = [n.split("_")[0] for n in names]
    assert len(names) == 139 and split == ["unknown"] * 47 + ["pellom"] * 92


@pytest.mark.parametrize("boss", ["unknown", "pellom"])
def test_collected_frames_replay_shows_true_value(tab, tmp_path, monkeypatch, boss):
    frames = [(n, f) for n, f in _replay_frames(tmp_path) if n.startswith(boss)]
    assert len(frames) == {"unknown": 47, "pellom": 92}[boss] and all(f.shape[:2] == (88, 521) for _n, f in frames)
    state = {}
    tab._region = {"x": 0, "y": 45, "w": 521, "h": 37}
    monkeypatch.setattr(tab, "_grab_region", lambda: dict(tab._region))
    monkeypatch.setattr(tab, "_grab_rect", lambda x, y, w, h: state["img"][y:y + h, x:x + w].copy())
    wrong, expected = [], None
    for name, img in frames:
        state["img"] = img
        for _ in range(3):  # 저장 간격이 1초 이상 = 실제로는 여러 틱. 바가 없던 뒤 존재 확인은 3틱에 한 번
            tab._tick()
        expected = _truth(name, expected)
        shown = _shown(tab)
        if shown.value != expected:
            wrong.append((name, shown.value, expected))
    assert wrong == []


@pytest.mark.parametrize("name,top,expected", [
    ("pellom_hp004_107.png", 45, 46),             # 펠롬 46.96 % (예전 4)
    ("eotgallin_poinche_hp004_002.png", 1, 46),   # 포인세 46.78 % — 37px 높이(지금 판독 영역)
    ("eotgallin_poinche_hp004_109.png", 1, 46),   # 포인세 46.86 %
    ("pellom_hp047_106.png", 45, 47), ("pellom_hp045_108.png", 45, 45),
    ("eotgallin_poinche_hp047_001.png", 1, 47), ("eotgallin_poinche_hp045_003.png", 1, 45),
    ("eotgallin_poinche_hp004_004.png", 1, 44), ("eotgallin_poinche_hp004_000.png", 1, 48),
])
def test_read_percent_46_is_not_4(tmp_path, name, top, expected):
    import zipfile
    from mabinogi_addon.detect.boss_hp_reader import read_percent
    with zipfile.ZipFile(f"tests/data/{ZIP}") as z:
        z.extract(name, tmp_path)
    frame = image_io.imread(str(tmp_path / name), cv2.IMREAD_COLOR)[top:top + 37]
    assert read_percent(frame[:, int(frame.shape[1] * 0.58):]) == expected


def test_low_hp_height_rule_skipped(tab, tmp_path, monkeypatch):
    """7.70 %에서 채움이 짧아 띠 높이 18px — 높이 규칙으로 버리지 않는다(9%에 멈추던 문제)."""
    import zipfile
    name = "unknown_hpxxx_045.png"
    with zipfile.ZipFile(f"tests/data/{ZIP}") as z:
        z.extract(name, tmp_path)
    img = image_io.imread(str(tmp_path / name), cv2.IMREAD_COLOR)
    assert bar_band_height(img, 45 + 18) < BAR_BAND_MIN
    out = {"boss_id": None, "raw_hp": None, "bar_pct": 7, "bar": True, "frame": img[45:82]}
    reading = tab._overlay_reading(img, 45, 37, out)
    assert reading["value"] == 7 and reading["rule"] is None


@pytest.mark.parametrize("name,expected", [
    ("eotgallin_poinche_hp004_002.png", 46),  # 46.78 % — 40px 높이 그대로(10-13 수집)
    ("eotgallin_poinche_hp004_109.png", 46),  # 46.86 %
    ("eotgallin_poinche_hp004_000.png", 48), ("eotgallin_poinche_hp004_004.png", 44),
    ("eotgallin_poinche_hp004_008.png", 40), ("eotgallin_poinche_hp045_003.png", 45),
    ("eotgallin_poinche_hp047_001.png", 47),
])
def test_read_percent_tall_40px_box(tmp_path, name, expected):
    """바(37px)보다 높게 잡은 40px 박스: 숫자 위치를 37px 배율로 봐서 46.xx도 46(예전 4)."""
    import zipfile
    from mabinogi_addon.detect.boss_hp_reader import read_percent
    with zipfile.ZipFile(f"tests/data/{ZIP}") as z:
        z.extract(name, tmp_path)
    frame = image_io.imread(str(tmp_path / name), cv2.IMREAD_COLOR)
    assert frame.shape[0] == 40
    assert read_percent(frame[:, int(frame.shape[1] * 0.58):]) == expected


# ---- 소수 두 자리(표시용, 사용자 확정 11-05) ------------------------------------------------------------------
FRAC_TRUE = [  # (zip 안 파일, 판독 영역 위 여백, 화면 글자) — 화면으로 확인
    ("pellom_hp047_106.png", 45, "47.58"), ("pellom_hp004_107.png", 45, "46.96"), ("pellom_hp045_108.png", 45, "45.72"),
    ("unknown_hpxxx_032.png", 45, "59.46"), ("unknown_hpxxx_033.png", 45, "42.27"), ("unknown_hpxxx_034.png", 45, "21.97"),
    ("unknown_hpxxx_035.png", 45, "26.52"),
    ("eotgallin_poinche_hp004_000.png", 1, "48.00"), ("eotgallin_poinche_hp004_002.png", 1, "46.78"),
    ("eotgallin_poinche_hp004_004.png", 1, "44.70"), ("eotgallin_poinche_hp004_008.png", 1, "40.31"),
    ("eotgallin_poinche_hp004_109.png", 1, "46.86"), ("eotgallin_poinche_hp045_003.png", 1, "45.65"),
    ("eotgallin_poinche_hp047_001.png", 1, "47.43"),
]
LOW_HP = [("unknown_hpxxx_042.png", "14.87"), ("unknown_hpxxx_043.png", "14.23"), ("unknown_hpxxx_044.png", "9.42"),
          ("unknown_hpxxx_045.png", "7.70")]  # 화면 글자


def _zip_frame(tmp_path, name, top):
    import zipfile
    with zipfile.ZipFile(f"tests/data/{ZIP}") as z:
        z.extract(name, tmp_path)
    frame = image_io.imread(str(tmp_path / name), cv2.IMREAD_COLOR)[top:top + 37]
    return frame[:, int(frame.shape[1] * 0.58):]


@pytest.mark.parametrize("name,top,text", FRAC_TRUE)
def test_fraction_matches_screen_text(tmp_path, name, top, text):
    from mabinogi_addon.detect.boss_hp_reader import read_percent, read_percent_frac
    reg = _zip_frame(tmp_path, name, top)
    whole, frac = read_percent_frac(reg)
    assert f"{whole}.{frac}" == text
    assert whole == read_percent(reg)  # 정수 경로·결과는 그대로


@pytest.mark.parametrize("name,text", LOW_HP)
def test_low_hp_shows_fraction_from_white_text(tmp_path, name, text):
    """저HP(회색 빈 바 위 흰 숫자)도 소수 — 흰 글자 샘플로(사용자 11-08, QA dee7b93). 예전엔 정수만."""
    from mabinogi_addon.detect.boss_hp_reader import read_percent, read_percent_frac
    reg = _zip_frame(tmp_path, name, 45)
    whole, frac = read_percent_frac(reg)
    assert f"{whole}.{frac}" == text and whole == read_percent(reg)


ALL_FRAMES_SHARDS = 4  # 수집 프레임 전부를 4묶음으로 — 한 건 60초 제한에 닿던 것(단독 58.8초, QA dc81399). 범위는 그대로(묶음 합 = 전부)


def _collected_frame_names():
    import zipfile
    with zipfile.ZipFile(f"tests/data/{ZIP}") as z:
        return sorted(n for n in z.namelist() if n.endswith(".png"))


def test_fraction_shards_cover_all_collected_frames():
    names = _collected_frame_names()
    shards = [names[i::ALL_FRAMES_SHARDS] for i in range(ALL_FRAMES_SHARDS)]
    assert sorted(n for shard in shards for n in shard) == names and len(names) > 300


@pytest.mark.parametrize("shard", range(ALL_FRAMES_SHARDS))
def test_fraction_never_changes_integer_on_all_collected_frames(shard):
    import zipfile

    import numpy as np
    from mabinogi_addon.detect.boss_hp_reader import read_percent, read_percent_frac
    names = _collected_frame_names()[shard::ALL_FRAMES_SHARDS]
    with zipfile.ZipFile(f"tests/data/{ZIP}") as z:
        for name in names:
            img = cv2.imdecode(np.frombuffer(z.read(name), np.uint8), cv2.IMREAD_COLOR)  # 압축을 풀어 쓰지 않고 메모리에서
            reg = (img[45:82] if img.shape[0] == 88 else img)
            reg = reg[:, int(reg.shape[1] * 0.58):]
            whole, frac = read_percent_frac(reg)
            assert whole == read_percent(reg), name
            assert frac is None or (whole is not None and len(frac) == 2 and frac.isdigit()), name


def test_overlay_draws_fraction_for_registered_and_unregistered(tab, tmp_path, monkeypatch):
    import zipfile
    state = {}
    tab._region = {"x": 0, "y": 45, "w": 521, "h": 37}
    monkeypatch.setattr(tab, "_grab_region", lambda: dict(tab._region))
    monkeypatch.setattr(tab, "_grab_rect", lambda x, y, w, h: state["img"][y:y + h, x:x + w].copy())
    with zipfile.ZipFile(f"tests/data/{ZIP}") as z:
        z.extractall(tmp_path, ["pellom_hp047_106.png", "unknown_hpxxx_034.png", "unknown_hpxxx_045.png"])
    for name, expected in (("pellom_hp047_106.png", ("펠롬", 47, "58")), ("unknown_hpxxx_034.png", ("보스", 21, "97")),
                           ("unknown_hpxxx_045.png", ("보스", 7, "70"))):  # 저HP 회색 바탕도 소수(11-08)
        tab.bar_section.value.reset()
        state["img"] = image_io.imread(str(tmp_path / name), cv2.IMREAD_COLOR)
        for _ in range(3):
            tab._tick()
        st = tab.bar_section._overlay.state()
        assert (st[0], st[1], st[4]) == expected, name


# ---- 기본 크기·25% 줄(제작자 시험 #194, 11-05) ----------------------------------------------------------------
def test_new_base_size_and_old_scale_converted():
    from mabinogi_addon.ui.boss_bar_overlay import BossBarOverlay
    ov = BossBarOverlay(100)
    try:
        assert (ov.width() - 4, ov.height() - 4 - ov._scale_h()) == (640, 39)  # 바는 예전 150%(540×39) 높이, 길이는 640(위에 눈금 글자 줄)
    finally:
        ov.close()
    config.save_boss_bar_overlay({"enabled": True})
    import json
    from mabinogi_addon.config import LOCAL_CONFIG_PATH
    raw = json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["bossBarOverlay"]["scale"] = 150  # 예전 기준으로 저장된 배율
    LOCAL_CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    assert config.load_boss_bar_overlay()["scale"] == 100  # 같은 높이(39px) = 새 100%
    config.save_boss_bar_overlay({"scale": 120})
    assert config.load_boss_bar_overlay()["scale"] == 120  # 새 기준으로 저장한 값은 그대로


def test_quarter_lines_inside_bar_under_pattern_lines():
    """25·50·75%에 옅은 흰 줄 — 바 안쪽만, 노란 패턴 선이 같은 자리면 노란 선이 보인다."""
    import numpy as np
    from PySide6.QtGui import QImage
    from mabinogi_addon.ui.boss_bar_overlay import BossBarOverlay

    def pixels(marks):
        ov = BossBarOverlay(100)
        try:
            ov.set_state("보스", 10, False, marks)  # 채움이 짧아 25% 이후는 빈 바(어두운 바탕)
            img = ov.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
            return arr[:, :img.width()].copy()
        finally:
            ov.close()
    plain = pixels(())
    inner_x0, inner_w, mid = 2 + 3, 640 - 6, 2 + 39 // 2
    x50 = round(inner_x0 + inner_w * 0.5)
    near = plain[mid, x50 - 1:x50 + 2, :3].astype(int).max()
    away = plain[mid, x50 + 8, :3].astype(int).max()
    assert near > away + 20  # 50% 자리에 옅은 줄
    for y in (0, 1, plain.shape[0] - 1):  # 바 밖(테두리 바깥 여백)은 옆자리와 같음 = 줄이 넘지 않음
        assert abs(int(plain[y, x50, 3]) - int(plain[y, x50 + 8, 3])) <= 2
    marked = pixels((50,))
    r, g, b = marked[mid, x50, :3].astype(int)
    assert r > 150 and g > 120 and b < 120  # 같은 자리면 노란 패턴 선이 위


@pytest.mark.parametrize("zip_name,name,y,h,expected", [
    ("gomok_petak_hp019_158.zip", "gomok_petak_hp017_159.png", 38, 37, ("고목의 페타크", 17, "74")),  # 등록 보스
    ("unknown_hpxxx_show001_upper_197.zip", "gomok_petak_hp018_128.png", 38, 37, ("고목의 페타크", 18, "23")),
    ("eotgallin_poinche_hp098_058.zip", "unknown_hpxxx_041.png", 40, 37, ("보스", 19, "55")),  # 미등록(보스바 확인 경로)
    ("gomok_petak_hp019_158.zip", "gomok_petak_hp017_159.png", 50, 37, ("고목의 페타크", 17, "74")),  # 원래 맞던 자리는 그대로
    ("gomok_petak_hp019_158.zip", "gomok_petak_hpxxx_184.png", 40, 41, ("보스", 12, None)),  # 두 자리 오독 12.84 → 19(QA f5ba724)
])
@pytest.mark.parametrize("fix", [False, True])
def test_overlay_rereads_low_hp_one_when_region_is_shifted(tab, tmp_path, monkeypatch, zip_name, name, y, h, expected, fix):
    """등록 영역이 바와 세로로 어긋나면(위 7px·아래 5px) 숫자가 잘려 '1'로 읽던 것 — 늘린 캡처의 ±6px에서 흰 글자로 다시(QA 4f106aa)."""
    import zipfile

    from mabinogi_addon.detect import boss_hp_reader
    if not fix:
        monkeypatch.setattr(boss_hp_reader, "recheck_low_hp", lambda p, v, f=None, region_rows=None: (v, f))
    state = {}
    tab._region = {"x": 0, "y": y, "w": 521, "h": h}
    monkeypatch.setattr(tab, "_grab_region", lambda: dict(tab._region))
    monkeypatch.setattr(tab, "_grab_rect", lambda x, yy, w, hh: state["img"][yy:yy + hh, x:x + w].copy())
    with zipfile.ZipFile(f"tests/data/{zip_name}") as z:
        z.extract(name, tmp_path)
    state["img"] = image_io.imread(str(tmp_path / name), cv2.IMREAD_COLOR)
    tab.bar_section.value.reset()
    for _ in range(3):
        tab._tick()
    st = tab.bar_section._overlay.state()
    if fix or y == 50:
        assert (st[0], st[1], st[4]) == expected
    else:
        assert st[1] != expected[1]  # 수정 전 현상(1 또는 19 등 오독)
