"""0.31.0 버프·디버프 불투명도와 목록 끌어서 순서 바꾸기(안내·도움말 명세 15절).

끌기는 Qt가 놓을 때 목록 모델의 행을 옮기는 것(rowsMoved)과 같아, 테스트는 모델 행 이동으로 흉내낸다.
"""
import json

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui.buff_tab import ANCHOR_ID, BuffTab
from mabinogi_addon.ui.debuff_tab import DebuffTab
from mabinogi_addon.ui.overlay import BuffOverlay
from test_navigation import window  # noqa: F401  (픽스처)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _ids(widget):
    return [widget.item(row).data(Qt.ItemDataRole.UserRole) for row in range(widget.count())]


def _drag(widget, source, target, app):
    """source 행을 target 자리(그 행 앞)에 놓는다 — QListWidget InternalMove 놓기와 같은 모델 이동."""
    assert widget.model().moveRow(QModelIndex(), source, QModelIndex(), target)
    app.processEvents()  # 놓은 뒤 저장·다시 그리기(QTimer 0)


# ---- 1. 불투명도 ----

def test_opacity_saved_restored_and_clamped(app):
    assert config.load_overlay_opacities() == (100, 100)  # 기본 = 예전과 같음
    tab = BuffTab()
    assert tab.opacity_spin.minimum() == 20 and tab.opacity_spin.maximum() == 100 and tab.opacity_spin.singleStep() == 10
    seen = []
    tab.opacity_changed.connect(seen.append)
    tab.opacity_spin.setValue(60)
    assert seen == [60] and config.load_overlay_opacities() == (60, 100)  # 버프·디버프 따로
    debuff = DebuffTab()
    debuff.opacity_spin.setValue(30)
    assert config.load_overlay_opacities() == (60, 30)
    assert BuffTab().opacity_spin.value() == 60  # 다시 열어도(재실행) 그대로
    for raw, expected in ((0, 20), (5, 20), (150, 100), (55, 50), ("x", 100), (None, 100)):
        data = config._read_local_config()
        data["overlay"] = {"buffOpacity": raw}
        config._write_local_config(data)
        assert config.load_overlay_opacities()[0] == expected  # 0%·범위 밖·잘못된 값은 칸에 맞춤
    tab.deleteLater()
    debuff.deleteLater()


def test_overlay_opacity_applies_immediately_and_survives_lock(app):
    overlay = BuffOverlay()
    overlay.set_opacity(40)
    assert overlay.opacity_percent == 40 and abs(overlay.windowOpacity() - 0.4) < 0.01
    overlay.set_locked(True)
    overlay.set_locked(False)  # 잠금을 풀어도 같은 불투명도
    assert abs(overlay.windowOpacity() - 0.4) < 0.01
    overlay.set_opacity(0)
    assert overlay.opacity_percent == 20  # 0%는 막는다
    overlay.deleteLater()


def test_main_window_wires_opacity_to_overlays(window):
    w, app = window
    w.buff_tab.opacity_spin.setValue(70)
    w.debuff_tab.opacity_spin.setValue(50)
    assert w.buff_overlay.opacity_percent == 70 and w.debuff_overlay.opacity_percent == 50


def test_lock_row_is_three_equal_columns(window):
    w, app = window
    for tab in (w.buff_tab, w.debuff_tab):
        row = [tab.lock_btn, tab.scale_spin, tab.opacity_spin]
        layout = tab.lock_btn.parentWidget().layout()
        top = next(item.layout() for item in (layout.itemAt(i) for i in range(layout.count()))
                   if item.layout() is not None and item.layout().indexOf(tab.opacity_spin) >= 0)
        assert [top.stretch(top.indexOf(widget)) for widget in row] == [1, 1, 1]
        assert tab.opacity_spin.prefix() == "불투명도 " and tab.opacity_spin.suffix() == " %"
        tab.lock_btn.setChecked(True)  # '위치 잠금됨'으로 길어져도 같은 너비
        app.processEvents()
        widths = [widget.width() for widget in row]
        assert max(widths) - min(widths) <= 2, widths
        tab.lock_btn.setChecked(False)


# ---- 2. 끌어서 순서 바꾸기 ----

def test_buff_drag_saves_same_as_arrow_buttons(app):
    tab = BuffTab()
    rows = _ids(tab.buff_list)
    assert rows[0] == ANCHOR_ID and len(rows) >= 4
    a, b = rows[1], rows[2]
    # 끌기: 2번째 일반 버프(b)를 첫 일반 버프(a) 앞으로
    _drag(tab.buff_list, 2, 1, app)
    dragged = list(tab._order)
    assert dragged[:2] == [b, a] and tab._current_id() == b  # 놓은 항목은 선택된 채
    saved = [s.id for s in config.load_buff_settings() if s.id in dragged]
    # ▲로 같은 이동을 한 탭과 저장 결과가 같다
    other = BuffTab()
    other._order = list(dragged)
    other._order[0], other._order[1] = other._order[1], other._order[0]  # 되돌린 상태(a, b)에서
    other._save()
    other._rebuild_list()
    other.buff_list.setCurrentRow(2)
    other._move(-1)
    assert other._order == dragged
    assert [s.id for s in config.load_buff_settings() if s.id in dragged] == saved
    tab.deleteLater()
    other.deleteLater()


def test_anchor_stays_on_top_and_cannot_be_dragged(app):
    tab = BuffTab()
    anchor = tab.buff_list.item(0)
    assert not anchor.flags() & Qt.ItemFlag.ItemIsDragEnabled  # 끌 수 없음
    before = list(tab._order)
    # 다른 항목을 기준 위로 놓아도 기준 바로 아래로
    _drag(tab.buff_list, 3, 0, app)
    assert _ids(tab.buff_list)[0] == ANCHOR_ID
    assert tab._order[0] == before[2] and sorted(tab._order) == sorted(before)  # 이동만(삭제·복제 없음)
    tab.deleteLater()


def test_debuff_drag_and_overlay_order_refresh(window):
    w, app = window
    tab = w.debuff_tab
    rows = _ids(tab.debuff_list)
    emitted = []
    tab.tracking_changed.connect(lambda: emitted.append(list(tab._order)))
    _drag(tab.debuff_list, 0, 3, app)  # 첫 디버프를 셋째 자리로
    assert tab._order[:3] == [rows[1], rows[2], rows[0]] and tab._current_id() == rows[0]
    assert emitted and emitted[-1] == tab._order  # 오버레이 쪽으로 바로 알림(▲▼과 같은 신호)
    stored = [s.id for s in config.load_debuff_settings() if s.id in tab._order]
    assert stored[:3] == [rows[1], rows[2], rows[0]]


def test_drag_mode_is_internal_move_only(app):
    from PySide6.QtWidgets import QAbstractItemView
    for widget in (BuffTab().buff_list, DebuffTab().debuff_list):
        assert widget.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove  # 밖으로 끌어도 삭제·복제 없음
        assert widget.defaultDropAction() == Qt.DropAction.MoveAction
