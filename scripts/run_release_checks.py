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
        for name in git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0'):
            if name:                                    # 커밋 안 한 새 파일은 이름뿐 아니라 내용까지
                h.update(name)
                h.update((root / name.decode('utf-8')).read_bytes())
        # 글꼴 조건이 다르면 다른 검사(11-17 QA: 기본 글꼴 통과 기록으로 CI 글꼴 실행이 건너뛰어짐 — #243은 글꼴 차이로 실패)
        font = os.environ.get('FONTCONFIG_FILE', '')
        h.update(font.encode())
        if font and Path(font).is_file():
            h.update(Path(font).read_bytes())
        return h.hexdigest()[:16]
    except (OSError, subprocess.CalledProcessError):
        return None


def _has_noto_cjk() -> bool:
    """CI가 설치하는 한글 글꼴(Noto Sans CJK)이 있는지. fc-list가 없으면(맥 등) 확인하지 않음."""
    try:
        out = subprocess.run(['fc-list', ':', 'family'], capture_output=True, text=True, check=False, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return 'Noto Sans CJK' in out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    parser.add_argument('--again', action='store_true',
                        help='같은 코드로 이미 통과했어도 다시 실행(이유가 있을 때만)')
    args = parser.parse_args(argv)
    root = Path.cwd()
    paths = release_tests(root, args.version)
    local = not os.environ.get('GITHUB_ACTIONS')
    ci_fonts = root / 'packaging' / 'fonts-ci.conf'
    if local and not os.environ.get('FONTCONFIG_FILE') and ci_fonts.is_file():
        # 로컬도 CI와 같은 글꼴로(packaging/fonts-ci.conf) — 글꼴 폭 차이로 로컬 통과·CI 실패가 나지 않게(0.52.0 #243)
        os.environ['FONTCONFIG_FILE'] = str(ci_fonts)
        print(f'Release feature checks: CI 글꼴 설정 자동 적용({ci_fonts.relative_to(root)})', flush=True)
        if not _has_noto_cjk():
            print('경고: fonts-noto-cjk가 없어 CI와 한글 글꼴이 달라요 — sudo apt-get install -y fonts-noto-cjk', flush=True)
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
