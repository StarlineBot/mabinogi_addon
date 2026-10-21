"""Opt-in regression reproducer: a transient journal replace must not abort pytest."""
from types import SimpleNamespace

from test_support import progress


def _journal(tmp_path, monkeypatch):
    monkeypatch.setenv('MABINOGI_TEST_DIAGNOSTICS', str(tmp_path))
    monkeypatch.setattr(progress.Journal, 'arm', lambda self: None)
    journal = progress.Journal(SimpleNamespace())
    monkeypatch.setattr(progress, '_state', journal)
    return journal


def test_report_without_contention_updates_journal(tmp_path, monkeypatch):
    journal = _journal(tmp_path, monkeypatch)
    try:
        progress.pytest_runtest_logreport(SimpleNamespace(outcome='passed'))
        assert '"outcome": "passed"' in journal.path.read_text(encoding='utf-8')
    finally:
        journal.raw.close()


def test_one_transient_replace_denial_does_not_escape_pytest_hook(tmp_path, monkeypatch):
    journal = _journal(tmp_path, monkeypatch)
    original = progress._REPLACE
    attempts = []

    def transient(source, target):
        attempts.append((source, target))
        if len(attempts) == 1:
            raise PermissionError(13, 'synthetic transient Windows journal replace denial')
        return original(source, target)

    monkeypatch.setattr(progress, '_REPLACE', transient)
    try:
        progress.pytest_runtest_logreport(SimpleNamespace(outcome='passed'))
        assert len(attempts) >= 2
        assert '"outcome": "passed"' in journal.path.read_text(encoding='utf-8')
    finally:
        journal.raw.close()
