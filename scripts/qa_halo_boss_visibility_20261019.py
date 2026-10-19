"""Compatibility entry point for the live battle visibility regression."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: F401,E402
from test_halo_live import (  # noqa: F401,E402
    window,
    test_confirmed_battle_keeps_outputs_while_timer_advances_without_boss_bar,
)
