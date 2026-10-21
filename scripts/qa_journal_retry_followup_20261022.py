"""Opt-in QA for retry limits and captured fallback diagnostics."""
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from test_support import progress


def test_seventh_transient_denial_recovers_without_false_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('MABINOGI_TEST_DIAGNOSTICS', str(tmp_path))
    monkeypatch.setattr(progress.Journal, 'arm', lambda self: None)
    journal = progress.Journal(SimpleNamespace())
    original = progress._REPLACE
    calls = []

    def replace(source, target):
        calls.append(1)
        if len(calls) < 8:
            raise PermissionError(13, 'synthetic sharing denial')
        return original(source, target)

    monkeypatch.setattr(progress, '_REPLACE', replace)
    monkeypatch.setattr(progress, '_state', journal)
    try:
        progress.pytest_runtest_logreport(SimpleNamespace(outcome='passed'))
        assert len(calls) == 8 and journal.failed is None
        assert json.loads(journal.path.read_text(encoding='utf-8'))['outcome'] == 'passed'
        assert not list(tmp_path.glob('*.error'))
    finally:
        journal.raw.close()


@pytest.mark.parametrize('capture_enabled', [True, False])
def test_no_error_file_fallback_never_publishes_success(tmp_path, capture_enabled):
    suite = tmp_path / 'suite'
    suite.mkdir()
    (suite / 'test_blocked.py').write_text(
        'import threading\nfrom test_support import progress\n'
        'def test_blocked():\n'
        '    def denied(*a, **k): raise PermissionError(13, "synthetic denial")\n'
        '    progress._REPLACE = denied\n'
        '    progress._OPEN = denied\n'
        '    progress._state.emit(outcome="passed")\n'
        '    threading.Event().wait()\n', encoding='utf-8')
    diagnostics = tmp_path / 'diagnostics'
    command = [sys.executable, '-m', 'scripts.run_regressions',
               '--diagnostics', str(diagnostics), '--case-timeout', '3',
               '--session-timeout', '15', '--stack-interval', '.25', '--', '-q']
    if not capture_enabled:
        command.append('-s')
    command.append(str(suite))
    start = time.monotonic()
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=20)
    seconds = time.monotonic() - start
    assert result.returncode != 0, result.stdout + result.stderr
    assert not list(diagnostics.glob('run-*/*.error'))
    records = [json.loads(p.read_text(encoding='utf-8'))
               for p in diagnostics.glob('run-*/failure.json')]
    assert records
    print('FALLBACK_EVIDENCE', json.dumps(dict(capture=capture_enabled,
          code=result.returncode, seconds=round(seconds, 3), failure=records)))
