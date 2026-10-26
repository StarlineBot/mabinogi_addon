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


def test_current_plan_matches_bundled_release_and_changed_features():
    root = Path(__file__).resolve().parents[1]
    notes = (root / 'src/mabinogi_addon/assets/release_notes.md').read_text(encoding='utf-8')
    version = notes.splitlines()[0].removeprefix('## v')
    paths = checks.release_tests(root, version)
    expected = {path.relative_to(root).as_posix() for path in (root / 'tests').glob('test_blackbox*.py')}
    expected.update({
        'tests/test_frame_summary.py', 'tests/test_optimization.py',
        'tests/test_optimization_network.py', 'tests/test_optimization_contract.py',
        'tests/test_optimization_ui.py', 'tests/test_config_atomic.py',
        'tests/test_config_bundle.py', 'tests/test_startup_build.py',
        'tests/test_autostart.py', 'tests/test_updater_relaunch_env.py',
        'tests/test_manual_update_progress.py', 'tests/test_overlay_metrics.py',
        'tests/test_halo_clock.py', 'tests/test_log_throttle.py',
        'tests/test_process_priority.py', 'tests/test_optimization_priority.py', 'tests/test_process_threads.py',
        'tests/test_access_cache.py', 'tests/test_optimization_auto.py', 'tests/test_cpu_layouts.py',
        'tests/test_optimization_recommend.py', 'tests/test_guide_images.py', 'tests/test_setup.py',
        'tests/test_optimization_public.py', 'tests/test_game_restart_reset.py',
        'tests/test_graphics_efficiency.py', 'tests/test_debuff_native_icons.py', 'tests/test_crescendo_native.py',
        'tests/test_debuff_engine.py', 'tests/test_debuff_identity.py', 'tests/test_debuff_added_defaults.py',
        'tests/test_debuff_icon_migration.py',
    })
    assert set(paths) == expected
