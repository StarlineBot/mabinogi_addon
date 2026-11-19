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


@pytest.mark.parametrize(("saved", "expected"), [
    (11, 8), (19, 16), (40, 32), (56, 48), (12, 8), (20, 16), (100, 64), (4, 8),
    (32, 32), (8, 8), (64, 64), (0, 32), (-1, 32), ("16", 32), (None, 32), (True, 32),
])
def test_grid_size_not_in_list_moves_to_nearest(saved, expected):
    """목록에 없는 저장값(11-19 잠깐 있던 11·19 등) → 원래 목록에서 가장 가까운 값(같은 거리면 작은 쪽) — 콤보 표시 = 스냅."""
    from mabinogi_addon import config
    assert config.GRID_SIZES == (8, 16, 24, 32, 48, 64)
    data = config._read_local_config()
    data["general"] = {"gridSize": saved}
    config._write_local_config(data)
    assert config.load_grid_size() == expected
