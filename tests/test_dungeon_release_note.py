"""The bundled calculator announcement must reach new and upgrading users."""

from pathlib import Path

import pytest

from mabinogi_addon.ui import release_notes


@pytest.mark.parametrize("current,last_seen", [("0.5.1", None), ("0.5.1", "0.4.90"),
                                              ("0.5.2", "0.4.90")])
def test_calculator_announcement_is_visible(current, last_seen, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "src/mabinogi_addon/assets/release_notes.md"
    monkeypatch.setattr(release_notes, "RELEASE_NOTES_FILE", source)
    visible = release_notes.notes_since(last_seen, current)
    assert "편의기능에 던전 입장 계산기를 추가했습니다" in visible
    assert "누적 순이익" in visible
    assert "믿음의 균열" in visible


def test_later_first_launch_does_not_repeat_the_calculator_launch_announcement(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "src/mabinogi_addon/assets/release_notes.md"
    monkeypatch.setattr(release_notes, "RELEASE_NOTES_FILE", source)
    sections = release_notes._parse_sections(source.read_text(encoding="utf-8"))
    current = sections[0][0]
    assert current != "0.5.1"
    visible = release_notes.notes_since(None, current)
    assert visible.startswith(f"## v{current}")
    assert "## v0.5.1" not in visible
    assert "편의기능에 던전 입장 계산기를 추가했습니다" not in visible
