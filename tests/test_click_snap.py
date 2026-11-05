"""클릭 경계 자동 맞춤(click-snap 명세) — 대상 찾기(tests/data 실화면)·겹침·선택창 클릭/드래그·제작자 전용."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from mabinogi_addon.detect import click_targets as ct

_app = QApplication.instance() or QApplication([])
DATA = Path(__file__).parent / "data"


def _read(name):
    return cv2.imdecode(np.fromfile(str(DATA / name), np.uint8), cv2.IMREAD_COLOR)


@pytest.fixture(scope="module")
def image01():
    return _read("image01.png")


def test_image01_finds_48_cells_three_stat_rows_and_boss(image01):
    t = ct.find_targets(image01)
    kinds = [x.kind for x in t]
    assert kinds.count("skill") == 48
    stats = [x for x in t if x.kind == "stat"]
    assert [x.name for x in stats] == list(ct.STAT_NAMES)
    assert stats[0].rect == (611, 972, 103, 10)
    assert [x.rect for x in t if x.kind == "boss"] == [(698, 817, 521, 37)]
    cells = {x.rect for x in t if x.kind == "skill"}
    assert len(cells) == 48  # 겹치는 칸 없음
    assert all(w == h == 40 for _x, _y, w, h in cells)  # 1080 = 40px 칸


def test_kinds_filter_skill_only(image01):
    t = ct.find_targets(image01, kinds=("skill",))
    assert {x.kind for x in t} == {"skill"} and len(t) == 48


def test_wqhd_window_cells_scale():
    t = ct.find_targets(_read("2026-10-30_windowed_wireweb_1.png"))
    assert sum(x.kind == "skill" for x in t) == 48
    assert sum(x.kind == "stat" for x in t) == 3
    assert sum(x.kind == "boss" for x in t) == 1


def test_no_boss_bar_when_not_visible():
    t = ct.find_targets(_read("mabinogi_2026_11_04_010804.png"), kinds=("boss",))
    assert t == []


def test_blank_or_bad_frame_has_no_targets():
    assert ct.find_targets(np.zeros((1080, 1920, 3), np.uint8)) == []
    assert ct.find_targets(None) == []
    assert ct.find_targets(np.zeros((10, 10), np.uint8)) == []


def test_hit_picks_smallest_covering_target():
    big = ct.Target("boss", (0, 0, 100, 100), "보스 체력바")
    small = ct.Target("stat", (10, 10, 20, 5), "생명력 바")
    assert ct.hit([big, small], 15, 12) is small
    assert ct.hit([big, small], 50, 50) is big
    assert ct.hit([big, small], 150, 50) is None
    assert ct.hit([small], 30, 12) is None  # 오른쪽 끝(배타)
    assert small.label == "생명력 바 20 × 5"


# ---- 선택창 -------------------------------------------------------------------------------------
def _mouse(kind, x, y):
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


@pytest.fixture
def selector(monkeypatch):
    from mabinogi_addon import feature_access
    from mabinogi_addon.ui.region_selector import RegionSelector
    monkeypatch.setattr(feature_access, "is_creator", lambda: True)
    sel = RegionSelector(snap_kinds=("skill", "stat", "boss"))
    sel._targets = [ct.Target("skill", (100, 100, 40, 40), "단축바 칸")]
    sel._dpr = 1.0
    out = {"snapped": [], "selected": []}
    sel.snapped.connect(out["snapped"].append)
    sel.selected.connect(lambda *r: out["selected"].append(r))
    yield sel, out
    sel.close()


def test_click_on_target_snaps_to_its_border(selector):
    sel, out = selector
    sel.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 110, 110))
    assert sel._hover is not None
    sel.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 110, 110))
    sel.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 112, 111))  # 4px 이하 = 클릭
    sel.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 112, 111))
    assert [t.rect for t in out["snapped"]] == [(100, 100, 40, 40)]
    g = sel._screen_geo
    assert out["selected"] == [(g.x() + 100, g.y() + 100, 40, 40)]


def test_moving_more_than_4px_is_a_normal_drag(selector):
    sel, out = selector
    sel.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 110, 110))
    sel.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 110, 110))
    sel.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 170, 150))
    sel.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 170, 150))
    assert out["snapped"] == []
    g = sel._screen_geo
    assert out["selected"] == [(g.x() + 110, g.y() + 110, 61, 41)]  # 기존 드래그 그대로(QRect 양 끝 포함)


def test_dpr_maps_physical_target_to_logical(selector):
    sel, _out = selector
    sel._dpr = 1.5
    r = sel._logical((150, 150, 60, 60))
    assert (r.x(), r.y(), r.width(), r.height()) == (100, 100, 40, 40)


def test_non_creator_never_runs_detection(monkeypatch):
    from mabinogi_addon import feature_access
    from mabinogi_addon.ui import region_selector as rs
    monkeypatch.setattr(feature_access, "is_creator", lambda: False)
    called = []
    monkeypatch.setattr(rs.RegionSelector, "_find_targets", lambda self: called.append(1))
    sel = rs.RegionSelector(snap_kinds=("skill",))
    assert sel._snap_enabled() is False
    sel.start()
    sel.close()
    assert called == [] and sel._targets == []


def test_snap_off_for_crop_fixed_and_plain_modes(monkeypatch, tmp_path):
    from mabinogi_addon import feature_access
    from mabinogi_addon.ui.region_selector import RegionSelector
    monkeypatch.setattr(feature_access, "is_creator", lambda: True)
    assert RegionSelector()._snap_enabled() is False  # snap_kinds 없음(기존 화면들)
    assert RegionSelector(snap_kinds=("skill",), save_path=tmp_path / "a.png")._snap_enabled() is False
    assert RegionSelector(snap_kinds=("skill",))._snap_enabled() is True


def test_custom_overlay_selector_asks_all_three_kinds():
    src = (Path(__file__).parents[1] / "src/mabinogi_addon/ui/custom_overlay_tab.py").read_text(encoding="utf-8")
    assert 'snap_kinds=("skill", "stat", "boss")' in src
