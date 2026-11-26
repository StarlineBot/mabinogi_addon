"""출처 표기(기획 11-26 — 넥슨 오픈 API 'Data based on NEXON Open API', ElevenLabs 무료 요금제 'elevenlabs.io')."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from mabinogi_addon.ui.widgets import NEXON_CREDIT, VOICE_CREDIT  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _texts(widget):
    return [lbl.text() for lbl in widget.findChildren(QLabel)]


def test_credit_strings():
    assert NEXON_CREDIT == "Data based on NEXON Open API"
    assert VOICE_CREDIT == "목소리: ElevenLabs (elevenlabs.io)"


@pytest.mark.parametrize("module,cls", [
    ("exchange_tab", "ExchangeTab"), ("craft_tab", "CraftTab"), ("dungeon_cost_tab", "DungeonCostTab"),
    ("distribution_tab", "DistributionTab"), ("party_tab", "PartyTab"), ("music_buff_tab", "MusicBuffTab"),
])
def test_nexon_api_tabs_show_credit(app, module, cls):
    import importlib
    tab_cls = getattr(importlib.import_module(f"mabinogi_addon.ui.{module}"), cls)
    tab = tab_cls()
    assert NEXON_CREDIT in _texts(tab)


def test_companion_tab_shows_voice_credit(app):
    from mabinogi_addon.ui.character_tab import CharacterTab
    assert VOICE_CREDIT in _texts(CharacterTab())


def test_settings_shows_both_credits(app):
    from mabinogi_addon.ui.settings_tab import SettingsTab
    from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
    texts = "\n".join(_texts(SettingsTab(AlwaysActiveWatcher())))
    assert NEXON_CREDIT in texts and VOICE_CREDIT in texts
