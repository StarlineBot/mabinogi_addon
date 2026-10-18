"""Group margins must not turn the output preview into a page minimum width."""

from copy import deepcopy
import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QWidget
from test_navigation import window
from mabinogi_addon import config


@pytest.mark.parametrize("font_size", [12, 20])
@pytest.mark.parametrize("scale", [100, 300])
def test_preview_fits_group_not_page_width(window, monkeypatch, font_size, scale, tmp_path):
    w, app = window
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen, "availableGeometry", lambda self: QRect(0, 0, 900, 1000))
    monkeypatch.setattr(screen, "geometry", lambda self: QRect(0, 0, 900, 1000))
    tab = w.stat_bars_tab
    for widget in w.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(font_size)
        widget.setFont(font)
    tab.scale_spin.setValue(scale)
    saved = deepcopy(config._read_local_config())
    preview = tab.display_preview
    group_layout = preview.parentWidget().layout()
    margins = group_layout.contentsMargins()
    w._open_setup_feature("stat_bars")
    scroll = w._combat_pages["stat_bars"]
    for margin in (28, 11, 28):
        group_layout.setContentsMargins(margin, margins.top(), margin, margins.bottom())
        for diagnostics in (False, True, False):
            tab.diagnostics_btn.setChecked(diagnostics)
            for _ in range(12):
                app.processEvents()
            assert scroll.horizontalScrollBar().maximum() == 0
            assert preview.width() <= group_layout.contentsRect().width()
            body = preview.widget()
            assert body.width() == body.sizeHint().width()
            if scale == 300:
                assert preview.horizontalScrollBar().maximum() > 0
            assert all(bar._scale == scale / 100 for bar in tab._preview_bars.values())
    assert config._read_local_config() == saved
    assert w.grab().save(str(tmp_path / f"stat-preview-{font_size}-{scale}.png"))
