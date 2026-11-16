"""0.50.1 제작 재료 계산기 가로 잘림(사용자 v0.50.0 실화면 11-16) — 더스크 바운드에서 새로고침·'남은 가격' 칸이 창 밖으로 잘렸다.

원인: 윗줄 한 줄에 세트 드롭다운 + 부위 체크 4개 + 공정 + 새로고침 → 탭 최소 폭이 편의기능 탭 내용 폭보다 넓음.
기준: 앱 기본 창 크기에서 두 시리즈 모든 장비, 글자를 키운 상태(16·20px)까지 최소 폭 ≤ 내용 폭, 가로 스크롤 없음,
새로고침 버튼과 표 마지막 칸이 보이는 곳 안.
"""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QWidget

from mabinogi_addon import config
from test_navigation import window  # noqa: F401  (픽스처)


def _open_craft(w, app):
    w._pages.setCurrentWidget(w._tabs)
    page = w._convenience_tabs
    while page is not None and w._tabs.indexOf(page) < 0:
        page = page.parentWidget()
    w._tabs.setCurrentWidget(page)
    titles = [w._convenience_tabs.tabText(i) for i in range(w._convenience_tabs.count())]
    w._convenience_tabs.setCurrentIndex(titles.index("제작 재료 계산기"))
    scroll = w._convenience_tabs.currentWidget()
    for _ in range(5):
        app.processEvents()
    return scroll


@pytest.mark.parametrize("pixels", [None, 16, 20])
def test_craft_tab_fits_content_width_for_every_series_and_item(window, monkeypatch, pixels):  # noqa: F811
    w, app = window
    monkeypatch.setattr(config, "get_nexon_api_key", lambda: "")  # 네트워크 없이(키 없음 상태)
    tab = w.craft_tab
    if pixels:
        for widget in [tab] + tab.findChildren(QWidget):
            font = widget.font()
            font.setPixelSize(pixels)
            widget.setFont(font)
    scroll = _open_craft(w, app)
    failures = []
    for row in range(tab.series_list.count()):
        tab.series_list.setCurrentRow(row)
        model = tab.weapon.model()
        for i in range(model.rowCount()):
            if model.item(i).data(Qt.ItemDataRole.UserRole) is None:
                continue  # 분류 머리
            tab.weapon.setCurrentIndex(i)
            for _ in range(3):
                app.processEvents()
            tab.layout().activate()
            name = tab.current_item().label
            need, have = tab.minimumSizeHint().width(), scroll.viewport().width()
            if need > have or scroll.horizontalScrollBar().maximum():
                failures.append((name, need, have, scroll.horizontalScrollBar().maximum()))
            # 새로고침 버튼·표 마지막 칸 오른쪽 끝이 보이는 곳 안
            right = scroll.viewport().mapToGlobal(QPoint(scroll.viewport().width(), 0)).x()
            refresh = tab.refresh.mapToGlobal(QPoint(tab.refresh.width(), 0)).x()
            header = tab.table.header()
            visible = [c for c in range(header.count()) if not header.isSectionHidden(c)]
            last = header.sectionViewportPosition(visible[-1]) + header.sectionSize(visible[-1])
            table_right = tab.table.viewport().mapToGlobal(QPoint(last, 0)).x()
            if refresh > right or table_right > right or last > tab.table.viewport().width() + 1:
                failures.append((name, "clipped", refresh, table_right, right))
    assert not failures, failures


def test_choice_row_only_for_process_series_and_refresh_on_first_row(window, monkeypatch):  # noqa: F811
    w, app = window
    monkeypatch.setattr(config, "get_nexon_api_key", lambda: "")
    tab = w.craft_tab
    _open_craft(w, app)
    tab.series_list.setCurrentRow(1)  # 더스크 바운드
    app.processEvents()
    assert tab.choice_row.isVisible()
    assert tab.refresh.parentWidget() is tab.weapon.parentWidget()
    assert tab.refresh.y() < tab.choice_row.y()  # 새로고침은 윗줄(세트 드롭다운 줄) 오른쪽 끝
    assert all(box.parentWidget() is tab.choice_row for box in tab.part_checks)
    tab.series_list.setCurrentRow(0)  # 소울 리버레이트
    app.processEvents()
    assert not tab.choice_row.isVisible()


def test_long_material_names_elide_with_tooltip(window, monkeypatch):  # noqa: F811
    w, app = window
    monkeypatch.setattr(config, "get_nexon_api_key", lambda: "")
    tab = w.craft_tab
    _open_craft(w, app)
    tab.series_list.setCurrentRow(1)
    app.processEvents()
    assert tab.table.textElideMode() == Qt.TextElideMode.ElideRight
    items = [tab.table.topLevelItem(r) for r in range(tab.table.topLevelItemCount())]
    rows = [c for c in items if not c.isFirstColumnSpanned()]
    assert rows and all(c.toolTip(0) == c.text(0) for c in rows)
