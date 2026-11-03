import json
from pathlib import Path

import pytest

from scripts import run_release_checks as checks


def plan(root, tests=None, version='0.10.1'):
    (root / 'packaging').mkdir()
    (root / 'tests').mkdir()
    (root / 'tests/test_feature.py').write_text('def test_ok(): pass\n', encoding='utf-8')
    (root / 'packaging/release_checks.json').write_text(json.dumps({
        'version': version, 'tests': tests if tests is not None else ['tests/test_feature.py'],
    }), encoding='utf-8')


@pytest.mark.parametrize('tests', [[], ['tests/missing.py'], ['../outside.py'], ['-q'],
                                  ['tests/test_feature.py'] * 2, ['tests/windows/test_native.py'],
                                  [1], 'tests'])
def test_invalid_plan_fails_instead_of_collecting_whole_suite(tmp_path, tests):
    plan(tmp_path, tests)
    with pytest.raises(ValueError):
        checks.release_tests(tmp_path, '0.10.1')


def test_new_version_requires_its_own_explicit_plan(tmp_path):
    plan(tmp_path)
    with pytest.raises(ValueError, match='release version'):
        checks.release_tests(tmp_path, '0.11.0')


@pytest.mark.parametrize('result', [0, 1, 124])
def test_runner_keeps_result_and_never_falls_back_to_all_tests(tmp_path, monkeypatch, result):
    plan(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls = []
    def run(args):
        calls.append(args)
        return result
    monkeypatch.setattr(checks.run_regressions, 'main', run)
    assert checks.main(['--version', '0.10.1']) == result
    assert len(calls) == 1 and calls[0][-1] == 'tests/test_feature.py'
    assert '--session-timeout' in calls[0] and '780' in calls[0]
    assert '--case-timeout' in calls[0] and '60' in calls[0]
    assert '-n' in calls[0] and '2' in calls[0] and '--maxfail=3' in calls[0]
    assert '--junitxml=unit-results.xml' in calls[0]


def test_current_plan_maps_every_selected_file_to_changed_code_or_shared_contract():
    root = Path(__file__).resolve().parents[1]
    notes = (root / 'src/mabinogi_addon/assets/release_notes.md').read_text(encoding='utf-8')
    version = notes.splitlines()[0].removeprefix('## v')
    paths = checks.release_tests(root, version)
    plan = json.loads((root / 'packaging/release_checks.json').read_text(encoding='utf-8'))
    coverage = plan['coverage']
    assert coverage and isinstance(coverage, dict)
    mapped = set()
    for source, entry in coverage.items():
        source_path = Path(source)
        assert not source_path.is_absolute() and '..' not in source_path.parts
        assert (root / source).is_file(), source
        assert isinstance(entry['reason'], str) and entry['reason'].strip(), source
        assert entry['tests'] and len(entry['tests']) == len(set(entry['tests'])), source
        assert set(entry['tests']) <= set(paths), source
        mapped.update(entry['tests'])
    # No wildcard/cumulative expected set: every selected test needs an explicit dependency reason.
    assert mapped == set(paths)


def test_current_release_keeps_feature_boundaries_and_delivery_contracts():
    """0.39.1(0.39.0 제품 되돌림): 되돌린 경로의 기존 검사 + 설정 호환 + 배포 계약. (0.39.0 자동 찾기 경계는 기능과 함께 빠짐)"""
    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / 'packaging/release_checks.json').read_text(encoding='utf-8'))
    paths = set(plan['tests'])
    # Minimum risk boundaries, not the union of every earlier release's tests.
    assert {
        'tests/test_config_compat_039.py', 'tests/test_setup.py',
        'tests/test_region_registration.py', 'tests/test_status_panel.py',
        'tests/test_halo_timer.py', 'tests/test_resource_live_samples.py',
        'tests/test_blackbox_combat.py', 'tests/test_release_checks.py',
        'tests/test_release_candidate.py', 'tests/test_windows_ci.py',
        'tests/test_startup_smoke.py',
    } <= paths
    assert {
        'src/mabinogi_addon/ui/setup_flow.py', 'src/mabinogi_addon/ui/setup_guide.py',
        'src/mabinogi_addon/config.py', 'src/mabinogi_addon/detect/tuarim_reader.py',
        'src/mabinogi_addon/assets/release_notes.md',
    } <= set(plan['coverage'])
    # The separate development entry must continue collecting the whole suite.
    regression = (root / '.github/workflows/regression.yml').read_text(encoding='utf-8')
    assert 'scripts.run_regressions' in regression
    assert 'run_release_checks' not in regression
