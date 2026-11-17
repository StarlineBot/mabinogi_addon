"""Claude Code PreToolUse 훅 — 이유 없는 전체 테스트(약 14분) 실행을 막는다.

사용자 지시(11-17): 지키지 않는 규칙 대신 지킬 수밖에 없는 장치로. 대상을 지정하지 않은 pytest
(= 전체 5천여 개)는 막고, 정말 필요하면 명령 앞에 FULL_REGRESSION_REASON='이유'를 붙여야 실행된다.
테스트 파일·폴더·노드(::)·-k·수집만(--co)을 지정한 실행, 배포 검사 스크립트는 그대로 통과.
훅이 실패하면(입력 형식이 다름 등) 막지 않는다 — 작업을 멈추게 하지 않는 쪽이 안전.
"""
from __future__ import annotations

import json
import re
import shlex
import sys

_RUNNERS = ('pytest', 'py.test')
_TARGET_FLAGS = {'-k', '--co', '--collect-only', '--test-inventory', '--regression-group', '--lf', '--last-failed',
                 '-h', '--help', '--version', '--fixtures', '--markers'}


_WRAPPERS = {'uv', 'run', 'python', 'python3', 'timeout', 'nice', 'exec', 'time', 'env', 'xvfb-run'}


def _wrapper(word: str) -> bool:
    name = word.rsplit('/', 1)[-1]
    return (name in _WRAPPERS or name.startswith('python3') or word.startswith('-')
            or ('=' in word and not word.startswith('-')) or re.fullmatch(r'\d+[smh]?', word) is not None)


def _is_target(arg: str) -> bool:
    return ('tests/' in arg or 'tests\\' in arg or arg.endswith('.py') or '::' in arg
            or arg.startswith('test_support') or arg in ('tests', 'tests/', './tests'))


def full_run(command: str) -> bool:
    if 'FULL_REGRESSION_REASON=' in command:
        return False
    for part in re.split(r'&&|\|\||;|\|', command):
        try:
            words = shlex.split(part)
        except ValueError:
            continue
        runner = None
        for i, w in enumerate(words):
            name = w.rsplit('/', 1)[-1]
            if name in _RUNNERS or w.endswith('scripts.run_regressions'):
                runner = i + 1
                break
            if w == '-m' and i + 1 < len(words) and (words[i + 1] in _RUNNERS
                                                    or words[i + 1].endswith('run_regressions')):
                runner = i + 2
                break
            if not _wrapper(w):
                break  # 다른 프로그램(grep·git 등)의 인자에 나온 'pytest'는 실행이 아님
        if runner is None:
            continue
        args = words[runner:]
        if any('$(' in a or '`' in a for a in args) or '$(' in part or '`' in part:
            continue  # 목록을 명령 치환으로 넘김 — 판단 불가, 막지 않음
        if any(_is_target(a) or a.split('=', 1)[0] in _TARGET_FLAGS for a in args):
            continue
        return True
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if data.get('tool_name') != 'Bash':
            return 0
        command = data.get('tool_input', {}).get('command', '')
    except Exception:
        return 0
    if not full_run(command):
        return 0
    print(
        '전체 테스트(약 14분) 실행이 막혔습니다 — 프로젝트 훅 .claude/hooks/test_guard.py.\n'
        '보통은 이렇게 하세요: ① 바뀐 파일의 테스트만 `uv run pytest -n 4 tests/test_xxx.py` '
        '② 배포 검사 `uv run python -m scripts.run_release_checks --version X.Y.Z` (로컬은 코어 전부, 같은 코드면 다시 안 돎).\n'
        '공통 설정·공유 판독/캡처·스레드 수명·패키징 등 넓은 변경이라 전체가 꼭 필요하면 '
        "명령 앞에 FULL_REGRESSION_REASON='이유' 를 붙이고, 배포 검사와 동시에(백그라운드) 돌리세요. "
        '시작 전에 사용자에게 예상 시간(약 14분)을 알리세요.',
        file=sys.stderr,
    )
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
