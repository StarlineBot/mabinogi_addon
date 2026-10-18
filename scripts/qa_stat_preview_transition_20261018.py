"""Repeated real-page scale and visibility changes must not reintroduce fixed width."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_navigation import window  # noqa: E402,F401
from mabinogi_addon import config  # noqa: E402


@pytest.mark.parametrize("font_size", [12, 20])
@pytest.mark.parametrize("drain_each_control", [False, True])
def test_preview_repeated_scale_group_and_page_changes(window, font_size, tmp_path, drain_each_control):
    w, app = window
    tab = w.stat_bars_tab
    for widget in w.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(font_size)
        widget.setFont(font)
    preview = tab.display_preview
    group_layout = preview.parentWidget().layout()
    timers = set(w.findChildren(QTimer))
    w._open_setup_feature("stat_bars")
    for _ in range(12):
        app.processEvents()
    for cycle in range(3):
        for scale in (300, 50, 150):
            tab.scale_spin.setValue(scale)
            if drain_each_control:
                for _ in range(12):
                    app.processEvents()
            for sid, check in tab._show_checks.items():
                check.setChecked(sid == "hp" or scale != 50)
                if drain_each_control:
                    for _ in range(12):
                        app.processEvents()
            tab.diagnostics_btn.setChecked(cycle % 2 == 0)
            before = deepcopy(config._read_local_config())
            w._open_setup_feature("memo")
            w._open_setup_feature("stat_bars")
            for _ in range(12):
                app.processEvents()
            page = w._combat_pages["stat_bars"]
            observed = preview.widget().width()
            expected = preview.widget().sizeHint().width()
            detail = {
                "cycle": cycle, "scale": scale, "body": observed,
                "expected": expected, "viewport": preview.viewport().width(),
                "range": preview.horizontalScrollBar().maximum(),
            }
            if observed != expected:
                assert w.grab().save(str(tmp_path / f"preview-failure-{font_size}.png"))
                # Diagnostic-only refresh after recording the failed final state.
                tab._resize_display_preview()
                for _ in range(12):
                    app.processEvents()
                detail["manual_fit_body"] = preview.widget().width()
                detail["manual_fit_range"] = preview.horizontalScrollBar().maximum()
            assert page.horizontalScrollBar().maximum() == 0
            assert preview.width() <= group_layout.contentsRect().width()
            assert observed == expected, repr(detail)
            assert preview.viewport().height() >= preview.widget().height()
            assert all(bar._scale == scale / 100 for bar in tab._preview_bars.values())
            overflow = max(0, preview.widget().width() - preview.viewport().width())
            assert preview.horizontalScrollBar().maximum() == overflow
            if scale == 300:
                assert overflow > 0
            elif scale == 50:
                assert overflow == 0
            assert config._read_local_config() == before
            assert set(w.findChildren(QTimer)) == timers
    assert w.grab().save(str(tmp_path / f"preview-history-{font_size}.png"))
