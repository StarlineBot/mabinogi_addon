"""Inspect actual first-show header fonts without repairing or resetting them.

Run with PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest
scripts/qa_feature_header_initial_font_20261020.py -q -s --tb=short.
"""

import json

from PySide6.QtGui import QFontInfo

from tests.conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: F401
from tests.test_navigation import window  # noqa: F401
from mabinogi_addon.ui.widgets import FeatureHeader


def observe(window):
    w, app = window
    observed = {}
    for key in ("dorcha", "custom"):
        w._open_setup_feature(key)
        app.processEvents()
        panel = w._combat_pages[key].widget()
        header = next(h for h in panel.findChildren(FeatureHeader) if h.isVisible())
        observed[key] = {}
        for name, widget in (("header", header), ("title", header.title),
                             ("description", header.description)):
            font = widget.font()
            actual = QFontInfo(font)
            observed[key][name] = {
                "font": font.toString(), "family": actual.family(),
                "pixels": actual.pixelSize(), "points": actual.pointSizeF(),
                "weight": actual.weight(), "height": widget.height(),
                "metrics_height": widget.fontMetrics().height(),
            }
    print("FIRST_SHOW_HEADER_FONTS " + json.dumps(observed, ensure_ascii=False))
    return observed


def test_first_show_resource_and_custom_titles_have_the_same_font(window):
    observed = observe(window)
    for key in ("pixels", "family", "weight"):
        assert observed["dorcha"]["title"][key] == observed["custom"]["title"][key]


def test_help_button_does_not_change_single_line_title_row_height(window):
    observed = observe(window)
    assert observed["dorcha"]["title"]["height"] == observed["custom"]["title"]["height"]
