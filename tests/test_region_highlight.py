"""영역 하이라이트 오버레이 스모크 테스트(offscreen)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui.region_highlight import RegionHighlight


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_flash_sets_rect_and_shows() -> None:
    _app()
    hl = RegionHighlight()
    hl.flash(100, 200, 320, 90, "버프 영역 확인", "아이콘 + 남은시간 확인", msec=50)
    assert not hl._rect.isNull()
    assert hl._rect.width() == 320
    assert hl._rect.height() == 90
    assert hl.isVisible()
    hl.close()


def test_flash_is_click_through() -> None:
    _app()
    hl = RegionHighlight()
    from PySide6.QtCore import Qt

    assert hl.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert hl.windowFlags() & Qt.WindowType.WindowTransparentForInput
    hl.close()
