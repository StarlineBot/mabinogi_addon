"""Configuration replacement retires every old-session custom writer."""

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from mabinogi_addon import config
from test_navigation import window
from test_custom_autosave import box, select
from test_support.regressions.custom_replacement import (
    test_import_or_reset_wins_over_previous_session_custom_autosave,
    test_clean_custom_save_control_preserves_replacement,
)


def dialogs(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


@pytest.mark.parametrize("action", ["import", "reset"])
def test_replacement_blocks_retry_late_signals_and_all_preset_writers(window, monkeypatch, tmp_path, action):
    w, app = window
    panel = w.custom_overlay_tab
    config.save_custom_preset("A", [box(1)])
    assert panel._apply_preset("A")
    select(panel, "A")
    panel._mgr.add(box(4))
    dialogs(monkeypatch)
    if action == "import":
        incoming = tmp_path / "수입 설정.json"
        config.save_custom_edit([box(99)], "A", path=incoming)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(incoming), ""))
        w.settings_tab._on_import_config()
    else:
        w.settings_tab._on_reset_config()
    expected = config.LOCAL_CONFIG_PATH.read_bytes() if config.LOCAL_CONFIG_PATH.exists() else None

    def forbidden(*args, **kwargs):
        pytest.fail("retired session attempted to write settings or open an editing dialog")

    for name in ("save_custom_edit", "delete_custom_preset", "save_auto_preset", "save_mirror_force_capture"):
        monkeypatch.setattr(config, name, forbidden)
    monkeypatch.setattr(QInputDialog, "getText", forbidden)
    monkeypatch.setattr(panel, "_confirm", forbidden)
    panel._mgr.changed.emit()
    panel._mgr.overlay_moved.emit()
    panel._save_timer.timeout.emit()
    panel.retry_btn.click()
    assert panel.flush_pending()
    panel._on_preset_save()
    panel._on_preset_load()
    assert not panel._apply_preset("A")
    panel._on_preset_delete()
    panel._on_auto_changed()
    panel._on_compat_toggled(True)
    panel._on_selected(4, 20, 48, 48)
    panel.set_paused(False)
    panel._on_enable(True)
    QTest.qWait(450)
    assert panel._writes_suspended and not panel.isEnabled()
    assert not panel._save_timer.isActive() and not panel._mgr._timer.isActive()
    assert panel._mgr._paused and not panel._mgr.overlays()
    assert panel.save_status.text() == "재시작 필요"
    panel.shutdown()
    w._force_quit = True
    assert w.close()
    observed = config.LOCAL_CONFIG_PATH.read_bytes() if config.LOCAL_CONFIG_PATH.exists() else None
    assert observed == expected


@pytest.mark.parametrize("action", ["import-cancel", "import-failure", "reset-cancel", "reset-failure"])
def test_unsuccessful_replacement_keeps_pending_custom_edit(window, monkeypatch, tmp_path, action):
    w, _ = window
    panel = w.custom_overlay_tab
    config.save_custom_preset("A", [box(1)])
    assert panel._apply_preset("A")
    panel._mgr.add(box(4))
    dialogs(monkeypatch)
    if action.startswith("import"):
        incoming = tmp_path / "broken.json"
        if action.endswith("failure"):
            def broken(*args, **kwargs):
                raise ValueError("broken")
            monkeypatch.setattr(config, "import_bundle", broken)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(incoming) if action.endswith("failure") else "", ""))
        w.settings_tab._on_import_config()
    else:
        if action.endswith("cancel"):
            monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
        else:
            def denied():
                raise PermissionError("reset denied")
            monkeypatch.setattr(config, "reset_config", denied)
        w.settings_tab._on_reset_config()
    assert not w._config_pending_restart and not panel._writes_suspended
    assert panel._dirty and panel._save_timer.isActive()
    assert panel.flush_pending()
    assert len(config.load_custom_presets()["A"]) == 2


@pytest.mark.parametrize("stage", ["name", "overwrite"])
def test_replacement_during_modal_save_as_does_not_resume_old_timer(window, monkeypatch, stage):
    w, _ = window
    panel = w.custom_overlay_tab
    config.save_custom_preset("A", [box(1)])
    assert panel._apply_preset("A")
    panel._mgr.add(box(4))

    def replace():
        config.reset_config()
        w._on_config_imported()

    def name_dialog(*args):
        if stage == "name":
            replace()
        return "A", True

    def overwrite(*args):
        replace()
        return False

    monkeypatch.setattr(QInputDialog, "getText", name_dialog)
    monkeypatch.setattr(panel, "_confirm", overwrite)
    panel._on_preset_save()
    assert panel._writes_suspended and not panel._save_timer.isActive()
    assert "customOverlay" not in config._read_local_config()
