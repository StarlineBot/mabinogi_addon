"""QA 검사 시간 장치(사용자 지시 11-17): 전체 테스트 차단 훅, 배포 검사 로컬 병렬·같은 코드 재실행 방지."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import run_release_checks as checks

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / '.claude/hooks/test_guard.py'
_spec = importlib.util.spec_from_file_location('test_guard', HOOK)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


@pytest.mark.parametrize('command', [
    'uv run pytest',
    'uv run pytest -q -n 4',
    'cd /x && QT_QPA_PLATFORM=offscreen uv run pytest -q -n 4 --durations=60 -p no:cacheprovider > log 2>&1',
    'uv run --frozen python -m pytest -n 4 -q -m "not windows_integration"',
    'uv run python -m scripts.run_regressions --diagnostics d -- -n 2 -vv',
    'echo start; pytest -x',
    'uv run --frozen python -m pytest -q -n 4 -p no:cacheprovider --ignore=tests/test_startup_splash.py',
    'uv run pytest -q --ignore tests/test_startup_splash.py',
    'uv run pytest -q --deselect tests/test_a.py::test_one --ignore-glob=tests/windows/*',
    "python3 - <<'EOF'\nprint(1)\nEOF\nuv run pytest -q -n 4",
])
def test_full_runs_are_blocked(command):
    assert guard.full_run(command)


@pytest.mark.parametrize('command', [
    'uv run pytest tests/test_music_buff.py -q',
    'uv run pytest -n 4 tests/test_a.py tests/test_b.py',
    'uv run pytest tests/test_a.py::test_one',
    'uv run pytest -k music',
    'uv run pytest --co -q',
    'uv run pytest tests',
    'uv run pytest -q --ignore=tests/test_x.py tests/test_y.py',
    "python3 - <<'EOF'\nx = ['echo start; pytest -x', 'uv run pytest -q']\nEOF\nuv run pytest -q tests/test_a.py",
    "FULL_REGRESSION_REASON='공통 설정 이전' uv run pytest -n 4",
    'uv run python -m scripts.run_release_checks --version 0.52.0',
    'uv run pytest -n 4 $(python -c "import json;print(1)")',
    'git log --oneline -3',
    'grep -rn pytest pyproject.toml',
])
def test_targeted_or_explained_runs_pass(command):
    assert not guard.full_run(command)


def _hook(payload):
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True)


def test_hook_exit_code_blocks_with_reason_and_ignores_other_tools():
    blocked = _hook({'tool_name': 'Bash', 'tool_input': {'command': 'uv run pytest -q'}})
    assert blocked.returncode == 2 and 'FULL_REGRESSION_REASON' in blocked.stderr
    assert _hook({'tool_name': 'Bash', 'tool_input': {'command': 'uv run pytest tests/test_x.py'}}).returncode == 0
    assert _hook({'tool_name': 'Read', 'tool_input': {'file_path': 'x'}}).returncode == 0
    broken = subprocess.run([sys.executable, str(HOOK)], input='not json', capture_output=True, text=True)
    assert broken.returncode == 0


def test_project_settings_register_the_hook():
    settings = json.loads((ROOT / '.claude/settings.json').read_text(encoding='utf-8'))
    commands = [h['command'] for e in settings['hooks']['PreToolUse'] if e['matcher'] == 'Bash' for h in e['hooks']]
    assert any('test_guard.py' in c for c in commands)


def _plan(root):
    (root / 'tests').mkdir()
    (root / 'tests/test_feature.py').write_text('def test_ok():\n    pass\n', encoding='utf-8')
    (root / 'packaging').mkdir()
    (root / 'packaging/release_checks.json').write_text(
        json.dumps({'version': '0.10.1', 'tests': ['tests/test_feature.py']}), encoding='utf-8')


def _git(root):
    for args in (['init', '-q'], ['add', '-A'],
                 ['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'x']):
        subprocess.run(['git', *args], cwd=root, check=True)


def test_local_uses_all_cores_but_ci_keeps_two(monkeypatch):
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.setattr(checks.os, 'cpu_count', lambda: 4)
    assert checks._workers() == '4'
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    assert checks._workers() == '2'


def test_same_code_passes_once_then_skips_until_changed(tmp_path, monkeypatch):
    _plan(tmp_path)
    (tmp_path / '.gitignore').write_text('.qa-stamps/\n', encoding='utf-8')
    _git(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    calls = []
    monkeypatch.setattr(checks.run_regressions, 'main', lambda args: calls.append(args) or 0)
    assert checks.main(['--version', '0.10.1']) == 0
    assert checks.main(['--version', '0.10.1']) == 0
    assert len(calls) == 1                                   # 같은 코드 — 다시 안 돎
    assert checks.main(['--version', '0.10.1', '--again']) == 0
    assert len(calls) == 2                                   # 명시하면 다시
    (tmp_path / 'tests/test_feature.py').write_text('def test_ok():\n    assert 1\n', encoding='utf-8')
    assert checks.main(['--version', '0.10.1']) == 0
    assert len(calls) == 3                                   # 코드 바뀜 — 다시 돎


def test_failure_leaves_no_stamp_and_ci_never_skips(tmp_path, monkeypatch):
    _plan(tmp_path)
    _git(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    calls = []
    monkeypatch.setattr(checks.run_regressions, 'main', lambda args: calls.append(args) or 1)
    assert checks.main(['--version', '0.10.1']) == 1
    assert not (tmp_path / '.qa-stamps').exists()
    monkeypatch.setattr(checks.run_regressions, 'main', lambda args: calls.append(args) or 0)
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    assert checks.main(['--version', '0.10.1']) == 0
    assert checks.main(['--version', '0.10.1']) == 0
    assert len(calls) == 3 and not (tmp_path / '.qa-stamps').exists()


def test_font_setting_and_untracked_contents_change_the_stamp(tmp_path, monkeypatch):
    _plan(tmp_path)
    (tmp_path / '.gitignore').write_text('.qa-stamps/\n', encoding='utf-8')
    _git(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.delenv('FONTCONFIG_FILE', raising=False)
    calls = []
    monkeypatch.setattr(checks.run_regressions, 'main', lambda args: calls.append(args) or 0)
    assert checks.main(['--version', '0.10.1']) == 0          # 기본 글꼴 통과
    conf = tmp_path.parent / 'fonts-ci.conf'
    conf.write_text('<fontconfig/>', encoding='utf-8')
    monkeypatch.setenv('FONTCONFIG_FILE', str(conf))
    assert checks.main(['--version', '0.10.1']) == 0
    assert len(calls) == 2                                   # CI 글꼴은 다른 검사 — 건너뛰지 않음
    new = tmp_path / 'tests/data.txt'
    new.write_text('a', encoding='utf-8')
    assert checks.main(['--version', '0.10.1']) == 0
    new.write_text('b', encoding='utf-8')                    # 커밋 안 한 파일 내용만 바뀜
    assert checks.main(['--version', '0.10.1']) == 0
    assert len(calls) == 4
