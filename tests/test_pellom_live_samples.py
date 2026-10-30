"""Keep the independent live repro unchanged and test auxiliary-bar rejection."""

from hashlib import sha256
from zipfile import ZipFile

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon import autofind_diagnostics as diag
from mabinogi_addon.autofind_replay import replay
from mabinogi_addon.detect import boss_bar, boss_hp_reader, boss_name_matcher
from test_autofind_diagnostics import storage, _capture
from scripts.qa_pellom_live_samples import (
    SAMPLES, EXPECTED_HP, ROOT, crop, upper_box,
    test_visible_pellom_is_identified,
    test_upper_boss_hp_is_read,
    test_low_hp_autofind_never_selects_erg_bar,
    test_actual_boss_tick_starts_pellom_tracking,
)


def image(stamp="001801"):
    result = image_io.imread(ROOT / f"tests/data/스크린샷 2026-10-18 {stamp}.png")
    assert result is not None
    return result


def test_new_name_does_not_replace_original_or_lower_threshold():
    frame = crop(image("001216"), upper_box("001216"))[:, :312]
    primary = boss_name_matcher.load_name_templates()
    variants = boss_name_matcher.load_name_variants()
    assert boss_name_matcher.MATCH_THRESHOLD == .6
    assert primary["pellom"].shape == (15, 28)
    assert np.count_nonzero(primary["pellom"]) == 30
    assert boss_name_matcher.identify(frame, primary) is None
    assert boss_name_matcher.identify(frame, primary, variants=variants) == "pellom"
    template = variants["pellom"][0]
    assert template.shape == (17, 32)
    assert np.count_nonzero(template) == 186


def test_low_hp_actual_tick_uses_existing_registered_region(monkeypatch):
    test_actual_boss_tick_starts_pellom_tracking(monkeypatch, "001801")


def test_auxiliary_percent_is_not_sufficient_for_a_boss(monkeypatch):
    auxiliary = image()[1280:1317, 1016:1537]
    assert boss_name_matcher.identify(auxiliary[:, :312]) is None
    def forbidden(*args, **kwargs):
        pytest.fail("auxiliary bar must be rejected before numeric interpretation")
    monkeypatch.setattr(boss_hp_reader, "read_percent", forbidden)
    trace = {}
    assert not boss_bar.make_validator(diagnostics=trace)(auxiliary)
    assert trace["validation"][-1]["rejection"] == "auxiliary_bar"


def test_bright_sample_only_participates_in_low_hp_fallback():
    upper = crop(image(), upper_box("001801"))[:, int(521 * .58):]
    assert boss_hp_reader._ACCEPT == .45
    # 0.31.0: 4K 굵은 '8' 샘플(UHD_DIGIT_SAMPLES)이 생겨 기본 경로도 이 프레임을 같은 값 8로 읽는다.
    # 밝은 샘플이 저HP 보조 경로에서만 쓰인다는 점은 4K 샘플을 뺀 기존 샘플로 확인한다.
    assert boss_hp_reader.read_percent(upper, boss_hp_reader._DIGITS) in (None, 8)
    legacy = boss_hp_reader._load_digits(exclude=boss_hp_reader.UHD_DIGIT_SAMPLES)
    assert boss_hp_reader.read_percent(upper, legacy) is None
    assert boss_hp_reader.read_percent(upper, legacy, bright_samples=boss_hp_reader._BRIGHT_SAMPLES) == 8
    auxiliary = image()[1280:1317, 1016:1537]
    assert boss_hp_reader.read_percent(auxiliary) == boss_hp_reader.read_percent(auxiliary, boss_hp_reader._DIGITS)


def test_auxiliary_strip_without_boss_above_is_rejected():
    frame = image()
    frame[1246:1280, 1016:1537] = 0
    assert boss_bar.locate_boss_bar(frame, boss_bar.make_validator()) is None


@pytest.mark.parametrize("stamp,expected", tuple(zip(SAMPLES, EXPECTED_HP)))
def test_cached_presence_matches_low_hp_reader(stamp, expected):
    frame = crop(image(stamp), upper_box(stamp))[:, int(521 * .58):]
    value, shift = boss_hp_reader.read_percent_cached(frame)
    assert value == expected
    assert boss_hp_reader.read_percent_cached(frame, hint=shift)[0] == expected


def test_low_hp_autofind_snapshot_replays_without_live_templates(storage, monkeypatch, tmp_path):
    frame = image()
    diag.perform_autofind("boss", _capture(frame), storage=storage)
    storage.io.wait()
    record = storage.recent()[0]
    assert record.metadata["success"]
    assert abs(record.metadata["result"][1] - 1246) < 3
    assert "auxiliary_name_erg" in record.metadata["asset_names"]
    assert any(name.startswith("bright_digit_8_") for name in record.metadata["asset_names"])
    path = storage.export(record, tmp_path / "펠롬 저HP.zip")
    monkeypatch.setattr(boss_bar, "_AUXILIARY_NAMES", {})
    monkeypatch.setattr(boss_hp_reader, "_DIGITS", {})
    monkeypatch.setattr(boss_hp_reader, "_BRIGHT_SAMPLES", {})
    replayed = replay(path)
    assert replayed["replayed"] and replayed["matches_recorded"]
    with ZipFile(path) as archive:
        saved = cv2.imdecode(np.frombuffer(archive.read("input.png"), np.uint8), cv2.IMREAD_COLOR)
    np.testing.assert_array_equal(saved, frame)


def test_missing_auxiliary_asset_is_setup_failure(storage, monkeypatch):
    monkeypatch.setattr(boss_bar, "_AUXILIARY_NAMES", {})
    diag.perform_autofind("boss", _capture(np.zeros((80, 120, 3), np.uint8)), storage=storage)
    storage.io.wait()
    record = storage.recent()[0]
    assert record.metadata["failure_stage"] == "detector_setup"
    assert record.metadata["missing_required_assets"] == ["auxiliary_name_erg"]


def test_existing_readable_low_hp_values_are_not_replaced():
    from test_boss_hp_reader import _norm37, _POINCHE_ZIP

    count = 0
    with ZipFile(_POINCHE_ZIP) as archive:
        for name in archive.namelist():
            if "hpxxx_" not in name:
                continue
            frame = cv2.imdecode(np.frombuffer(archive.read(name), np.uint8), cv2.IMREAD_COLOR)
            frame = _norm37(frame)
            baseline = boss_hp_reader.read_percent(frame, boss_hp_reader._DIGITS)
            current = boss_hp_reader.read_percent(frame)
            if baseline is not None:
                assert current == baseline, (name, baseline, current)
                count += 1
    assert count >= 20


def test_published_v83_notes_are_preserved():
    notes = (ROOT / "src/mabinogi_addon/assets/release_notes.md").read_text(encoding="utf-8")
    published = notes[notes.index("## v0.4.83\n"):]
    # Canonical LF text from published tag ec4a903, independent of checkout CRLF.
    assert sha256(published.encode("utf-8")).hexdigest() == "a16e6ac72e5726c5940d1c2cd6f024ca37ee8b86fa2b8da3425476ace1770e93"
