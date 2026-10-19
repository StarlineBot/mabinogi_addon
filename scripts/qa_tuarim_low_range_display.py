"""Historical command compatibility; authoritative regressions live in test_support."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from test_support.regressions.tuarim_low_range import *  # noqa: F403
