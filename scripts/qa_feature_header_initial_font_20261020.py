"""Inspect actual first-show header fonts without repairing or resetting them.

Run with PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest
scripts/qa_feature_header_initial_font_20261020.py -q -s --tb=short.
"""

import json


from tests.conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: F401
from tests.test_navigation import window  # noqa: F401
from test_support.regressions.feature_header import initial_header_metrics


def observe(window):
    observed = initial_header_metrics(window)
    print("FIRST_SHOW_HEADER_FONTS " + json.dumps(observed, ensure_ascii=False))
    return observed


def test_first_show_resource_and_custom_titles_have_the_same_font(window):
    observed = observe(window)
    for key in ("pixels", "family", "weight"):
        assert observed["dorcha"]["title"][key] == observed["custom"]["title"][key]


def test_help_button_does_not_change_single_line_title_row_height(window):
    observed = observe(window)
    assert observed["dorcha"]["title"]["height"] == observed["custom"]["title"]["height"]
