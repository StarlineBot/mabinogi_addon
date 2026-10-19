"""Compatibility entry point; QA cases now live in the regular regression suite."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: F401,E402
from test_halo_presentation import (  # noqa: F401,E402
    window,
    test_warning_edit_sample_survives_normal_tick_without_boss,
    test_synced_countdown_remains_visible_outside_settings,
)
