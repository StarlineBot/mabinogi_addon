"""Run the explicit feature checks for this release, not the development suite."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from scripts import run_regressions


def release_tests(root, version):
    plan = json.loads((root / 'packaging/release_checks.json').read_text(encoding='utf-8'))
    if plan.get('version') != version:
        raise ValueError('Update packaging/release_checks.json for the release version')
    paths = plan.get('tests')
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
        raise ValueError('Release checks must name a nonempty list of test files')
    if len(set(paths)) != len(paths):
        raise ValueError('Duplicate release checks')
    for name in paths:
        path = Path(name)
        if (path.is_absolute() or '..' in path.parts or path.suffix != '.py'
                or path.parts[:1] != ('tests',) or path.parts[:2] == ('tests', 'windows')
                or not (root / path).is_file()
                or not (root / path).resolve().is_relative_to((root / 'tests').resolve())):
            raise ValueError(f'Invalid release test file: {name}')
    return paths


def _workers():
    """CI 러너는 2개 그대로. 로컬(QA 컨테이너 등)은 코어 수만큼 — -n 2 고정이면 4코어에서 2배 느림(11-17 측정)."""
    if os.environ.get('GITHUB_ACTIONS'):
        return '2'
    return str(max(2, os.cpu_count() or 2))


def _fingerprint(root, version):
    """같은 코드·자료·버전이면 같은 값. git이 아니거나 실패하면 None(중복 방지 안 함)."""
    try:
        def git(*args):
            return subprocess.run(['git', *args], cwd=root, capture_output=True, check=True).stdout
        h = hashlib.sha256()
        h.update(version.encode())
        h.update(git('rev-parse', 'HEAD^{tree}'))
        h.update(git('diff', 'HEAD', '--binary'))
        h.update(git('ls-files', '--others', '--exclude-standard', '-z'))
        return h.hexdigest()[:16]
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    parser.add_argument('--again', action='store_true',
                        help='같은 코드로 이미 통과했어도 다시 실행(이유가 있을 때만)')
    args = parser.parse_args(argv)
    root = Path.cwd()
    paths = release_tests(root, args.version)
    local = not os.environ.get('GITHUB_ACTIONS')
    stamp = None
    if local:
        key = _fingerprint(root, args.version)
        if key:
            stamp = root / '.qa-stamps' / f'release-{args.version}-{key}.ok'
            if stamp.is_file() and not args.again:
                print(f'Release feature checks: 이미 같은 코드로 통과함({stamp.read_text(encoding="utf-8").strip()}) '
                      '— 다시 돌리지 않음. 꼭 필요하면 --again', flush=True)
                return 0
    print('Release feature checks: ' + ', '.join(paths), flush=True)
    result = run_regressions.main([
        '--diagnostics', 'test-diagnostics/unit', '--case-timeout', '60',
        '--session-timeout', '780', '--', '-n', _workers(), '-q', '--maxfail=3', '--tb=short',
        '-m', 'not windows_integration', '--durations=15', '--junitxml=unit-results.xml', *paths,
    ])
    if result == 0 and stamp is not None:
        from datetime import datetime
        stamp.parent.mkdir(exist_ok=True)
        stamp.write_text(datetime.now().strftime('%Y-%m-%d %H:%M'), encoding='utf-8')
    return result


if __name__ == '__main__':
    raise SystemExit(main())
