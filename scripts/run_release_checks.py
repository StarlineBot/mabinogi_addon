"""Run the explicit feature checks for this release, not the development suite."""

import argparse
import json
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


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    args = parser.parse_args(argv)
    paths = release_tests(Path.cwd(), args.version)
    print('Release feature checks: ' + ', '.join(paths), flush=True)
    return run_regressions.main([
        '--diagnostics', 'test-diagnostics/unit', '--case-timeout', '60',
        '--session-timeout', '150', '--', '-n', '2', '-q', '--maxfail=3', '--tb=short',
        '-m', 'not windows_integration', '--durations=15', '--junitxml=unit-results.xml', *paths,
    ])


if __name__ == '__main__':
    raise SystemExit(main())
