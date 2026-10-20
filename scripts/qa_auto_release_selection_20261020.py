"""A stale artifact must not hide the same run's successful latest candidate.

PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest
scripts/qa_auto_release_selection_20261020.py -q --tb=short --show-capture=no
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_release_candidate import (  # noqa: E402,F401
    automation, bundle,
    test_latest_valid_attempt_is_selectable_with_retained_prior_attempt,
)

# Historical QA command retained; the four cases now live in the regular suite.
