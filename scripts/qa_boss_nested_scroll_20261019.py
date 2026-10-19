"""Preserve the three existing release-gate failures after nested boss tabs."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_navigation import window  # noqa: E402,F401
from test_interaction_polish import test_eight_actual_pages_render_without_overflow_or_writes as check_pages  # noqa: E402
from test_wrapping_controls import test_windows_minimum_widths_wrap_and_restore_without_state_changes as check_wrap  # noqa: E402


@pytest.mark.parametrize("dark", [False, True])
def test_original_page_gate_at_twenty_pixels(window, monkeypatch, tmp_path, dark):
    check_pages(window, 20, dark, tmp_path, monkeypatch)


def test_original_wrapping_gate_at_twenty_pixels(window, tmp_path):
    check_wrap(window, "boss", tmp_path)
