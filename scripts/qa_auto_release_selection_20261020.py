"""A stale artifact must not hide the same run's successful latest candidate.

PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest
scripts/qa_auto_release_selection_20261020.py -q --tb=short --show-capture=no
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_release_candidate import automation, bundle, REPO, SHA  # noqa: E402,F401
from scripts import release_automation as a  # noqa: E402


@pytest.mark.parametrize('candidate_run', ['', '123'])
@pytest.mark.parametrize('old_first', [False, True])
def test_latest_valid_attempt_is_selectable_with_retained_prior_attempt(
        automation, candidate_run, old_first):
    env = automation
    env['prepare']('verify-only')
    old = deepcopy(env['artifacts'][123][0])
    old.update(id=457, name='verified-windows-123-1')
    old_folder = env['root'] / 'prior-attempt'
    shutil.copytree(env['folder'], old_folder)
    manifest = deepcopy(env['manifest'])
    manifest['run_attempt'] = 1
    manifest['authorization']['run_attempt'] = 1
    (old_folder / 'candidate.json').write_text(json.dumps(manifest), encoding='utf-8')
    env['sources'][457] = old_folder
    if old_first:
        env['artifacts'][123].insert(0, old)
    else:
        env['artifacts'][123].append(old)
    try:
        selected = a.select_existing(REPO, SHA, '0.6.0', candidate_run=candidate_run)
    finally:
        assert not any(event[0] in ('tag', 'release') for event in env['events'])
    assert selected['context']['run_id'] == 123
    assert selected['context']['run_attempt'] == 2
    assert selected['context']['artifact_id'] == 456
    assert not any(event[0] in ('tag', 'release') for event in env['events'])
