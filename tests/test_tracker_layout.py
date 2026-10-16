from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui.main_window import MainWindow


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    raw = {"general": {"skipSetup": True}}
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: deepcopy(raw))
    monkeypatch.setattr(config, "_write_local_config", lambda *a, **k: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "테스트"})
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    w = MainWindow()
    monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1600, 1100)))
    w.show()
    app.processEvents()
    yield w, app
    w._force_quit = True
    w.close()


def reserved_layout(w, app):
    """동일 제품 위젯을 이전 전용 하단 배치로 놓아 상대 좌표를 비교한다."""
    d = w.creator_dialogue
    # 이전 배치를 측정하는 동안에만 새 자동 재배치 필터를 분리한다.
    for panel in d._tracker_panels:
        panel.removeEventFilter(d)
    d._floating_footer = False
    for tab in (w.buff_tab, w.debuff_tab):
        tab.form_panel.layout().setContentsMargins(0, 0, 0, 0)
    d.footer.setFixedWidth(w.centralWidget().width())
    w.centralWidget().layout().addWidget(d.footer)
    app.processEvents()
    for panel in d._tracker_panels:
        panel.installEventFilter(d)


@pytest.mark.parametrize("index", [0, 1])
def test_only_list_grows_settings_face_and_rows_stay_fixed(window, index):
    w, app = window
    w._tracker_tabs.setCurrentIndex(index)
    app.processEvents()
    tab = w.buff_tab if index == 0 else w.debuff_tab
    items = tab.buff_list if index == 0 else tab.debuff_list
    reserved_layout(w, app)
    height = items.height()
    face = w.creator_dialogue.face.mapTo(w, QPoint())
    form = tab.form_panel.layout().itemAt(0).widget()
    form_origin = form.mapTo(w, QPoint())
    form_width = form.width()
    row_height = items.sizeHintForRow(0)
    w.creator_dialogue.refresh()
    app.processEvents()
    assert items.height() == height + 64
    assert items.sizeHintForRow(0) == row_height
    assert form.mapTo(w, QPoint()) == form_origin and form.width() == form_width
    assert w.creator_dialogue.face.mapTo(w, QPoint()) == face
    assert w.size().width() == 790 and w.size().height() == 864
    assert w._tracker_tabs.widget(index).verticalScrollBar().maximum() == 0
    assert w.creator_dialogue.footer.width() == 76
    assert w.creator_dialogue.footer.x() > items.mapTo(w.centralWidget(), QPoint()).x() + items.width()


def test_other_pages_keep_reserved_space_and_switches_do_not_drift(window):
    w, app = window
    d = w.creator_dialogue
    row = w.buff_tab.buff_list.currentRow()
    height = w.buff_tab.buff_list.height()
    face = d.face.mapTo(w, QPoint())
    for _ in range(12):
        for top, sub in ((0, 2), (0, 3), (1, 0), (2, 0), (2, 3), (2, 6), (3, 0)):
            w._tabs.setCurrentIndex(top)
            if top == 0:
                w._tracker_tabs.setCurrentIndex(sub)
            elif top == 2:
                w._convenience_tabs.setCurrentIndex(sub)
            app.processEvents()
            assert not d._floating_footer
            assert w.centralWidget().layout().indexOf(d.footer) >= 0
        w._tabs.setCurrentIndex(0)
        w._tracker_tabs.setCurrentIndex(0)
        app.processEvents()
        assert w.buff_tab.buff_list.height() == height
        assert d.face.mapTo(w, QPoint()) == face
        assert w.buff_tab.buff_list.currentRow() == row
    for on in (False, True, False, True):
        w.settings_tab.dialogue_enabled.setChecked(on)
        assert w.buff_tab.buff_list.height() == height


@pytest.mark.parametrize("mode", ["off", "band", "percent"])
def test_debuff_controls_and_small_area_remain_accessible(window, monkeypatch, mode):
    w, app = window
    w._tracker_tabs.setCurrentIndex(1)
    tab = w.debuff_tab
    tab.method_combo.setCurrentIndex(tab.method_combo.findData(mode))
    tab.status_label.setText("게임창이 비활성 상태여서 지정 영역 판독을 기다리고 있습니다. 상태 안내가 여러 줄로 표시되는 경우입니다.")
    monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1100, 730)))
    w.creator_dialogue.refresh()
    app.processEvents()
    assert w.height() <= 698
    assert tab.debuff_list.height() > 0
    assert w._tracker_tabs.widget(1).horizontalScrollBar().maximum() == 0
    assert w.rect().contains(w.creator_dialogue.face.mapTo(w, w.creator_dialogue.face.rect().bottomRight()))
    assert tab.debuff_list.geometry().bottom() < tab.debuff_list.parentWidget().height()


def test_footer_does_not_intercept_lower_left_and_shutdown_removes_filters(window):
    w, app = window
    d = w.creator_dialogue
    # 가상 작업 영역이 실제 offscreen 화면보다 높으므로 Qt 자식의 hit-test를 사용한다.
    hit = w.centralWidget().childAt(QPoint(200, w.centralWidget().height() - 25))
    assert hit is not None
    assert hit is not d.footer and not d.footer.isAncestorOf(hit)
    d.shutdown()
    w.resize(790, 800)
    app.processEvents()
    assert d.closed


def test_small_buff_uses_reserved_footer_and_restores_without_drift(window, monkeypatch):
    w, app = window
    d = w.creator_dialogue
    assert d._floating_footer
    height = w.buff_tab.buff_list.height()
    for _ in range(4):
        monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1100, 730)))
        d.refresh()
        app.processEvents()
        assert not d._floating_footer
        assert w.centralWidget().layout().indexOf(d.footer) >= 0
        assert d.footer.width() == w.centralWidget().width()
        assert w._pages.geometry().bottom() < d.footer.y()
        scroll = w._tracker_tabs.widget(0)
        assert scroll.horizontalScrollBar().maximum() == 0
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        app.processEvents()
        assert d.face.mapTo(w, QPoint()).y() > scroll.mapTo(w, scroll.rect().bottomLeft()).y()
        monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1600, 1100)))
        d.refresh()
        app.processEvents()
        assert d._floating_footer
        assert w.buff_tab.buff_list.height() == height


def test_bubble_does_not_resize_expanded_list_or_expand_visibility_region(window):
    w, app = window
    d = w.creator_dialogue
    seen = []
    d.visibility = lambda hwnd, rects, size: seen.append(rects) or True
    height = w.buff_tab.buff_list.height()
    assert d.request()
    app.processEvents()
    assert d.bubble.isVisible()
    assert w.buff_tab.buff_list.height() == height
    assert len(seen[-1]) == 2
    assert seen[-1][0][2:] == (48, 48)
    assert seen[-1][1][2] <= 310
    d.dismiss()
    app.processEvents()
    assert w.buff_tab.buff_list.height() == height


def test_growing_notice_reevaluates_footer_without_tab_switch(window):
    w, app = window
    d = w.creator_dialogue
    label = w.buff_tab.status_label
    original = label.text()
    assert d._floating_footer
    label.setText("여러 줄 상태 안내입니다.\n" * 40)
    app.processEvents()
    app.processEvents()
    assert not d._floating_footer
    label.setText(original)
    app.processEvents()
    app.processEvents()
    assert d._floating_footer
