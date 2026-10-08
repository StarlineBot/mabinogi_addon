"""DPI 논리→물리 좌표 변환 테스트."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from mabinogi_addon.ui import dpi


def test_to_physical_scales_by_dpr(monkeypatch) -> None:
    monkeypatch.setattr(dpi, "screen_scale", lambda: 1.5)
    assert dpi.to_physical({"x": 100, "y": 200, "w": 320, "h": 90}) == (
        150, 300, 480, 135
    )


def test_to_physical_noop_at_100(monkeypatch) -> None:
    monkeypatch.setattr(dpi, "screen_scale", lambda: 1.0)
    r = {"x": 10, "y": 20, "w": 30, "h": 40}
    assert dpi.to_physical(r) == (10, 20, 30, 40)
