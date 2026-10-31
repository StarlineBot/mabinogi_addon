from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QWidget

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
    w._hide_home()  # 0.28.0: 앱은 홈부터 시작(탐색 구조 명세 12.1). 이 테스트는 탭 화면을 측정한다.
    # These tests measure the editable form. The anchor now intentionally shows guidance instead.
    w.buff_tab.buff_list.setCurrentRow(1)
    assert w.buff_tab.name_edit.isEnabled()
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
        for top, sub in ((0, 2), (0, 3), (0, 4), (0, 5), (0, 6), (0, 7), (0, 8),
                         (1, 0), (2, 0), (2, 1), (2, 2), (3, 0)):
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


@pytest.mark.parametrize("font_pixels", [9, 13, 18])
def test_small_buff_uses_reserved_footer_and_restores_without_drift(window, monkeypatch, font_pixels, tmp_path):
    w, app = window
    d = w.creator_dialogue
    w.setStyleSheet(w.styleSheet() + "\nQWidget {font-size: %dpx;}" % font_pixels)
    for _ in range(8):
        app.processEvents()
    state = layout_state(w, w.buff_tab)
    reserved = w.centralWidget().layout().indexOf(d.footer) >= 0
    fits = state["needed"] + 64 - w.buff_tab.form_panel.layout().contentsMargins().bottom() <= state["viewport"] + (64 if reserved else 0)
    assert d._floating_footer == (not w.buff_tab._columns.stacked and fits)
    # 0.27.0(명세 11절): 상태 줄은 지정 후 요약 줄이라 지정 전엔 숨는다 → 지정 전에도 보이는 영역 안내 줄로 늘어나는 안내를 만든다
    notice = w.buff_tab.region_guide.text()
    # QLabel의 양쪽 내용 배치가 처리된 뒤 반복 전환의 기준 높이를 잰다.
    w.buff_tab.region_guide.setText("status\n" * 80)
    for _ in range(8):
        app.processEvents()
    w.buff_tab.region_guide.setText(notice)
    for _ in range(8):
        app.processEvents()
    state = layout_state(w, w.buff_tab)
    reserved = w.centralWidget().layout().indexOf(d.footer) >= 0
    fits = state["needed"] + 64 - w.buff_tab.form_panel.layout().contentsMargins().bottom() <= state["viewport"] + (64 if reserved else 0)
    baseline_floating = not w.buff_tab._columns.stacked and fits
    assert d._floating_footer == baseline_floating
    height = w.buff_tab.buff_list.height()
    for _ in range(4):
        # 글꼴에 관계없이 실제 내용이 작은 viewport에 들어가지 않는 조건을 만든다.
        w.buff_tab.region_guide.setText("status\n" * 80)
        monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1100, 730)))
        d.refresh()
        for _ in range(6):  # 0.27.0: 영역 묶음 안 안내 줄의 배치 요청이 탭까지 올라오도록
            app.processEvents()
        state = layout_state(w, w.buff_tab)
        assert state["needed"] > state["viewport"] + 64, state
        assert not d._floating_footer, state
        assert w.centralWidget().layout().indexOf(d.footer) >= 0
        assert d.footer.width() == w.centralWidget().width()
        assert w._pages.geometry().bottom() < d.footer.y()
        scroll = w._tracker_tabs.widget(0)
        assert_form_controls_within_viewport(w, w.buff_tab, tmp_path)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        app.processEvents()
        assert d.face.mapTo(w, QPoint()).y() > scroll.mapTo(w, scroll.rect().bottomLeft()).y()
        w.buff_tab.region_guide.setText(notice)
        monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1600, 1100)))
        d.refresh()
        for _ in range(8):
            app.processEvents()
        assert d._floating_footer == baseline_floating, layout_state(w, w.buff_tab)
        assert w.buff_tab.buff_list.height() == height


def layout_state(w, tab):
    scroll = w._tracker_tabs.currentWidget()
    return {
        "needed": tab.layout().heightForWidth(scroll.viewport().width()),
        "viewport": scroll.viewport().height(),
        "frame": w.frameGeometry().height() - w.height(),
        "font": tab.font().toString(),
        "floating": w.creator_dialogue._floating_footer,
        "footer": w.creator_dialogue.footer.geometry().getRect(),
        "inner_width": scroll.widget().width(),
        "viewport_width": scroll.viewport().width(),
        "horizontal_range": scroll.horizontalScrollBar().maximum(),
        "horizontal_value": scroll.horizontalScrollBar().value(),
        "vertical_range": scroll.verticalScrollBar().maximum(),
        "vertical_value": scroll.verticalScrollBar().value(),
    }


def assert_form_controls_within_viewport(w, tab, output):
    viewport = w._tracker_tabs.currentWidget().viewport()
    controls = []
    clipped = []
    for control in tab.form_panel.findChildren(QWidget):
        if not isinstance(control, (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit)):
            continue
        if not control.isVisible():
            continue
        rect = QRect(control.mapTo(viewport, QPoint()), control.size())
        entry = {"type": type(control).__name__, "rect": rect.getRect(),
                 "visible_region": control.visibleRegion().boundingRect().getRect()}
        controls.append(entry)
        if rect.left() < 0 or rect.right() >= viewport.width():
            clipped.append(entry)
    state = {**layout_state(w, tab), "controls": controls, "clipped": clipped}
    assert controls, state
    if clipped:
        screenshot = output / "tracker-horizontal-clipping.png"
        assert w.grab().save(str(screenshot)), state
        state["screenshot"] = str(screenshot)
    assert not clipped, f"clipped controls: {state}"


def assert_form_controls_reachable(w, tab, app, output):
    scroll = w._tracker_tabs.currentWidget()
    state = layout_state(w, tab)
    if state["needed"] <= state["viewport"]:
        assert state["vertical_range"] == 0, state
    else:
        assert state["vertical_range"] > 0, state
    controls = [control for control in tab.form_panel.findChildren(QWidget)
                if isinstance(control, (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit))
                and control.isVisible()]
    assert controls, state
    for control in controls:
        # 칸 전체를 기준으로 스크롤한다. Qt6 ensureWidgetVisible은 입력칸(QLineEdit)이면 커서 영역만 보고,
        # 그게 보이면 칸 테두리가 잘려도 스크롤하지 않는다(0.32.0 디버프 '이 디버프 추적' 자리 이동 뒤 이름 칸 아래 3px).
        # '모든 칸을 온전히 보이게 스크롤할 수 있는가'라는 검사 의도는 같다.
        top_left = control.mapTo(scroll.widget(), QPoint())
        scroll.ensureVisible(top_left.x() + control.width() // 2, top_left.y() + control.height() // 2,
                             control.width() // 2 + 50, control.height() // 2 + 50)
        for _ in range(8):
            app.processEvents()
        rect = QRect(control.mapTo(scroll.viewport(), QPoint()), control.size())
        details = {**layout_state(w, tab), "control": type(control).__name__,
                   "rect": rect.getRect(),
                   "visible_region": control.visibleRegion().boundingRect().getRect()}
        assert scroll.viewport().rect().contains(rect), f"unreachable control: {details}"
    assert_form_controls_within_viewport(w, tab, output)


@pytest.mark.parametrize("font_pixels", [9, 13, 18])
@pytest.mark.parametrize("index", [0, 1])
def test_small_area_layout_is_safe_for_measured_content(window, monkeypatch, font_pixels, index, tmp_path):
    w, app = window
    d = w.creator_dialogue
    w._tracker_tabs.setCurrentIndex(index)
    w.setStyleSheet(w.styleSheet() + "\nQWidget {font-size: %dpx;}" % font_pixels)
    monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1100, 730)))
    d.refresh()
    for _ in range(8):
        app.processEvents()
    tab = (w.buff_tab, w.debuff_tab)[index]
    scroll = w._tracker_tabs.currentWidget()
    state = layout_state(w, tab)
    assert w.height() <= 698, state
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff, state
    assert not scroll.horizontalScrollBar().isVisible(), state
    assert_form_controls_within_viewport(w, tab, tmp_path)
    assert w.rect().contains(d.face.mapTo(w, d.face.rect().bottomRight())), state
    if d._floating_footer:
        assert scroll.verticalScrollBar().maximum() == 0, state
        for item_index in range(tab.form_panel.layout().count()):
            widget = tab.form_panel.layout().itemAt(item_index).widget()
            if widget is not None and widget.isVisible():
                rect = QRect(widget.mapTo(w.centralWidget(), QPoint()), widget.size())
                assert not rect.intersects(d.footer.geometry()), (state, rect.getRect())
    else:
        assert w._pages.geometry().bottom() < d.footer.y(), state


def test_hidden_scrollbar_does_not_hide_a_clipped_control_from_test(window, tmp_path):
    w, app = window
    scroll = w._tracker_tabs.currentWidget()
    control = w.buff_tab.form_panel.findChildren(QLineEdit)[0]
    original = control.pos()
    control.move(original.x() + scroll.viewport().width(), original.y())
    try:
        assert not scroll.horizontalScrollBar().isVisible()
        with pytest.raises(AssertionError, match="clipped"):
            assert_form_controls_within_viewport(w, w.buff_tab, tmp_path)
        assert (tmp_path / "tracker-horizontal-clipping.png").is_file()
    finally:
        control.move(original)


@pytest.mark.parametrize("index", [0, 1])
def test_overwide_columns_stack_and_restore_without_clipping(window, tmp_path, index):
    w, app = window
    w._tracker_tabs.setCurrentIndex(index)
    for _ in range(8):
        app.processEvents()
    tab = (w.buff_tab, w.debuff_tab)[index]
    columns = tab._columns
    left = columns.itemAt(0).widget()
    right = tab.form_panel
    scroll = w._tracker_tabs.currentWidget()
    assert not columns.stacked
    original = (left.minimumWidth(), right.minimumWidth())
    items = tab.buff_list if index == 0 else tab.debuff_list
    notice = tab.status_label.text()
    # QLabel 양쪽 내용의 배치가 확정된 뒤 복원의 기준 높이를 측정한다.
    for text in ("status\n" * 80, notice):
        tab.status_label.setText(text)
        for _ in range(8):
            app.processEvents()
    height = items.height()
    for _ in range(4):
        # Windows QA의 inner 946px에 해당하는 최소 폭을 플랫폼 독립적으로 공급한다.
        left.setMinimumWidth(518)
        right.setMinimumWidth(404)
        for _ in range(8):
            app.processEvents()
        assert columns.stacked
        assert not w.creator_dialogue._floating_footer
        assert scroll.widget().width() == scroll.viewport().width()
        assert_form_controls_reachable(w, tab, app, tmp_path)
        tab.status_label.setText("status\n" * 80)
        for _ in range(8):
            app.processEvents()
        state = layout_state(w, tab)
        assert state["needed"] > state["viewport"], state
        assert state["vertical_range"] > 0, state
        assert_form_controls_reachable(w, tab, app, tmp_path)
        tab.status_label.setText(notice)
        for _ in range(8):
            app.processEvents()
        assert_form_controls_reachable(w, tab, app, tmp_path)
        left.setMinimumWidth(original[0])
        right.setMinimumWidth(original[1])
        for _ in range(8):
            app.processEvents()
        assert not columns.stacked
        assert w.creator_dialogue._floating_footer
        assert items.height() == height


def test_reachability_check_rejects_controls_left_below_viewport(window, tmp_path, monkeypatch):
    w, app = window
    tab = w.buff_tab
    tab._columns.itemAt(0).widget().setMinimumWidth(518)
    tab.form_panel.setMinimumWidth(404)
    tab.status_label.setText("status\n" * 80)
    for _ in range(8):
        app.processEvents()
    scroll = w._tracker_tabs.currentWidget()
    state = layout_state(w, tab)
    assert state["needed"] > state["viewport"] and state["vertical_range"] > 0, state
    assert_form_controls_reachable(w, tab, app, tmp_path)
    scroll.verticalScrollBar().setValue(0)
    monkeypatch.setattr(scroll, "ensureWidgetVisible", lambda *a: None)
    monkeypatch.setattr(scroll, "ensureVisible", lambda *a: None)  # 0.32.0: 도우미가 칸 전체 기준 ensureVisible로 스크롤
    with pytest.raises(AssertionError, match="unreachable control"):
        assert_form_controls_reachable(w, tab, app, tmp_path)


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
    label = w.buff_tab.region_guide  # 0.27.0: 상태 줄은 지정 후 요약 줄(지정 전 숨김)
    original = label.text()
    assert d._floating_footer
    label.setText("여러 줄 상태 안내입니다.\n" * 40)
    for _ in range(6):  # 0.27.0: 영역 묶음으로 몇 단계 깊어져 배치 요청이 탭까지 올라오는 데 루프가 몇 번 더 돈다
        app.processEvents()
    assert not d._floating_footer
    label.setText(original)
    for _ in range(6):  # 0.27.0: 영역 묶음으로 몇 단계 깊어져 배치 요청이 탭까지 올라오는 데 루프가 몇 번 더 돈다
        app.processEvents()
    assert d._floating_footer
