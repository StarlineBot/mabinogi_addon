"""Keep the original independent low-range reproductions in the CI gate."""

import pytest

from mabinogi_addon.detect import tuarim_reader as reader
from scripts.qa_tuarim_low_range_display import sample
from scripts.qa_tuarim_low_range_display import (
    pipeline,
    test_existing_full_percent_contract_remains_safe,
    test_low_range_word_keeps_visible_tens,
    test_real_reader_value_reaches_percent_overlay,
)


@pytest.mark.parametrize("tens,score", [(9, 0.99), (1, 0.59), (4, 0.99)])
def test_sparse_ink_does_not_invent_high_values(monkeypatch, tens, score):
    original = reader._classify

    def classify(vec, refs, labels):
        if refs is reader._REFS[2]:
            return tens, score
        return original(vec, refs, labels)

    monkeypatch.setattr(reader, "_classify", classify)
    assert reader.read_percent(sample("v06_7466.png")) is None


def test_sparse_ink_requires_confident_ones_at_the_same_alignment(monkeypatch):
    original = reader._classify

    def classify(vec, refs, labels):
        if refs is reader._REFS[0]:
            return 6, 0.84
        return original(vec, refs, labels)

    monkeypatch.setattr(reader, "_classify", classify)
    assert reader.read_percent(sample("v06_7466.png")) is None


def test_absent_tens_does_not_gain_a_digit(monkeypatch):
    original = reader._classify

    def classify(vec, refs, labels):
        if refs is reader._REFS[2]:
            raise AssertionError("No tens classification for an empty tens cell")
        return original(vec, refs, labels)

    monkeypatch.setattr(reader, "_classify", classify)
    assert reader.read_percent(sample("v06_161.png")) == 6
