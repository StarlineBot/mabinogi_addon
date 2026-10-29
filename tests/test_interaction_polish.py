"""Approved presentation changes must preserve independent state and storage."""

from copy import deepcopy
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QAbstractButton, QPushButton, QWidget
from test_navigation import window
from test_support.scroll_visibility import assert_control_reachable
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
    # 0.27.0(안내·도움말 명세 11.2): 선택/전체 × 잠금/해제/삭제 6버튼 → 선택 삭제·전체 위치 잠금 2개, 비었을 때는 표·버튼 대신 점선 안내
    w, app = window
    tab = w.custom_overlay_tab
    w._open_setup_feature("custom")
    settle(app)
    assert not tab.del_sel_btn.isEnabled() and not tab.lock_all_btn.isEnabled()
    assert tab.empty_hint.isVisible() and not tab.overlay_list.isVisible() and not tab.lock_all_btn.isVisible()
    assert tab.region_btn.isEnabled() and tab.region_btn.isVisible()
    assert not tab.preset_load_btn.isEnabled()
    assert not tab.preset_delete_btn.isEnabled()
    tab._mgr.add(dict(x=1, y=2, w=40, h=40, posX=100, posY=100, name="시험"))
    settle(app)
    assert tab.lock_all_btn.isEnabled() and tab.overlay_list.isVisible() and not tab.empty_hint.isVisible()
    assert not tab.del_sel_btn.isEnabled()
    tab.overlay_list.topLevelItem(0).setSelected(True)
    assert tab.del_sel_btn.isEnabled()
    tab._mgr.clear()
    assert not tab.del_sel_btn.isEnabled() and not tab.lock_all_btn.isEnabled()
    before = deepcopy(config._read_local_config())
    tab.preset_manage_btn.setChecked(True)
    tab.preset_manage_btn.setChecked(False)
    assert config._read_local_config() == before


def test_custom_lock_cell_toggles_one_overlay_and_all_lock_button_follows(window):
    # 0.27.0(명세 11.2 신규 동작): 표의 '위치 잠금' 칸을 누르면 그 오버레이만 잠금/해제, 모두 잠기면 '전체 위치 잠금됨'
    w, app = window
    tab = w.custom_overlay_tab
    for i in range(2):
        tab._mgr.add(dict(x=1 + i, y=2, w=40, h=40, posX=100, posY=100, name=f"시험{i}"))
    tab._mgr.set_locked_all(False)
    first = tab.overlay_list.topLevelItem(0)
    tab.overlay_list.itemClicked.emit(first, 3)
    assert [o.locked for o in tab._mgr.overlays()] == [True, False]
    assert tab.overlay_list.topLevelItem(0).text(3) == "잠금됨" and tab.lock_all_btn.text() == "전체 위치 잠금"
    tab.overlay_list.itemClicked.emit(tab.overlay_list.topLevelItem(0), 0)  # 다른 칸은 잠금을 바꾸지 않음
    assert [o.locked for o in tab._mgr.overlays()] == [True, False]
    tab.lock_all_btn.click()
    assert all(o.locked for o in tab._mgr.overlays()) and tab.lock_all_btn.text() == "전체 위치 잠금됨"
    tab._mgr.clear()


def test_custom_delete_confirmation_identifies_overlay_not_preset(window, monkeypatch):
    w, app = window
    tab = w.custom_overlay_tab
    tab._mgr.add(dict(x=1, y=2, w=40, h=40, posX=100, posY=100, name="삭제 확인 대상"))
    tab.overlay_list.topLevelItem(0).setSelected(True)
    confirmations = []
    monkeypatch.setattr(tab, "_confirm", lambda title, text: confirmations.append((title, text)) or False)
    tab._on_delete_selected()  # 0.27.0: '전체 삭제'는 없앰(명세 11.2 — 버튼 2개)
    assert len(confirmations) == 1
    assert all("삭제 확인 대상" in text for _, text in confirmations)
    assert all("오버레이" in title for title, _ in confirmations)
    assert tab.overlay_list.topLevelItemCount() == 1


def test_resource_both_displays_off_keeps_independent_alert(window):
    # 0.27.0(명세 11.2): 표시 미리보기는 없앴고, 투아림 알림 사용은 '투아림 알림' 구역으로 옮겼다(표시와 독립)
    w, app = window
    w._open_setup_feature("dorcha")
    w.dorcha_tab.enable.setChecked(False)
    w.resource_tab.percent_chk.setChecked(False)
    w.tuarim_tab.enable.setChecked(True)
    settle(app)
    assert not w.dorcha_tab.preview_scroll.isVisible()
    assert w.tuarim_tab.enable.parentWidget() is w.resource_tab.tuarim_alert_box
    assert w.tuarim_tab.enable.isVisible()
    assert config.load_tuarim()["enabled"]
    assert not w.dorcha_tab.enable.isChecked()
    assert not w.resource_tab.percent_chk.isChecked()


def test_stat_individual_locks_are_public_without_saving_on_logout(window, monkeypatch):
    w, app = window
    tab = w.stat_bars_tab
    before = deepcopy(config._read_local_config())
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    tab._apply_login_gate()
    assert all(button.isEnabled() for button in tab.bar_lock_buttons.values())
    assert not tab.collect_chk.isEnabled() and tab.auto_find_btn.isEnabled()
    assert config._read_local_config() == before


def test_seeded_lock_and_preset_states_render(window, tmp_path):
    w, app = window
    tab = w.stat_bars_tab
    w._open_setup_feature("stat_bars")
    tab._set_bar_locked("hp", True)
    tab._set_bar_locked("mp", False)
    tab._set_bar_locked("sta", True)
    # 0.27.0(명세 11.2): 표시 미리보기 없음. 잠금은 하나 — 바마다 다르면 '전체 위치 잠금'(모두 잠겨야 '전체 위치 잠금됨', 0.28.1 명세 13.3)
    assert not tab.lock_btn.isChecked() and tab.lock_btn.text() == "전체 위치 잠금"
    tab.lock_btn.click()
    assert all(b.isChecked() for b in tab.bar_lock_buttons.values()) and tab.lock_btn.text() == "전체 위치 잠금됨"
    tab._set_bar_locked("mp", False)
    settle(app)
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
    assert not custom.del_sel_btn.isEnabled()
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
                assert_control_reachable(control, app, key)
            page.verticalScrollBar().setValue(0)
            settle(app)
            assert w.grab().save(str(tmp_path / f"{key}-{font_size}-{'dark' if dark else 'light'}.png"))
        assert config._read_local_config() == before
        assert set(w.findChildren(QTimer)) == timers
    finally:
        app.setPalette(palette)
