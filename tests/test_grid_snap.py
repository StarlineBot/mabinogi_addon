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
