"""Independent QA: real local Git boundaries; no external publication or device IO."""

import ast
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts import release_candidate as candidate


ROOT = Path(__file__).resolve().parents[4]
ORIGINAL = Path(os.environ.get('QA_GIT_ROOT', ROOT))
BASE = '6126026652e11ae039a065a6631507a699247352'
REPO = 'qa/local'
VERSION = '0.6.0'


def git(root, *args):
    return subprocess.check_output(
        ['git', '-c', 'user.name=Independent QA', '-c', 'user.email=qa@example.invalid', *args],
        cwd=root, text=True, stderr=subprocess.PIPE,
    ).strip()


@pytest.fixture
def source(tmp_path, monkeypatch):
    root, remote = tmp_path/'source', tmp_path/'remote.git'
    root.mkdir()
    git(tmp_path, 'init', '--bare', '--initial-branch=main', str(remote))
    git(root, 'init', '--initial-branch=main')
    for name in ('src/product.py', 'tests/test_product.py', '.github/workflows/windows.yml',
                 'packaging/build.py', 'docs/qa/assets/sample.png', 'docs/qa/report.md', 'uv.lock'):
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('baseline\n', encoding='utf-8')
    notes = root/'src/mabinogi_addon/assets/release_notes.md'
    notes.parent.mkdir(parents=True)
    notes.write_text(f'## v{VERSION}\n\nVerified notes\n', encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'QA fixture')
    sha = git(root, 'rev-parse', 'HEAD')
    git(root, 'remote', 'add', 'origin', str(remote))
    git(root, 'tag', 'v'+VERSION)
    git(root, 'push', 'origin', 'main', '--tags')
    monkeypatch.chdir(root)
    monkeypatch.setenv('GITHUB_REPOSITORY', REPO)
    now = candidate.utcnow()
    run = dict(id=101, repository=dict(full_name=REPO), head_sha=sha, run_attempt=1,
               workflow_id=22, path=candidate.WORKFLOW, head_branch='main',
               event='workflow_dispatch', status='completed', conclusion='success')
    jobs = [dict(name='validate', conclusion='success', steps=[
        dict(name=name, conclusion='success') for name in candidate.REQUIRED])]
    artifact = dict(id=44, name='verified-windows-101-1', expired=False,
                    size_in_bytes=1024, workflow_run=dict(id=101, head_sha=sha),
                    expires_at=(now+candidate.TTL).isoformat())
    monkeypatch.setattr(candidate, 'api', lambda path: dict(id=22) if path.endswith('windows.yml') else run)
    monkeypatch.setattr(candidate, 'pages', lambda path, field: jobs if field == 'jobs' else [artifact])
    return root, sha, now


@pytest.mark.parametrize('name,allowed', [
    ('docs/qa/report.md', True), ('src/product.py', False),
    ('tests/test_product.py', False), ('.github/workflows/windows.yml', False),
    ('packaging/build.py', False), ('docs/qa/assets/sample.png', False), ('uv.lock', False),
])
def test_real_remote_changes_after_validation(source, name, allowed):
    root, sha, _ = source
    baseline = candidate.gate(REPO, 101, 1, sha, VERSION)
    (root/name).write_text('changed after validation\n', encoding='utf-8')
    git(root, 'add', name)
    git(root, 'commit', '-m', 'Changed input')
    git(root, 'push', 'origin', 'main')
    assert git(root, 'rev-parse', 'HEAD') != sha
    if allowed:
        assert candidate.gate(REPO, 101, 1, sha, VERSION) == baseline
    else:
        with pytest.raises(ValueError, match='inputs changed'):
            candidate.gate(REPO, 101, 1, sha, VERSION)


def test_real_git_seal_bytes_and_expiry(source, tmp_path):
    root, sha, now = source
    (root/'dist').mkdir()
    original = b'QA-only fake PE boundary\x00\xff'
    (root/'dist/mabinogi-addon.exe').write_bytes(original)
    for name in ('unit-results.xml', 'windows-results.xml'):
        (root/name).write_text('<testsuite tests="2" skipped="0" failures="0" errors="0"/>', encoding='utf-8')
    folder = tmp_path/'candidate'
    manifest = candidate.seal(root, folder, sha, VERSION, 101, 1, REPO,
                              now=now, read_version=lambda _: VERSION)
    context = candidate.gate(REPO, 101, 1, sha, VERSION)
    assert candidate.verify_bundle(folder, context, now=now) == manifest
    assert (folder/'mabinogi-addon.exe').read_bytes() == original
    metadata = json.loads((folder/'version.json').read_text(encoding='utf-8'))
    assert metadata['sha256'] == candidate.digest(folder/'mabinogi-addon.exe')
    with pytest.raises(ValueError, match='expired'):
        candidate.verify_bundle(folder, context, now=now+timedelta(days=1))
    (folder/'mabinogi-addon.exe').write_bytes(original+b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        candidate.verify_bundle(folder, context, now=now)


@pytest.mark.parametrize('old,new', [
    ('scripts/qa_tuarim_low_range_display.py', 'test_support/regressions/tuarim_low_range.py'),
    ('scripts/qa_dorcha_restart_after_move.py', 'test_support/regressions/dorcha_restart.py'),
    ('scripts/qa_custom_autosave_import_reset.py', 'test_support/regressions/custom_replacement.py'),
])
def test_moved_functions_keep_original_assertions_and_fixtures(old, new):
    before = git(ORIGINAL, 'show', BASE+':'+old)
    after = (ROOT/new).read_text(encoding='utf-8')

    def definitions(text):
        return {node.name: ast.dump(node, include_attributes=False)
                for node in ast.parse(text).body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

    expected = definitions(before)
    assert expected
    assert definitions(after) == expected
