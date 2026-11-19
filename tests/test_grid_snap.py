"""격자 스냅이 화면 정중앙을 기준으로 동작하는지."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint

from mabinogi_addon.ui import grid


def test_snap_is_center_based(monkeypatch):
    monkeypatch.setattr(grid, "_screen_center", lambda: (1000, 500))
    # 중앙 자체는 그대로.
    assert grid.snap(QPoint(1000, 500), 32) == QPoint(1000, 500)
    # 중앙에서 한 칸 근처 → 중앙±격자 배수로 반올림.
    assert grid.snap(QPoint(1000 + 20, 500 + 20), 32) == QPoint(1032, 532)
    assert grid.snap(QPoint(1000 - 20, 500 - 10), 32) == QPoint(968, 500)
    # 중앙에서 떨어진 임의 좌표도 중앙 기준 격자에 정렬(0 기준 아님).
    p = grid.snap(QPoint(1003, 500), 32)
    assert (p.x() - 1000) % 32 == 0


# ---- 격자 크기 선택지(사용자 결정 11-19): 8·11·16·19·24, 기본 16, 예전 값 옮기기 ----
def test_grid_size_choices_and_default():
    from mabinogi_addon import config
    assert config.GRID_SIZES == (8, 11, 16, 19, 24)
    assert config.load_grid_size() == 16 == grid._DEFAULT_SIZE


@pytest.mark.parametrize(("saved", "expected"), [
    (32, 24), (48, 24), (64, 24), (25, 24), (4, 8), (12, 11), (13, 11), (14, 16), (18, 19), (20, 19),
    (21, 19), (22, 24), (16, 16), (11, 11), (0, 16), (-3, 16), ("32", 16), (None, 16), (True, 16),
])
def test_old_grid_size_moves_to_choice(saved, expected):
    from mabinogi_addon import config
    data = config._read_local_config()
    data["general"] = {"gridSize": saved}
    config._write_local_config(data)
    assert config.load_grid_size() == expected


def test_odd_grid_reaches_odd_offsets_from_center(monkeypatch):
    monkeypatch.setattr(grid, "_screen_center", lambda: (960, 540))
    # 11px 격자: 중앙에서 홀수 거리(±11·±33) 자리에 맞는다 — 짝수 칸만으론 못 가던 자리
    assert grid.snap(QPoint(960 + 12, 540 - 30), 11) == QPoint(971, 507)
    assert grid.snap(QPoint(960 - 20, 540 + 19), 19) == QPoint(941, 559)
    for s in (11, 19):
        p = grid.snap(QPoint(1234, 777), s)
        assert (p.x() - 960) % s == 0 and (p.y() - 540) % s == 0


def test_odd_grid_guide_paints(monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    guide = grid._GridGuide()
    guide.resize(101, 61)
    guide._size = 11
    image = guide.grab().toImage()  # 홀수 칸에서도 그리기 예외 없음
    assert image.width() == 101
    guide.close()


def test_settings_combo_matches_saved_and_snap():
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from mabinogi_addon import config
    from mabinogi_addon.ui.settings_tab import SettingsTab
    QApplication.instance() or QApplication([])
    config.save_grid_size(48)  # 예전 값 → 콤보·스냅 모두 24
    tab = SettingsTab(SimpleNamespace(is_game_active=lambda: False, is_self_active=lambda: False,
                                      set_game_exe=lambda *_: None))
    try:
        combo = tab._grid_size
        assert [combo.itemData(i) for i in range(combo.count())] == [8, 11, 16, 19, 24]
        assert combo.currentData() == 24 == grid.size()
        combo.setCurrentIndex(combo.findData(11))
        assert config.load_grid_size() == 11 == grid.size()
    finally:
        tab.close()
