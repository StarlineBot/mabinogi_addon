"""Approved presentation changes must preserve independent state and storage."""

from copy import deepcopy
import pytest
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QAbstractButton, QPushButton, QWidget
from test_navigation import window
from mabinogi_addon import config
from mabinogi_addon.ui.buff_tab import ANCHOR_ID
from mabinogi_addon.ui.settings_layout import LOCK_STYLE


def settle(app):
    for _ in range(12):
        app.processEvents()


def test_lock_button_height_does_not_change_when_checked(window):
    button = QPushButton("위치 잠금")
    button.setCheckable(True)
    button.setStyleSheet(LOCK_STYLE)
    button.ensurePolished()
    height = button.sizeHint().height()
    button.setChecked(True)
    button.setText("위치 잠금됨")
    assert button.sizeHint().height() == height
    button.deleteLater()


def test_anchor_normal_and_empty_selection_do_not_write(window):
    w, app = window
    w._open_setup_feature("buff")
    tab = w.buff_tab
    before = deepcopy(config._read_local_config())
    normal = next(i for i, key in enumerate(tab._rows()) if key != ANCHOR_ID)
    for _ in range(3):
        tab.buff_list.setCurrentRow(0)
        settle(app)
        assert tab._form_stack.currentWidget() is tab.anchor_panel
        assert not tab.name_edit.isVisible()
        assert not tab.del_btn.isEnabled()
        tab.buff_list.setCurrentRow(normal)
        settle(app)
        assert tab._form_stack.currentWidget() is tab._buff_editor
        assert tab.name_edit.isVisible() and tab.name_edit.isEnabled()
        assert tab.name_edit.text() == tab._display_name(tab._rows()[normal])
        tab.buff_list.setCurrentRow(-1)
        assert tab._form_stack.currentWidget() is tab._empty_panel
    assert config._read_local_config() == before


def test_unregistered_regions_have_no_active_clear_or_view_command(window):
    w, app = window
    for tab in (w.buff_tab, w.debuff_tab, w.boss_tab, w.stat_bars_tab,
                w.dorcha_tab, w.tuarim_tab, w.skillbar_tab, w.memo_tab, w.resource_tab):
        assert not tab.clear_region_btn.isEnabled(), type(tab).__name__
    assert not w.boss_tab.view_region_btn.isEnabled()


def test_stat_individual_and_all_locks_preserve_show_alert_pause(window):
    w, app = window
    tab = w.stat_bars_tab
    w._open_setup_feature("stat_bars")
    tab._paused = True
    original = deepcopy(tab._bars_cfg)
    initial = {key: value["locked"] for key, value in original.items()}
    button = tab.bar_lock_buttons["mp"]
    button.click()
    expected = {**initial, "mp": not initial["mp"]}
    assert {k: v["locked"] for k, v in tab._bars_cfg.items()} == expected
    assert {k: v.locked for k, v in tab._overlays.items()} == expected
    reopened = type(tab)(tab._watcher)
    reopened._timer.stop()
    try:
        assert {k: b.isChecked() for k, b in reopened.bar_lock_buttons.items()} == expected
    finally:
        reopened.shutdown()
        reopened.close()
    for locked in (True, False):
        tab._set_locked_all(locked)
        assert all(b.isChecked() is locked for b in tab.bar_lock_buttons.values())
        assert all(v.locked is locked for v in tab._overlays.values())
    saved = config.load_stat_bars()
    assert tab._paused
    for key in original:
        assert saved["bars"][key]["show"] == original[key]["show"]
        assert saved["bars"][key]["alert"] == original[key]["alert"]
        assert tab.bar_lock_buttons[key].styleSheet() == LOCK_STYLE
        assert tab.bar_lock_buttons[key].text() == "위치 잠금"


def test_custom_empty_and_selection_command_states(window):
    w, app = window
    tab = w.custom_overlay_tab
    selected = (tab.sel_lock_btn, tab.sel_unlock_btn, tab.del_sel_btn)
    all_items = (tab.lock_all_btn, tab.unlock_all_btn, tab.del_all_btn)
    assert not any(b.isEnabled() for b in (*selected, *all_items))
    assert tab.region_btn.isEnabled()
    assert not tab.preset_load_btn.isEnabled()
    assert not tab.preset_delete_btn.isEnabled()
    tab._mgr.add(dict(x=1, y=2, w=40, h=40, posX=100, posY=100, name="시험"))
    assert all(b.isEnabled() for b in all_items)
    assert not any(b.isEnabled() for b in selected)
    tab.overlay_list.topLevelItem(0).setSelected(True)
    assert all(b.isEnabled() for b in selected)
    tab._mgr.clear()
    assert not any(b.isEnabled() for b in (*selected, *all_items))
    before = deepcopy(config._read_local_config())
    tab.preset_manage_btn.setChecked(True)
    tab.preset_manage_btn.setChecked(False)
    assert config._read_local_config() == before


def test_custom_delete_confirmation_identifies_overlay_not_preset(window, monkeypatch):
    w, app = window
    tab = w.custom_overlay_tab
    tab._mgr.add(dict(x=1, y=2, w=40, h=40, posX=100, posY=100, name="삭제 확인 대상"))
    tab.overlay_list.topLevelItem(0).setSelected(True)
    confirmations = []
    monkeypatch.setattr(tab, "_confirm", lambda title, text: confirmations.append((title, text)) or False)
    tab._on_delete_selected()
    tab._on_delete_all()
    assert len(confirmations) == 2
    assert all("삭제 확인 대상" in text for _, text in confirmations)
    assert all("오버레이" in title for title, _ in confirmations)
    assert tab.overlay_list.topLevelItemCount() == 1


def test_resource_both_displays_off_keeps_preview_and_independent_alert(window):
    w, app = window
    w._open_setup_feature("dorcha")
    w.dorcha_tab.enable.setChecked(False)
    w.resource_tab.percent_chk.setChecked(False)
    w.tuarim_tab.enable.setChecked(True)
    settle(app)
    assert w.dorcha_tab.preview_scroll.isVisible()
    assert w.dorcha_tab.preview_scroll.width() > 0
    assert config.load_tuarim()["enabled"]
    assert not w.dorcha_tab.enable.isChecked()
    assert not w.resource_tab.percent_chk.isChecked()


def test_stat_individual_locks_follow_existing_login_gate_without_saving(window, monkeypatch):
    w, app = window
    tab = w.stat_bars_tab
    before = deepcopy(config._read_local_config())
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    tab._apply_login_gate()
    assert not any(button.isEnabled() for button in tab.bar_lock_buttons.values())
    assert config._read_local_config() == before


def test_seeded_lock_and_preset_states_render(window, tmp_path):
    w, app = window
    tab = w.stat_bars_tab
    w._open_setup_feature("stat_bars")
    tab._set_bar_locked("hp", True)
    tab._set_bar_locked("mp", False)
    tab._set_bar_locked("sta", True)
    for sid, ratio in (("hp", .7), ("mp", 1.), ("sta", 1.)):
        tab._preview_bars[sid].set_value(ratio, f"{ratio*100:.0f}%")
    settle(app)
    assert tab.display_preview.horizontalScrollBar().maximum() == 0
    assert w.grab().save(str(tmp_path / "stat-mixed-locks.png"))
    custom = w.custom_overlay_tab
    items = [dict(x=10+i*50, y=20, w=40, h=40, posX=100, posY=100,
                  name=name, locked=i == 0) for i, name in enumerate(("스노우스톰", "도르카"))]
    config.save_custom_preset("편집 대상", items)
    config.save_custom_preset("선택 대상", items[:1])
    custom._refresh_presets()
    assert custom._apply_preset("편집 대상")
    custom.preset_combo.setCurrentIndex(custom.preset_combo.findData("선택 대상"))
    w._open_setup_feature("custom")
    custom._mgr._timer.stop()
    settle(app)
    assert custom._active_preset == "편집 대상"
    assert custom.overlay_list.topLevelItemCount() == 2
    assert not custom.sel_lock_btn.isEnabled()
    assert custom.lock_all_btn.isEnabled()
    assert w.grab().save(str(tmp_path / "custom-distinct-targets.png"))


@pytest.mark.parametrize("font_size", [12, 20])
@pytest.mark.parametrize("dark", [False, True])
def test_eight_actual_pages_render_without_overflow_or_writes(window, font_size, dark, tmp_path, monkeypatch):
    w, app = window
    palette = app.palette()
    themed = QPalette(palette)
    if dark:
        for role, color in ((QPalette.ColorRole.Window,"#202020"), (QPalette.ColorRole.Base,"#252525"),
                            (QPalette.ColorRole.Button,"#303030"), (QPalette.ColorRole.Text,"#eeeeee"),
                            (QPalette.ColorRole.WindowText,"#eeeeee"), (QPalette.ColorRole.ButtonText,"#eeeeee")):
            themed.setColor(role, QColor(color))
    app.setPalette(themed)
    try:
        for widget in w.findChildren(QWidget):
            widget.setPalette(themed)
            font = widget.font()
            font.setPixelSize(font_size)
            widget.setFont(font)
        from mabinogi_addon.ui import theme
        monkeypatch.setattr(theme, "is_dark", lambda: dark)
        w._apply_tab_styles()
        before = deepcopy(config._read_local_config())
        timers = set(w.findChildren(QTimer))
        for key in ("buff", "debuff", "boss", "stat_bars", "dorcha", "custom", "skillbar", "memo"):
            w._open_setup_feature(key)
            settle(app)
            page = w._combat_pages[key]
            assert page.horizontalScrollBar().maximum() == 0, key
            for control in page.widget().findChildren(QAbstractButton):
                if not control.isVisible():
                    continue
                page.ensureWidgetVisible(control)
                settle(app)
                rect = QRect(control.mapTo(page.viewport(), QPoint()), control.size())
                assert page.viewport().rect().contains(rect), (key, control.text(), rect)
            page.verticalScrollBar().setValue(0)
            settle(app)
            assert w.grab().save(str(tmp_path / f"{key}-{font_size}-{'dark' if dark else 'light'}.png"))
        assert config._read_local_config() == before
        assert set(w.findChildren(QTimer)) == timers
    finally:
        app.setPalette(palette)
