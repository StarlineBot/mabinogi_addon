"""Independent diagnostics QA; run explicitly with pytest from the repository."""

import os
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest

from mabinogi_addon import autofind_diagnostics as diagnostics
from mabinogi_addon import config, image_io, paths
from mabinogi_addon.autofind_replay import detector_assets, replay, run_detector
from mabinogi_addon.ui import diag_capture, dpi


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    settings_path = tmp_path / 'settings.json'
    raw_reader = config._read_local_config
    config._write_local_config({}, path=settings_path)
    monkeypatch.setattr(config, '_read_local_config', lambda *a, **k: raw_reader(settings_path))
    user_dir = tmp_path / 'user'
    monkeypatch.setattr(paths, 'user_data_dir', lambda: user_dir)
    monkeypatch.setattr(dpi, 'screen_scale', lambda: 1.0)
    return settings_path, user_dir


@pytest.fixture
def storage(tmp_path):
    store = diagnostics.DiagnosticStore(tmp_path / 'records')
    yield store
    store.io.close()


def region():
    return {'x': -100, 'y': 50, 'w': 30, 'h': 20}


@pytest.mark.skipif(os.name == 'nt', reason='Directory chmod does not validate Windows ACLs.')
def test_actual_read_only_directory_is_reported(isolated, monkeypatch):
    settings_path, user_dir = isolated
    config._write_local_config({'buffTracker': {'captureRegion': region()}}, path=settings_path)
    user_dir.mkdir()
    user_dir.chmod(0o500)
    try:
        result = diag_capture.save_diagnostic()
    finally:
        user_dir.chmod(0o700)
    assert 'PermissionError' in result.error
    assert not result.saved
    assert result.regions[0].status == 'save_failed'
    assert '\uc800\uc7a5 \ud3f4\ub354 \uc624\ub958' in result.message()


def test_real_corrupt_json_region_keeps_valid_region(isolated, monkeypatch):
    settings_path, _ = isolated
    config._write_local_config({
        'buffTracker': {'captureRegion': {'x': 0, 'y': 0, 'w': 30}},
        'debuffTracker': {'captureRegion': region()},
    }, path=settings_path)
    monkeypatch.setattr(diag_capture, '_grab_pixels', lambda pixels: np.full((20, 30, 3), 70, np.uint8))
    result = diag_capture.save_diagnostic()
    assert [r.status for r in result.regions] == ['invalid_region', 'saved', 'unconfigured']
    assert len(result.saved) == 1
    np.testing.assert_array_equal(
        image_io.imread(result.directory / result.saved[0]),
        np.full((20, 30, 3), 70, np.uint8),
    )


@pytest.mark.parametrize('failure', ['capture', 'png'])
def test_failures_are_distinguished_with_real_config(isolated, monkeypatch, failure):
    settings_path, _ = isolated
    config._write_local_config({'buffTracker': {'captureRegion': region()}}, path=settings_path)
    def grab(pixels):
        if failure == 'capture':
            raise RuntimeError('independent capture failure')
        return np.zeros((20, 30, 3), np.uint8)
    monkeypatch.setattr(diag_capture, '_grab_pixels', grab)
    if failure == 'png':
        monkeypatch.setattr(image_io, 'imwrite', lambda *a, **k: False)
    result = diag_capture.save_diagnostic()
    assert result.regions[0].status == ('capture_failed' if failure == 'capture' else 'save_failed')
    assert result.regions[0].error


def test_real_image_and_zip_bytes_preserved(isolated, storage, tmp_path):
    frame = image_io.imread(REPO / 'tests/data/tuarim_hi/95.png')
    assert frame is not None
    original = frame.copy()
    diagnostics.perform_autofind('stat_bars', lambda: (frame, -1920, 100), storage=storage)
    frame[:] = 0
    storage.io.wait()
    record = storage.recent()[0]
    png_path = record.directory / 'input.png'
    np.testing.assert_array_equal(image_io.imread(png_path), original)
    path = storage.export(record, tmp_path / '\uc6d0\ubcf8 \uacf5\uc720.zip')
    with ZipFile(path) as archive:
        assert archive.read('input.png') == png_path.read_bytes()
    assert replay(path)['matches_recorded']


@pytest.mark.parametrize('feature', ['buff', 'boss', 'debuff'])
def test_absent_required_templates_must_not_claim_replayed(isolated, storage, tmp_path, monkeypatch, feature):
    from mabinogi_addon.detect import status_panel, boss_hp_reader
    frame = image_io.imread(REPO / 'tests/data/\uc2a4\ud06c\ub9b0\uc0f7 2026-10-09 190901.png')
    assert frame is not None
    assert run_detector(feature, frame, detector_assets(feature), {}) is not None
    if feature == 'buff':
        monkeypatch.setattr(status_panel, 'anchor_template', lambda: None)
    else:
        monkeypatch.setattr(boss_hp_reader, '_DIGITS', {})
    diagnostics.perform_autofind(feature, lambda: (frame, 0, 0), storage=storage)
    storage.io.wait()
    record = storage.recent()[0]
    assert record.metadata['success'] is False
    assert record.metadata['failure_stage'] == 'detector_setup'
    expected_missing = ['anchor'] if feature == 'buff' else [f'digit_{d}' for d in '0123456789']
    assert record.metadata['missing_required_assets'] == expected_missing
    archive = storage.export(record, tmp_path / (feature + '-missing-assets.zip'))
    result = replay(archive)
    print({'feature': feature, 'asset_names': record.metadata.get('asset_names'), 'replayed': result['replayed'],
           'matches_recorded': result.get('matches_recorded'), 'trace': result.get('trace')})
    assert result['replayed'] is False, (
        'Missing mandatory detector templates are mistaken for a successfully reproduced no-match.'
    )
    assert result['failure_stage'] == 'detector_setup'
    assert result['missing_assets'] == expected_missing
    assert result['error']
