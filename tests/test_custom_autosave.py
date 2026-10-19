"""Applied preset, selection and startup target are independent state machines."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog

from mabinogi_addon import config
from mabinogi_addon.ui.custom_overlay_tab import CustomOverlayTab


class Watcher:
    def is_game_active(self):
        return False

    def is_self_active(self):
        return False


def box(x):
    return dict(x=x, y=20, w=48, h=48, posX=100, posY=100, name="한글 이름")


@pytest.fixture
def tab():
    QApplication.instance() or QApplication([])
    config.save_custom_preset("A", [box(1)])
    config.save_custom_preset("B", [box(2)])
    config.save_custom_preset("C", [box(3)])
    config.save_auto_preset("C")
    widget = CustomOverlayTab(Watcher())
    yield widget
    # Failure injection is scoped with monkeypatch.context in the tests.
    assert widget.flush_pending()
    widget.shutdown()
    widget.close()


def select(tab, name):
    index = tab.preset_combo.findData(name)
    assert index >= 0, name
    tab.preset_combo.setCurrentIndex(index)


def test_selected_and_startup_targets_do_not_redirect_edits(tab):
    assert tab._apply_preset("A")
    select(tab, "B")
    tab._mgr.add(box(4))
    assert tab._active_preset == "A"
    assert tab.flush_pending()
    assert len(config.load_custom_presets()["A"]) == 2
    assert len(config.load_custom_presets()["B"]) == 1
    assert config.load_auto_preset() == "C"
    tab._on_preset_load()
    assert tab._active_preset == "B"
    assert len(config.load_custom_presets()["A"]) == 2
    assert tab._apply_preset("A")
    assert len(tab._mgr.overlays()) == 2


def test_move_scale_lock_and_empty_edits_persist(tab):
    assert tab._apply_preset("A")
    overlay = tab._mgr.overlays()[0]
    overlay.move(456, 789)
    overlay._scale = 1.7
    overlay.moved.emit()
    tab._mgr.set_locked_all(True)
    assert tab.flush_pending()
    data = config.load_custom_presets()["A"][0]
    assert (data["posX"], data["posY"], data["scale"], data["locked"]) == (456, 789, 1.7, True)
    tab._mgr.clear()
    assert tab._apply_preset("B")
    assert config.load_custom_presets()["A"] == []
    assert tab._apply_preset("A")
    assert tab._mgr.overlays() == []


def test_save_as_always_prompts_and_switches_only_after_success(tab, monkeypatch):
    assert tab._apply_preset("A")
    select(tab, "B")
    tab._mgr.add(box(4))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a: ("D", True))
    tab._on_preset_save()
    assert tab._active_preset == "D"
    presets = config.load_custom_presets()
    assert len(presets["A"]) == len(presets["D"]) == 2
    tab._mgr.clear()
    assert tab.flush_pending()
    assert config.load_custom_presets()["D"] == []
    assert config.load_custom_presets()["A"] == presets["A"]
    assert config.load_custom_presets()["B"] == presets["B"]
    assert config.load_auto_preset() == "C"


@pytest.mark.parametrize("action", ["cancel", "overwrite_rejected", "write_failure"])
def test_unsuccessful_save_as_preserves_target_and_disk(tab, monkeypatch, action):
    assert tab._apply_preset("A")
    before = config.LOCAL_CONFIG_PATH.read_bytes()
    tab._mgr.add(box(4))
    with monkeypatch.context() as patch:
        patch.setattr(QInputDialog, "getText", lambda *a: ("B", action != "cancel"))
        patch.setattr(tab, "_confirm", lambda *a: action != "overwrite_rejected")
        if action == "write_failure":
            patch.setattr(config, "save_custom_edit", denied)
        tab._on_preset_save()
        assert tab._active_preset == "A"
        assert config.LOCAL_CONFIG_PATH.read_bytes() == before
        assert len(tab._mgr.overlays()) == 2
    assert tab.flush_pending()


def denied(*args, **kwargs):
    raise PermissionError("한글 경로 쓰기 거부")


def test_failed_save_blocks_switch_retains_edits_and_can_retry(tab, monkeypatch):
    assert tab._apply_preset("A")
    before = config.LOCAL_CONFIG_PATH.read_bytes()
    tab._mgr.add(box(4))
    with monkeypatch.context() as patch:
        patch.setattr(config, "save_custom_edit", denied)
        assert not tab.flush_pending()
        assert not tab._apply_preset("B")
        assert tab._active_preset == "A"
        assert len(tab._mgr.overlays()) == 2
        assert config.LOCAL_CONFIG_PATH.read_bytes() == before
        assert tab.save_status.text() == "저장 실패"
        assert not tab._save_timer.isActive()
    assert tab.flush_pending()
    assert tab.save_status.text() == "자동 저장됨"
    assert tab._apply_preset("B")


def test_load_write_failure_rolls_back_visible_composition(tab, monkeypatch):
    assert tab._apply_preset("A")
    before = tab._mgr.to_dicts()
    with monkeypatch.context() as patch:
        patch.setattr(config, "save_custom_edit", denied)
        assert not tab._apply_preset("B")
        assert tab._mgr.to_dicts() == before
        assert tab._active_preset == "A"
    assert tab.flush_pending()


def test_delete_pending_active_preset_does_not_resurrect(tab, monkeypatch):
    assert tab._apply_preset("A")
    tab._mgr.add(box(4))
    select(tab, "A")
    monkeypatch.setattr(tab, "_confirm", lambda *a: True)
    tab._on_preset_delete()
    assert "A" not in config.load_custom_presets()
    assert tab._active_preset is None
    assert not tab._save_timer.isActive()
    tab._mgr.set_locked_all(True)
    assert tab.flush_pending()
    assert "A" not in config.load_custom_presets()
    assert config.load_auto_preset() == "C"


def test_legacy_unknown_target_not_inferred_and_empty_startup_preset():
    QApplication.instance() or QApplication([])
    config.save_custom_preset("A", [box(1)])
    config.save_custom_overlays([box(1)])
    widget = CustomOverlayTab(Watcher())
    try:
        assert widget._active_preset is None
        assert widget._mgr.overlays() == []  # Existing startup policy: explicit auto preset only.
        widget._mgr.add(box(4))
        assert widget.flush_pending()
        assert config.load_custom_presets()["A"] == [box(1)]
    finally:
        widget.shutdown()
        widget.close()
    config.save_custom_preset("empty", [])
    config.save_auto_preset("empty")
    widget = CustomOverlayTab(Watcher())
    try:
        assert widget._active_preset == "empty"
        assert widget._mgr.overlays() == []
    finally:
        widget.shutdown()
        widget.close()


def test_atomic_replace_failure_keeps_last_good_primary_and_backup(tmp_path, monkeypatch):
    path = tmp_path / "한글 폴더" / "설정.json"
    config.save_custom_edit([box(1)], "A", path=path)
    before = path.read_bytes()
    replace = os.replace

    def fail_final(source, destination):
        if destination == path:
            raise PermissionError("replace denied")
        return replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_final)
        with pytest.raises(PermissionError):
            config.save_custom_edit([box(2)], "A", path=path)
    assert path.read_bytes() == before
    assert path.with_name(path.name + ".bak").read_bytes() == before
    assert config.load_custom_presets(path)["A"] == [box(1)]


def test_debounce_batches_edits_and_per_row_mixed_lock_is_preserved(tab, monkeypatch):
    assert tab._apply_preset("A")
    save = config.save_custom_edit
    calls = []

    def counted(*args, **kwargs):
        calls.append(args)
        return save(*args, **kwargs)

    monkeypatch.setattr(config, "save_custom_edit", counted)
    tab._mgr.add(box(4))
    for i in range(30):
        tab._mgr.overlays()[0].move(100 + i, 300)
        tab._mgr.overlay_moved.emit()
    item = tab.overlay_list.topLevelItem(0)
    tab.overlay_list.topLevelItem(1).setSelected(True)
    item.setCheckState(3, Qt.CheckState.Checked)
    assert tab.overlay_list.topLevelItem(0) is item
    assert tab.overlay_list.topLevelItem(1).isSelected()
    assert [o.locked for o in tab._mgr.overlays()] == [True, False]
    assert not calls
    from test_support.qt_wait import until
    until(lambda: bool(calls) and not tab._save_timer.isActive(), timeout_ms=1000)
    assert len(calls) == 1
    assert not tab._save_timer.isActive()
    assert config.load_custom_presets()["A"][0]["posX"] == 129


def test_repeated_apply_pause_and_edit_does_not_accumulate_windows_or_timers(tab):
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer

    assert tab._apply_preset("A")
    timers = set(tab.findChildren(QTimer))
    before = len(QApplication.topLevelWidgets())
    for i in range(40):
        assert tab._apply_preset("A" if i % 2 else "B")
        tab.set_paused(True)
        tab.set_paused(False)
        tab._mgr.set_locked_all(i % 2 == 0)
        assert tab.flush_pending()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
    assert set(tab.findChildren(QTimer)) == timers
    assert len(QApplication.topLevelWidgets()) <= before
    assert len(tab._mgr.overlays()) == 1


def test_shutdown_flushes_pending_edits_without_changing_startup_target(tab):
    assert tab._apply_preset("A")
    tab._mgr.add(box(4))
    assert tab._save_timer.isActive()
    tab.shutdown()
    assert not tab._save_timer.isActive()
    reopened = CustomOverlayTab(Watcher())
    try:
        assert reopened._active_preset == "C"
        assert reopened._apply_preset("A")
        assert len(reopened._mgr.overlays()) == 2
        assert config.load_auto_preset() == "C"
    finally:
        reopened.shutdown()
        reopened.close()


def test_failed_delete_keeps_named_target_and_applied_state(tab, monkeypatch):
    assert tab._apply_preset("A")
    select(tab, "B")
    notices = []
    monkeypatch.setattr(tab, "_confirm", lambda *a: True)
    monkeypatch.setattr(tab, "_info", notices.append)
    with monkeypatch.context() as patch:
        patch.setattr(config, "delete_custom_preset", denied)
        tab._on_preset_delete()
    assert "'B'" in notices[0]
    assert tab._active_preset == "A"
    assert "B" in config.load_custom_presets()
    assert not tab._dirty
