"""Explicit unresolved auto/legacy setup prerequisite reproduction."""

from copy import deepcopy

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, setup_state
from mabinogi_addon.ui.setup_page import SetupPage


def settings(flag=None, legacy="percent"):
    general = {"debuffGateMode": legacy, "gameExe": "Client.exe"}
    if flag is not None:
        general["debuffAutoGate"] = flag
    return {
        "general": general,
        "buffTracker": {"enabled": False},
        "debuffTracker": {"enabled": True, "captureRegion": dict(x=100,y=100,w=520,h=88)},
        "bossPattern": {"enabled": False},
        "customOverlay": {"enabled": False},
        "memo": {"enabled": False},
    }


@pytest.mark.parametrize("flag", (None, True), ids=("upgraded-default", "explicit-auto"))
@pytest.mark.parametrize("check", ("missing", "pending"))
def test_auto_does_not_require_optional_hp_region(flag, check, tmp_path):
    raw = settings(flag)
    path = tmp_path / "settings.json"
    config._write_local_config(raw,path)
    assert config.load_debuff_runtime_mode(path) == "auto"
    result = (setup_state.missing("debuff",raw) if check == "missing" else
              setup_state.pending(raw,automatic_only=True,feature_keys=("debuff",)))
    assert result == [], {"runtime": "auto", "legacy": "percent", "unexpected_requirements": result}


@pytest.mark.parametrize("logged_in", (False, True))
def test_real_setup_page_reports_registered_debuff_in_auto(monkeypatch, logged_in):
    app = QApplication.instance() or QApplication([])
    raw = settings(True)
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: deepcopy(raw))
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id":"qa"} if logged_in else None)
    page = SetupPage()
    try:
        page.show()
        app.processEvents()
        _, label, _ = page.feature_rows["debuff"]
        assert label.text() == "영역 등록됨"
    finally:
        page.close()
        app.processEvents()


def test_explicit_legacy_percent_keeps_real_prerequisite(tmp_path):
    raw = settings(False)
    path = tmp_path / "settings.json"
    config._write_local_config(raw,path)
    assert config.load_debuff_runtime_mode(path) == "percent"
    assert setup_state.missing("debuff",raw) == ["boss"]


@pytest.mark.parametrize("legacy", ("off", "band"))
def test_other_legacy_values_do_not_add_hp_requirement(legacy):
    raw = settings(True, legacy)
    assert setup_state.missing("debuff",raw) == []
