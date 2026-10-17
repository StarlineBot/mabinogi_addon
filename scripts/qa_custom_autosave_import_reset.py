"""Pending custom edits must not overwrite imported or reset configuration."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from test_navigation import window
from test_custom_autosave import box
from mabinogi_addon import config


@pytest.mark.parametrize("action", ["import-other-name", "import-same-name", "import-same-name-zip", "reset"])
@pytest.mark.parametrize("completion", ["normal-close", "debounce"])
def test_import_or_reset_wins_over_previous_session_custom_autosave(
    window, monkeypatch, tmp_path, action, completion,
):
    w, app = window
    panel = w.custom_overlay_tab
    config.save_custom_preset("old-A", [box(1)])
    assert panel._apply_preset("old-A")
    panel._mgr.add(box(4))
    assert panel._dirty
    if completion == "normal-close":
        # A previous save failure leaves pending edits indefinitely, without a timer race.
        with monkeypatch.context() as patch:
            def denied(*args, **kwargs):
                raise PermissionError("QA transient write failure")
            patch.setattr(config, "save_custom_edit", denied)
            assert not panel.flush_pending()
        assert panel._dirty and not panel._save_timer.isActive()

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    if action.startswith("import"):
        incoming = tmp_path / "incoming.json"
        name = "old-A" if "same-name" in action else "imported-B"
        config.save_custom_edit([box(99)], name, path=incoming)
        config.save_auto_preset(name, path=incoming)
        if action.endswith("zip"):
            archive = tmp_path / "incoming.zip"
            config.export_bundle(archive, path=incoming)
            incoming = archive
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(incoming), ""))
        w.settings_tab._on_import_config()
    else:
        w.settings_tab._on_reset_config()
    assert w._config_pending_restart
    expected = deepcopy(config._read_local_config().get("customOverlay"))
    print({"action": action, "completion": completion, "before": expected})
    if completion == "normal-close":
        w._force_quit = True
        assert w.close()
    else:
        QTest.qWait(450)
    observed = config._read_local_config().get("customOverlay")
    print({"after": observed})
    assert observed == expected, "old custom autosave overwrote imported/reset settings"


@pytest.mark.parametrize("action", ["import", "reset"])
def test_clean_custom_save_control_preserves_replacement(window, monkeypatch, tmp_path, action):
    w, _ = window
    panel = w.custom_overlay_tab
    config.save_custom_preset("old-A", [box(1)])
    assert panel._apply_preset("old-A") and not panel._dirty
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    if action == "import":
        incoming = tmp_path / "clean-incoming.json"
        config.save_custom_edit([box(99)], "old-A", path=incoming)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(incoming), ""))
        w.settings_tab._on_import_config()
    else:
        w.settings_tab._on_reset_config()
    expected = deepcopy(config._read_local_config().get("customOverlay"))
    w._force_quit = True
    assert w.close()
    assert config._read_local_config().get("customOverlay") == expected
