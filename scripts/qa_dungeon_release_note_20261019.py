"""New calculator is absent from the bundled first-run and upgrade notes."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mabinogi_addon.ui import release_notes  # noqa: E402


@pytest.mark.parametrize("last_seen", [None, "0.4.90"])
def test_bundled_update_explains_new_dungeon_calculator(last_seen, monkeypatch):
    source = ROOT / "src" / "mabinogi_addon" / "assets" / "release_notes.md"
    monkeypatch.setattr(release_notes, "RELEASE_NOTES_FILE", source)
    sections = release_notes._parse_sections(source.read_text(encoding="utf-8"))
    assert sections
    current = sections[0][0]
    visible = release_notes.notes_since(last_seen, current)
    assert "던전" in visible and "입장" in visible, (
        f"New dungeon entry calculator has no bundled update explanation: "
        f"last_seen={last_seen}, current={current}"
    )
