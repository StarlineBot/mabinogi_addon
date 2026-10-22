"""The first traceback survives a later stall, before pytest's final summary."""

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('phase', ['setup', 'call', 'teardown'])
@pytest.mark.parametrize('parallel', [False, True])
def test_first_error_is_visible_before_later_xdist_stall(tmp_path, phase, parallel):
    suite = tmp_path/'suite'
    suite.mkdir()
    marker = 'CI_FIRST_' + phase.upper()
    failure = f'raise RuntimeError({marker!r})'
    source = ('import pytest,threading\n@pytest.fixture\ndef resource():\n'
              f'    {failure if phase == "setup" else "pass"}\n    yield\n'
              f'    {failure if phase == "teardown" else "pass"}\n'
              'def test_00_failure(resource):\n'
              f'    {failure if phase == "call" else "pass"}\n'
              'def test_99_stall():\n    threading.Event().wait()\n')
    (suite/'test_live.py').write_text(source, encoding='utf-8')
    result = subprocess.run([sys.executable, '-m', 'scripts.run_regressions',
        '--diagnostics', str(tmp_path/'diagnostics'), '--case-timeout', '4',
        '--session-timeout', '20', '--stack-interval', '.25', '--',
        *(['-n', '2'] if parallel else []), '-q',
        '--maxfail=3', '--tb=short', str(suite)], cwd=ROOT, capture_output=True,
        text=True, timeout=30)
    output = result.stdout + result.stderr
    assert result.returncode == 124, output
    assert output.count('[ci-first-error]') == 1, output
    assert f'phase={phase}' in output and marker in output
    assert output.index(marker) < output.index('[watchdog] case timeout'), output


def test_maxfail_stops_failing_suite_but_preserves_failure_exit(tmp_path):
    suite = tmp_path/'suite'
    suite.mkdir()
    (suite/'test_fail.py').write_text(
        'import pytest\n@pytest.mark.parametrize("n",range(20))\n'
        'def test_bad(n): raise RuntimeError("CI_FAIL_FAST")\n', encoding='utf-8')
    result = subprocess.run([sys.executable, '-m', 'scripts.run_regressions',
        '--diagnostics', str(tmp_path/'diagnostics'), '--case-timeout', '15',
        '--session-timeout', '25', '--', '-n', '2', '-q', '--maxfail=3',
        '--tb=short', str(suite)], cwd=ROOT, capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    assert result.returncode in (1, 2), output
    assert output.count('[ci-first-error]') == 3, output
    assert '20 failed' not in output and 'CI_FAIL_FAST' in output


def test_error_payload_is_bounded_deduplicated_and_keeps_exception_tail():
    from test_support.live_errors import LiveErrors

    class Console:
        def __init__(self):
            self.chunks = []
        def send(self, data):
            self.chunks.append(data)
        def flush(self):
            pass

    console = Console()
    reporter = LiveErrors(console)
    body = 'header\n' + 'x'*100000 + '\nROOT_CAUSE_AT_END'
    reporter.report('node', 'setup', body)
    reporter.report('node', 'setup', body)
    for number in range(5):
        reporter.report(f'node{number}', 'call', 'failure')
    output = b''.join(console.chunks)
    assert output.count(b'[ci-first-error]') == 3
    assert b'header' in output and b'ROOT_CAUSE_AT_END' in output
    assert b'[traceback truncated]' in output and len(output) < 35*1024
    assert all(len(chunk) <= 8192 for chunk in console.chunks)


def test_collection_and_internal_errors_use_the_same_immediate_channel(monkeypatch):
    from types import SimpleNamespace
    from test_support import progress

    calls = []
    monkeypatch.setattr(progress, '_live_errors', SimpleNamespace(report=lambda *args: calls.append(args)))
    progress.pytest_collectreport(SimpleNamespace(failed=True, nodeid='test_import.py', longrepr='IMPORT_FAILURE'))
    progress.pytest_collectreport(SimpleNamespace(failed=False))
    progress.pytest_internalerror('INTERNAL_FAILURE', None)
    assert calls == [('test_import.py', 'collection', 'IMPORT_FAILURE'),
                     ('pytest', 'internal', 'INTERNAL_FAILURE')]


def test_traceback_is_sent_before_journal_io(monkeypatch):
    from types import SimpleNamespace
    from test_support import progress

    calls = []
    def journal(**kw):
        calls.append('journal')
        raise OSError('journal unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(progress, '_live_errors', SimpleNamespace(report=lambda *args: calls.append('traceback')))
        patch.setattr(progress, '_state', SimpleNamespace(emit=journal))
        with pytest.raises(OSError, match='journal unavailable'):
            progress.pytest_runtest_logreport(SimpleNamespace(
                failed=True, nodeid='test_first.py', when='setup', longrepr='FIRST_FAILURE', outcome='failed'))
    assert calls == ['traceback', 'journal']
