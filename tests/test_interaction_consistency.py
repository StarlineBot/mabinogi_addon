"""Actual product layouts, native previews and save-before-close contracts."""

from pathlib import Path
import os
from zipfile import ZipFile

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

from mabinogi_addon import config, image_io
from mabinogi_addon.ui.stat_overlay import StatBarOverlay
from test_navigation import window
from test_dorcha_reader import crop
from test_custom_autosave import box, denied, select


def test_normal_close_refuses_to_discard_unsaved_custom_edits(window, monkeypatch):
    w, app = window
    tab = w.custom_overlay_tab
    tab._mgr.add(box(1))
    with monkeypatch.context() as patch:
        patch.setattr(config, "save_custom_edit", denied)
        w._force_quit = True
        assert not w.close()
        app.processEvents()
        assert not w._closing
        assert w.isVisible()
        assert w._tracker_tabs.currentWidget() is w._combat_pages["custom"]
        assert len(tab._mgr.overlays()) == 1
        assert tab.save_status.text() == "저장 실패"
        assert tab.error_box.isVisible()
    assert tab.flush_pending()


def test_embedded_stat_preview_has_no_native_window_or_motion(window):
    w, app = window
    tab = w.stat_bars_tab
    w._open_setup_feature("stat_bars")
    app.processEvents()
    for bar in tab._preview_bars.values():
        assert not bar.isWindow()
        assert bar.parent() is tab._preview_groups[bar.stat_id]
        assert bar.parent().parent() is tab.display_preview.widget()
        before = bar.pos()
        bar.set_warning(True, 1)
        bar.set_scale(3)
        assert not bar.warning_active and not bar._warning_timer.isActive()
        assert bar.pos() == before
    tab.scale_spin.setValue(100)
    tab.align_combo.setCurrentIndex(2)
    assert all(bar._scale == 1 and bar._align == "right" for bar in tab._preview_bars.values())
    assert tab._overlays == {}  # Inspecting an output preview never starts capture/output windows.


def test_shared_boss_registration_status_updates_without_polling(window, monkeypatch):
    w, _ = window
    before = config.load_boss_pattern()["enabled"]
    config.save_boss_bar_region(10, 20, 523, 36)
    w.boss_tab.bar_region_changed.emit()
    assert w.stat_bars_tab.boss_region_status.text() == "보스 체력바 · 등록됨"
    assert config.load_boss_pattern()["enabled"] is before
    monkeypatch.setattr(config, "load_boss_bar_region", lambda: pytest.fail("registration status must not poll config"))
    w.stat_bars_tab._apply_login_gate()


@pytest.mark.parametrize("kind", ["resource", "stat", "custom", "custom-error", "buff", "debuff", "boss", "skillbar", "memo"])
def test_actual_layout_render_and_commands(window, kind, tmp_path):
    w, app = window
    out = Path(os.environ.get("INTERACTION_RENDER_DIR", str(tmp_path)))
    out.mkdir(exist_ok=True)
    if kind == "resource":
        d, t = w.dorcha_tab, w.tuarim_tab
        d._region = dict(x=800, y=1000, w=28, h=23)
        t._region = dict(x=900, y=1000, w=58, h=28)
        d._apply_gate()
        t._update_region_label()
        d._cfg.update(enabled=True, showTuarim=True)
        d._update_elements()
        d._set_value(13)
        d._set_percent(95)
        d._show_source(crop("2026-10-16 211456"))
        with ZipFile(Path(__file__).parent / "data/투아림게이지 샘플 모음.zip") as archive:
            frame = cv2.imdecode(np.frombuffer(archive.read("새 폴더 (2)/v04_5789.png"), np.uint8), cv2.IMREAD_COLOR)
        t._show_preview(frame)
        t.value_label.setText("최근 확정: 95%")
        key = "dorcha"
        panel = w.resource_tab
    elif kind == "stat":
        panel = w.stat_bars_tab
        frame = image_io.imread(Path(__file__).parent / "data/stat_bar_shots/hp021_mp100_sta100_007.png")
        panel._show_preview(frame)
        panel.value_label.setText("현재 판독: 생명력 21% · 마나 100% · 스태미나 100%")
        panel._region = dict(x=1000, y=1300, w=frame.shape[1], h=frame.shape[0])
        panel._update_region_label()
        for sid, bar in panel._preview_bars.items():
            bar.set_value(.21 if sid == "hp" else 1)
        key = "stat_bars"
    elif kind.startswith("custom"):
        panel = w.custom_overlay_tab
        config.save_custom_preset("전투", [box(1), dict(box(2), locked=True), box(3)])
        config.save_custom_preset("파티 지원", [box(4)])
        config.save_custom_preset("채집", [box(5)])
        config.save_auto_preset("채집")
        assert panel._apply_preset("전투")
        select(panel, "파티 지원")
        if kind.endswith("error"):
            panel._save_failed(PermissionError("write denied"))
        key = "custom"
    else:
        key = kind
        panel = getattr(w, kind + "_tab")
    assert w._open_setup_feature(key)
    w.creator_dialogue.refresh()
    for _ in range(4):
        app.processEvents()
    scroll = w._combat_pages[key]
    assert scroll.horizontalScrollBar().maximum() == 0
    for control in panel.findChildren(QAbstractButton):
        if not control.isVisible() or control.window() is not w:
            continue
        scroll.ensureWidgetVisible(control)
        app.processEvents()
        rect = QRect(control.mapTo(scroll.viewport(), QPoint()), control.size())
        assert scroll.viewport().rect().contains(rect), (kind, control.text(), rect)
    scroll.verticalScrollBar().setValue(0)
    app.processEvents()
    assert w.grab().save(str(out / f"{kind}.png"))
    if kind.startswith("custom"):
        assert panel.flush_pending()


def test_distribution_stale_result_render(window, tmp_path):
    from mabinogi_addon.market.fee import calc_distribution

    w, app = window
    tab = w.distribution_tab
    tab.price_spin.setValue(8890)
    tab.count_spin.setValue(4)
    sale = 88900000
    result = calc_distribution(sale, 4, True, {})
    tab._show((tab._request_id, result, sale, 4, True, "쿠폰 시세 조회 실패"))
    tab.price_spin.setValue(9000)
    w._tabs.setCurrentWidget(w._convenience_tabs)
    w._convenience_tabs.setCurrentIndex(0)
    for _ in range(4):
        app.processEvents()
    for label in tab.result_area.findChildren(QLabel):
        card = label.parentWidget()
        if card.objectName() == "card":
            assert card.rect().contains(QRect(label.pos(), label.size())), (label.text(), card.size(), label.geometry())
            assert label.height() >= label.fontMetrics().height(), (label.text(), label.height(), label.fontMetrics().height())
    assert tab.result_status.text() == "입력 변경됨 · 아래는 이전 계산 결과"
    out = Path(os.environ.get("INTERACTION_RENDER_DIR", str(tmp_path)))
    out.mkdir(exist_ok=True)
    assert w.grab().save(str(out / "distribution.png"))


def test_long_preset_names_do_not_push_commands_outside_viewport(window):
    w, app = window
    tab = w.custom_overlay_tab
    name = "한글 LongNameWithoutSpaces" * 12
    config.save_custom_preset(name, [box(1)])
    config.save_auto_preset(name)
    assert tab._apply_preset(name)
    select(tab, name)
    assert w._open_setup_feature("custom")
    for _ in range(4):
        app.processEvents()
    scroll = w._combat_pages["custom"]
    assert scroll.horizontalScrollBar().maximum() == 0
    assert tab.active_label.width() > 100
    for control in (tab.save_btn, tab.preset_load_btn, tab.preset_delete_btn, tab.auto_combo, tab.del_all_btn):
        scroll.ensureWidgetVisible(control)
        app.processEvents()
        rect = QRect(control.mapTo(scroll.viewport(), QPoint()), control.size())
        assert scroll.viewport().rect().contains(rect), (control, rect)
