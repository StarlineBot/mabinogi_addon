"""0.53.2(사용자 보고 11-21): 목록을 아래로 내린 뒤 누르면 목록이 튀거나 다른 줄이 골라지던 문제 — 요리·버프·디버프.

- 요리: 목록에서 누를 때마다 dish_list를 다시 채워 스크롤이 0이 되고, 누른 줄이 화면 맨 아래로 튐.
- 버프·디버프: 이름 칸을 고친 뒤 다른 줄을 누르면 포커스 아웃 저장이 목록을 다시 만들어(스크롤 리셋) 바뀐 자리의 다른 줄이 골라짐.
실제 마우스 클릭(QTest)으로 본다.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def _click(view, item):
    rect = view.visualItemRect(item)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
    QApplication.processEvents()


def _in_view(view, item):
    rect = view.visualItemRect(item)
    return rect.top() >= 0 and rect.bottom() <= view.viewport().height()


def _middle_item(view):
    """지금 화면 가운데쯤 보이는 줄."""
    center = view.viewport().rect().center()
    return view.itemAt(center)


def test_cooking_click_keeps_scroll_and_row():
    from mabinogi_addon.ui.cooking_tab import CookingTab
    tab = CookingTab()
    tab.resize(900, 500)
    tab.show()
    tab.category_list.setCurrentRow(0)  # 첫 카테고리(혼합, 80개)
    QApplication.processEvents()
    bar = tab.dish_list.verticalScrollBar()
    assert bar.maximum() > 20
    bar.setValue(bar.maximum() // 2)
    QApplication.processEvents()
    before = bar.value()
    item = _middle_item(tab.dish_list)
    name, y = item.text(), tab.dish_list.visualItemRect(item).y()
    _click(tab.dish_list, item)
    assert tab.selected.name == name
    assert bar.value() == before
    now = next(tab.dish_list.item(i) for i in range(tab.dish_list.count()) if tab.dish_list.item(i).text() == name)
    assert tab.dish_list.visualItemRect(now).y() == y and tab.dish_list.currentItem().text() == name
    # 한 번 더 다른 줄을 눌러도 튀지 않음
    other = tab.dish_list.itemAt(tab.dish_list.viewport().rect().center().x(), y + 40)
    _click(tab.dish_list, other)
    assert tab.selected.name == other.text() and bar.value() == before
    tab.shutdown()


def test_cooking_ingredient_move_shows_target_in_view():
    from mabinogi_addon import cooking
    from mabinogi_addon.ui.cooking_tab import CookingTab
    tab = CookingTab()
    tab.resize(900, 500)
    tab.show()
    tab.select("특대 떡국")
    QApplication.processEvents()
    tab.open_ingredient("떡국 곱빼기")
    QApplication.processEvents()
    target = tab.dish_list.currentItem()
    assert target.text() == "떡국 곱빼기"
    assert _in_view(tab.dish_list, target)
    # 다른 카테고리 요리로(▸ 재료가 다른 조리방법)
    index = cooking.dish_index(cooking.load())
    src = next(d for d in cooking.load() for i in d.recipe
               if cooking.ingredient_dish(i.name, index) and cooking.ingredient_dish(i.name, index).method != d.method)
    ing = next(i.name for i in src.recipe if cooking.ingredient_dish(i.name, index)
               and cooking.ingredient_dish(i.name, index).method != src.method)
    tab.select(src.name)
    tab.open_ingredient(ing)
    QApplication.processEvents()
    cur = tab.dish_list.currentItem()
    assert cur.text() == cooking.ingredient_dish(ing, index).name
    assert _in_view(tab.dish_list, cur)
    tab.shutdown()


def _edit_name_then_click(tab, view):
    tab.resize(900, 420)
    tab.show()
    tab.activateWindow()
    QApplication.setActiveWindow(tab)
    QApplication.processEvents()
    bar = view.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    QApplication.processEvents()
    # 화면에 보이는 줄 하나를 골라 이름을 고치는 중(포커스가 이름 칸)
    first = view.itemAt(view.viewport().rect().center().x(), 5)
    _click(view, first)
    edited_id = view.currentItem().data(Qt.ItemDataRole.UserRole)
    tab.name_edit.setFocus()
    QApplication.processEvents()
    tab.name_edit.setText("고친 이름")
    before = bar.value()
    target = _middle_item(view)
    if target is first:
        target = view.itemAt(view.viewport().rect().center().x(), view.visualItemRect(first).bottom() + 20)
    target_id = target.data(Qt.ItemDataRole.UserRole)
    _click(view, target)
    assert view.currentItem().data(Qt.ItemDataRole.UserRole) == target_id  # 누른 줄
    assert bar.value() == before                                           # 스크롤 그대로
    saved = next(view.item(i) for i in range(view.count()) if view.item(i).data(Qt.ItemDataRole.UserRole) == edited_id)
    assert "고친 이름" in saved.text()                                       # 이름 저장됨
    return edited_id


def _many(monkeypatch, catalog_fn_name, module, count=30):
    """목록이 스크롤되도록 항목을 충분히(카탈로그를 복제)."""
    import dataclasses
    real = getattr(module, catalog_fn_name)
    base = list(real())

    def many():
        out = list(base)
        n = 0
        while len(out) < count:
            src = base[n % len(base)]
            out.append(dataclasses.replace(src, id=f"{src.id}_copy{n}", name=f"{src.name} {n}"))
            n += 1
        return out
    monkeypatch.setattr(module, catalog_fn_name, many)


def test_buff_edit_name_then_click_other_row(monkeypatch):
    from mabinogi_addon.ui import buff_tab
    _many(monkeypatch, "available_catalog", buff_tab)
    tab = buff_tab.BuffTab()
    _edit_name_then_click(tab, tab.buff_list)
    tab.close()


def test_debuff_edit_name_then_click_other_row(monkeypatch):
    from mabinogi_addon.ui import debuff_tab
    _many(monkeypatch, "available_debuff_catalog", debuff_tab)
    tab = debuff_tab.DebuffTab()
    _edit_name_then_click(tab, tab.debuff_list)
    tab.close()


def test_custom_overlay_refresh_keeps_scroll():
    """같은 개수로 다시 그릴 때(저장·이름 갱신 등) 표 스크롤이 맨 위로 가지 않음."""
    from types import SimpleNamespace

    from mabinogi_addon.ui.custom_overlay_tab import CustomOverlayTab
    tab = CustomOverlayTab(SimpleNamespace(is_game_active=lambda: False, is_self_active=lambda: False))
    data = [{"name": f"오버레이{i}", "x": i, "y": i, "w": 10, "h": 10, "scale": 1, "locked": False} for i in range(40)]
    tab._mgr.to_dicts = lambda: data
    tab.resize(900, 300)
    tab.show()
    tab._refresh_overlays()
    QApplication.processEvents()
    bar = tab.overlay_list.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum() // 2)
    before = bar.value()
    tab._refresh_overlays()
    assert bar.value() == before
    tab.close()
