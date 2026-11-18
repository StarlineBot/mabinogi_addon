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


ANSWER_HOOK = ROOT / '.claude/hooks/answer_guard.py'
_aspec = importlib.util.spec_from_file_location('answer_guard', ANSWER_HOOK)
answer = importlib.util.module_from_spec(_aspec)
_aspec.loader.exec_module(answer)


def _transcript(tmp_path, reply):
    rows = [
        {'type': 'user', 'message': {'role': 'user', 'content': '권한 되나?'}},
        {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'tool_use', 'name': 'Bash'}]}},
        {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'content': 'ok'}]}},
        {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': reply}]}},
    ]
    path = tmp_path / 't.jsonl'
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
    return path


def _stop(path, active=False):
    payload = {'transcript_path': str(path), 'stop_hook_active': active}
    return subprocess.run([sys.executable, str(ANSWER_HOOK)], input=json.dumps(payload), capture_output=True, text=True)


@pytest.mark.parametrize('reply', ['권한은 확인 못 했습니다.', '될지는 해 봐야 압니다.', '그건 모르겠습니다.',
                                   '실행 권한이 있는지는 확인하지 못했습니다.', '아직 확인 전입니다.'])
def test_unverified_answers_are_sent_back(tmp_path, reply):
    result = _stop(_transcript(tmp_path, reply))
    assert result.returncode == 2 and '된다' in result.stderr


@pytest.mark.parametrize('reply', ['됩니다. 후보 #248 성공.', "안 된다: 런북 파일이 이 저장소에 없음", '`확인 못 함` 문구는 코드 예시',
                                   '답에 "확인 못 했다", "모르겠다" 같은 표현이 있으면 막습니다.',
                                   '해석입니다.\n> 정확히는 모르겠지만 유튜브만 봤어요.\n결론: 애드온이 원인.'])
def test_concluded_answers_pass(tmp_path, reply):
    assert _stop(_transcript(tmp_path, reply)).returncode == 0


def test_answer_guard_blocks_only_once_and_never_breaks(tmp_path):
    assert _stop(_transcript(tmp_path, '확인 못 했습니다'), active=True).returncode == 0
    broken = subprocess.run([sys.executable, str(ANSWER_HOOK)], input='{}', capture_output=True, text=True)
    assert broken.returncode == 0
    settings = json.loads((ROOT / '.claude/settings.json').read_text(encoding='utf-8'))
    assert any('answer_guard.py' in h['command'] for e in settings['hooks']['Stop'] for h in e['hooks'])
