"""오버레이 일시정지(사냥 안 할 때 잠깐 끄기) 동작 테스트."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui.buff_controller import BuffController
from mabinogi_addon.ui.overlay import BuffOverlay


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_paused_hides_overlay_and_blocks_alert() -> None:
    _app()
    overlay = BuffOverlay()
    fired: list = []
    ctrl = BuffController(
        overlay, catalog={}, show_duration={}, on_alert=fired.append
    )
    ctrl._game_active = True
    ctrl._items = [object()]  # 표시할 항목이 있는 상태로 가정

    ctrl.set_paused(True)
    assert not overlay.isVisible()  # 일시정지 → 숨김
    ctrl._on_alerted(["x"])
    assert fired == []  # 일시정지 중엔 알림 억제

    ctrl.set_paused(False)
    ctrl._on_alerted(["x"])
    assert fired == [["x"]]  # 재개 후엔 알림 전달(buff_ids 리스트 그대로)


def test_paused_overrides_foreground() -> None:
    _app()
    overlay = BuffOverlay()
    ctrl = BuffController(overlay, catalog={}, show_duration={})
    ctrl.set_paused(True)
    # 게임이 포그라운드로 바뀌어도 일시정지 중엔 계속 숨김
    ctrl._on_foreground_changed(True, False)
    assert not overlay.isVisible()
