"""요리 계산기(docs/cooking-spec.md 8절) — 데이터·검색 필터·재료 이동·상세 그림·게임 위 바."""
from __future__ import annotations

import itertools
import json

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtWidgets import QLabel

from mabinogi_addon import config, cooking
from scripts import build_cookings


@pytest.fixture(autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---- 데이터(2·4절) ----
SAMPLE_JS = """const cookings = [
  {
    originName: "Sashimi Rice Bowl",
    localName: "모둠회덮밥",
    isCatering: true,
    localCookingType: "혼합",
    localRecipe: "모둠생선회(50%) 밥(20%) 야채 모둠(40%)",
    status: [
      {
        name: "생명력",
        value: 35
      },
      {
        name: "마나",
        value: 25
      },
    ],
  },
  {
    localName: "이벤트 케이크",
    isCatering: true,
    localCookingType: "",
    localRecipe: ""
  },
  {
    localName: "개인 요리",
    isCatering: false,
    localCookingType: "굽기",
    localRecipe: "밀가루(100%)"
  },
  {
    localName: "깨진 요리",
    isCatering: true,
    localCookingType: "굽기",
    localRecipe: "밀가루 100%"
  }
]
module.exports = {
  cookings
}
"""


def test_parse_js_and_recipe_from_bot_format():
    raw = build_cookings.parse_js(SAMPLE_JS)
    dishes, stats = build_cookings.select(raw)
    assert stats == {"catering": 3, "no_method": 1, "bad": 1, "kept": 1}
    assert dishes == [{"name": "모둠회덮밥", "method": "혼합",
                       "recipe": [{"name": "모둠생선회", "ratio": 50}, {"name": "밥", "ratio": 20},
                                  {"name": "야채 모둠", "ratio": 40}],
                       "status": [{"name": "생명력", "value": 35}, {"name": "마나", "value": 25}]}]
    assert build_cookings.parse_recipe("밥(20%) 이상한 글") is None
    assert build_cookings.parse_recipe("우유(12.5%)") == [{"name": "우유", "ratio": 12.5}]


def test_build_summary_survives_cp1252_console(tmp_path):
    """Windows 러너 stdout이 cp1252여도 요약 줄을 찍고 0으로 끝난다(QA 반려 11-19 — 예외로 '실패' 경고가 났었음)."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(build_cookings.__file__).resolve().parents[1]
    source = tmp_path / "cookings.js"
    raw = json.loads(cooking.data_path().read_text(encoding="utf-8"))["dishes"]
    items = [{"localName": d["name"], "isCatering": True, "localCookingType": d["method"],
              "localRecipe": " ".join(f"{r['name']}({r['ratio']}%)" for r in d["recipe"]), "status": d["status"]}
             for d in raw]
    source.write_text("const cookings = " + json.dumps(items, ensure_ascii=False, indent=2) + "\nmodule.exports = { cookings }\n",
                      encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "scripts.build_cookings", "--source", str(source), "--out",
                             str(tmp_path / "out.json")], cwd=root, capture_output=True, check=False,
                            env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"387" in result.stdout and (tmp_path / "out.json").is_file()


def test_build_refuses_too_few_dishes(tmp_path):
    with pytest.raises(ValueError, match="최소"):
        build_cookings.build(SAMPLE_JS, tmp_path / "c.json")
    assert not (tmp_path / "c.json").exists()


def test_generated_json_shape_and_count():
    raw = json.loads(cooking.data_path().read_text(encoding="utf-8"))
    assert raw["source"] == build_cookings.URL
    assert len(raw["dishes"]) == 387 >= build_cookings.MIN_COUNT  # 11-19: 단체 466 중 조리방법 없는 79개 제외
    for d in raw["dishes"]:
        assert set(d) == {"name", "method", "recipe", "status"} and d["method"] and d["recipe"]
        assert all(r["ratio"] > 0 and r["name"] for r in d["recipe"])
    dishes = cooking.load()
    assert len(dishes) == 387 and len({d.name for d in dishes}) == 387
    assert set(cooking.categories(dishes)) == set(cooking.CATEGORIES)  # 모르는 조리방법 없음


def test_ratio_normalized_by_sum():
    dish = {d.name: d for d in cooking.load()}["모둠회덮밥"]
    assert [i.ratio for i in dish.recipe] == [50, 20, 40]
    assert [round(r * 100, 2) for r in cooking.ratios(dish.recipe)] == [45.45, 18.18, 36.36]
    assert [round(b * 100, 2) for b in cooking.boundaries(dish.recipe)] == [45.45, 63.64]


# ---- 검색 필터(3절) ----
def test_search_three_kinds_ignore_spaces():
    dishes = cooking.load()
    assert "모둠회덮밥" in cooking.search(dishes, "요리 이름", "모둠 회덮밥")
    assert "모둠회덮밥" in cooking.search(dishes, "재료", "야채모둠")
    by_stat = cooking.search(dishes, "능력치", "마법공격력")
    assert "모둠회덮밥" in by_stat
    assert all(any(n == "마법공격력" for n, _ in d.status) for d in dishes if d.name in by_stat)
    assert cooking.search(dishes, "능력치", "마법") == set()  # 능력치는 이름 정확히
    assert cooking.search(dishes, "재료", "   ") is None    # 빈 검색 = 필터 없음
    counts = cooking.category_counts(dishes, cooking.search(dishes, "재료", "밥"))
    assert counts["혼합"] == 7 and counts["삶기"] == 0 and sum(counts.values()) == 20


def _items(widget):
    return [widget.item(i) for i in range(widget.count())]


@pytest.mark.parametrize(("kind", "query"), [("요리 이름", "덮밥"), ("재료", "밥"), ("능력치", "마법공격력")])
def test_tab_filter_counts_grey_and_keeps_selection(kind, query):
    from mabinogi_addon.ui.cooking_tab import _DISH, CookingTab
    tab = CookingTab()
    tab.select("모둠회덮밥")
    tab.kind.setCurrentText(kind)
    if kind == "능력치":
        tab.stat.setCurrentIndex(tab.stat.findData(query))
    else:
        tab.query.setText(query)
    hits = cooking.search(cooking.load(), kind, query)
    counts = cooking.category_counts(cooking.load(), hits)
    assert tab.count.text() == f"{len(hits)}개 요리"
    for item in _items(tab.category_list)[1:]:  # 맨 위 '즐겨찾기'(0.55.0)는 따로 확인
        n = counts[item.data(_DISH)]
        assert item.text().removeprefix("★ ") == f"{item.data(_DISH)} ({n})"
        assert bool(item.flags() & Qt.ItemFlag.ItemIsEnabled) == (n > 0)  # 0개 카테고리는 회색·못 고름
    for item in _items(tab.dish_list):
        assert bool(item.flags() & Qt.ItemFlag.ItemIsEnabled) == (item.data(_DISH) in hits)
    assert tab.selected.name == "모둠회덮밥"
    # 검색어를 지워도 선택은 그대로, 회색·숫자 없음
    tab.query.setText("")
    tab.kind.setCurrentText("요리 이름")
    assert tab.selected.name == "모둠회덮밥"
    for item in _items(tab.category_list)[1:]:  # 숫자 없음, 요리가 하나도 없는 카테고리(반죽)만 회색
        assert item.text() == item.data(_DISH)
        assert bool(item.flags() & Qt.ItemFlag.ItemIsEnabled) == (item.text() != "반죽")
    assert tab.count.text() == "387개 요리"
    tab.shutdown()


def test_ingredient_search_highlights_row():
    from mabinogi_addon.ui.cooking_tab import CookingTab
    tab = CookingTab()
    tab.kind.setCurrentText("재료")
    tab.query.setText("밥")
    tab.select("모둠회덮밥")
    assert [row.property("searchHit") for row in tab.ingredient_rows] == [False, True, False]
    tab.kind.setCurrentText("능력치")
    tab.stat.setCurrentIndex(tab.stat.findData("마나"))
    assert "font-weight:800;'>마나 +25" in tab.stats.text()
    tab.shutdown()


# ---- 재료 이동·되돌아가기 ----
def test_detail_order_buttons_right_under_gauge():
    """사용자 피드백 11-19: 재료 → 비율 그림 → 두 버튼(그림 폭) → 능력치, 조리방법·능력치는 타이틀보다 작고 본문보다 큼."""
    from PySide6.QtGui import QFontInfo

    from mabinogi_addon.ui.cooking_tab import GAUGE_VIEW_W, CookingTab
    tab = CookingTab()
    tab.select("모둠회덮밥")
    widgets = [tab.detail_layout.itemAt(i).widget() for i in range(tab.detail_layout.count())]
    at = widgets.index(tab.gauge)
    assert widgets[at + 1] is tab.overlay_buttons
    from mabinogi_addon.ui.widgets import divider
    assert type(widgets[at + 2]) is type(divider()) and widgets[at + 2].height() <= 1  # 구역 구분선
    assert widgets[at + 3].text() == "능력치" and widgets[at + 4] is tab.stats
    titles = [w.text() for w in widgets if isinstance(w, QLabel) and w.text() in
              ("재료", "비율 — 점선 위치에서 농도 조절을 멈추기", "능력치")]
    assert len(titles) == 3
    # 구역: [이름·조리방법] | [재료] | [비율 그림 + 버튼] | [능력치] — 제목마다 바로 앞이 구분선
    for w in widgets:
        if isinstance(w, QLabel) and w.text() in titles:
            assert widgets[widgets.index(w) - 1].maximumHeight() == 1
    assert tab.overlay_btn.parent() is tab.overlay_buttons and tab.lock_btn.parent() is tab.overlay_buttons
    assert tab.overlay_buttons.width() == GAUGE_VIEW_W == tab.gauge.pixmap().width()
    for pixels in (None, 20):  # 기본·큰 글꼴 모두 타이틀 > 조리방법·능력치 > 본문
        if pixels:
            font = tab.font()
            font.setPixelSize(pixels)
            tab.setFont(font)
        widgets = [tab.detail_layout.itemAt(i).widget() for i in range(tab.detail_layout.count())]
        body = QFontInfo(tab.font()).pixelSize()
        title = next(w for w in widgets if w is not None and getattr(w, "text", lambda: "")() == "모둠회덮밥")
        stats_title = widgets[widgets.index(tab.stats) - 1]
        size = [QFontInfo(w.font()).pixelSize() for w in (title, tab.method_label, tab.stats, stats_title)]
        assert size[0] > size[1] == size[2] > size[3] > body  # 타이틀 > 조리방법 = 능력치 값 > 구역 제목 > 본문
        assert body == (pixels or body)
    tab.shutdown()


def test_history_back_in_order_and_no_cycle():
    h = cooking.History()
    h.enter("A", "B")
    h.enter("B", "C")
    h.enter("C", "D")
    assert [h.back(), h.back(), h.back(), h.back()] == ["C", "B", "A", None]
    h.enter("A", "B")
    h.enter("B", "A")  # 같은 요리 재등장 → 되감기(쌓이지 않음)
    assert len(h) == 0
    h.enter("A", "A")
    assert len(h) == 0


def test_tab_ingredient_navigation_three_levels():
    from mabinogi_addon.ui.cooking_tab import CookingTab
    tab = CookingTab()
    chain = ["특대 떡국", "떡국 곱빼기", "떡국", "하얀 떡"]  # 재료 요리를 따라 세 번 들어간다
    tab.select(chain[0])
    for before, target in itertools.pairwise(chain):
        tab.open_ingredient(target)
        assert tab.selected.name == target
        assert tab.back_btn is not None and tab.back_btn.text() == f"← {before}"
    for expected in reversed(chain[:-1]):
        tab.back_btn.click()
        assert tab.selected.name == expected
    assert tab.back_btn is None
    tab.open_ingredient("모둠생선회")
    item = next(i for i in _items(tab.dish_list) if i.text() == "모둠회덮밥")
    tab._dish_clicked(item)  # 목록에서 직접 고름 → 기록 삭제
    assert len(tab.history) == 0 and tab.back_btn is None
    tab.shutdown()


# ---- 그림(5·6절) ----
def test_detail_pixmap_fills_gauge_by_ratio():
    from mabinogi_addon.ui import cooking_gauge as g
    dish = {d.name: d for d in cooking.load()}["모둠회덮밥"]
    image = g.detail_pixmap(dish).toImage()
    x0, y0 = g.PANEL[:2]
    gx0, gy0, gx1, gy1 = g.GAUGE
    width, mid = gx1 - gx0, (gy0 + gy1) // 2 - y0

    def at(fraction):
        return image.pixelColor(round(gx0 + width * fraction) - x0, mid)
    assert at(0.2) == QColor(g.COLORS[0]) and at(0.55) == QColor(g.COLORS[1]) and at(0.9) == QColor(g.COLORS[2])
    dash_x = round(gx0 + width * cooking.boundaries(dish.recipe)[0]) - x0
    column = [image.pixelColor(dash_x + dx, y).lightness() for dx in (-1, 0, 1) for y in range(g.DASH_TOP - y0, gy0 - y0)]
    assert max(column) == 255  # 바 위 버튼 줄까지 흰 점선
    empty = g.detail_pixmap(None).toImage()
    assert empty.pixelColor(round(gx0 + width * 0.2) - x0, mid) == QColor(0, 0, 0)


def test_overlay_size_render_and_lock():
    from mabinogi_addon.ui.cooking_gauge import (
        BAR_H,
        BAR_W,
        DASH_FACTOR,
        CookingBarOverlay,
    )
    dish = {d.name: d for d in cooking.load()}["모둠회덮밥"]
    o = CookingBarOverlay()
    o.set_dish(dish)
    assert o.bar_size() == (BAR_W, BAR_H) == (245, 10)
    assert (o.width(), o.height()) == (245, BAR_H * (DASH_FACTOR + 1))
    image = o.grab().toImage()
    assert image.pixelColor(30, o.height() - 5) == QColor("#EBC351")
    o.set_scale(2.0)
    assert o.bar_size() == (490, 20)
    o.wheelEvent(QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                             Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
    assert o.scale == 2.05
    o.set_locked(True)
    assert o.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    o.set_locked(False)
    assert not o.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    o.close()


class _Watcher:
    def __init__(self):
        self.game = True

    def is_game_active(self):
        return self.game

    def is_self_active(self):
        return False


def test_overlay_position_scale_saved_and_restored_and_hidden_without_game():
    from mabinogi_addon.ui.cooking_tab import CookingTab
    watcher = _Watcher()
    tab = CookingTab(watcher)
    tab.select("모둠회덮밥")
    tab.overlay_btn.click()
    o = tab.overlay
    assert o.isVisible() and o.dish.name == "모둠회덮밥" and o.scale == 1.0
    o.move(123, 456)
    o.moved.emit()
    o.set_scale(1.5)
    o.scaled.emit()
    tab.lock_btn.click()
    assert config.load_cooking_overlay() == {"pos": {"x": o.x(), "y": o.y()}, "scale": 1.5, "locked": True}
    watcher.game = False
    tab._sync_overlay()
    assert not o.isVisible()  # 게임이 앞에 없으면 숨김
    tab.select("모둠생선회")
    assert o.dish.name == "모둠생선회"  # 상세 요리가 바뀌면 바도
    tab.shutdown()

    again = CookingTab(watcher)
    watcher.game = True
    again.select("모둠회덮밥")
    again.set_overlay(True)
    assert (again.overlay.x(), again.overlay.y()) == (o.x(), o.y())
    assert again.overlay.scale == 1.5 and again.overlay.locked
    again.shutdown()


def test_overlay_config_rejects_bad_values():
    config.save_cooking_overlay(pos={"x": "a", "y": 1}, scale=9, locked="yes")
    assert config.load_cooking_overlay() == {"pos": None, "scale": None, "locked": False}


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_first_bar_is_physical_245x10_for_display_scale(monkeypatch, dpr):
    """첫 사용(저장 배율 없음): Windows 배율과 무관하게 물리 픽셀 245×10(±1) — 게임 요리창 바 측정값(QA 반려 11-19)."""
    from mabinogi_addon.ui import cooking_tab, dpi
    monkeypatch.setattr(dpi, "screen_scale", lambda: dpr)
    tab = cooking_tab.CookingTab()
    tab.select("모둠회덮밥")
    tab.set_overlay(True)
    w, h = tab.overlay.bar_size()
    assert abs(w * dpr - 245) <= 1 and abs(h * dpr - 10) <= 1
    tab.shutdown()


def test_saved_scale_kept_regardless_of_display_scale(monkeypatch):
    from mabinogi_addon.ui import cooking_tab, dpi
    monkeypatch.setattr(dpi, "screen_scale", lambda: 1.5)
    config.save_cooking_overlay(scale=1.2)
    tab = cooking_tab.CookingTab()
    tab.select("모둠회덮밥")
    tab.set_overlay(True)
    assert tab.overlay.scale == 1.2
    tab.shutdown()


def test_bar_drags_freely_without_grid(monkeypatch):
    """사용자 결정 11-19: 격자 맞춤을 켜도 요리 바는 1px 단위로 자유 이동, 안내선 없음(다른 오버레이는 그대로 격자)."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    from mabinogi_addon.ui import grid
    from mabinogi_addon.ui.cooking_gauge import CookingBarOverlay
    config.save_general_flag("gridSnap", True)
    config.save_grid_size(32)
    assert grid.enabled() and grid.size() == 32
    shown = []
    monkeypatch.setattr(grid, "show_guide", lambda *a, **k: shown.append(a))
    o = CookingBarOverlay()
    o.move(400, 300)
    moved = []
    o.moved.connect(lambda: moved.append(o.pos()))

    def mouse(kind, gx, gy):
        button = Qt.MouseButton.LeftButton
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
        return QMouseEvent(kind, QPointF(10, 10), QPointF(gx, gy), button, buttons, Qt.KeyboardModifier.NoModifier)
    o.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, 410, 310))
    o.mouseMoveEvent(mouse(QEvent.Type.MouseMove, 415, 313))
    o.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, 415, 313))
    assert (o.x(), o.y()) == (405, 303)  # 스냅 없이 정확히 (+5, +3)
    assert shown == [] and moved == [o.pos()]
    o.close()


class _Fg:
    """전경 창 흉내: 'game' · 'self'(애드온) · 'other'."""
    def __init__(self):
        self.front = "game"

    def is_game_active(self):
        return self.front == "game"

    def is_self_active(self):
        return self.front == "self"


def test_bar_shows_only_when_game_or_cooking_tab_front():
    """사용자 결정 11-19: 다른 오버레이처럼 게임이 앞일 때만 — 애드온이 앞이면 요리 탭이 보일 때만, 끄는 중엔 유지."""
    from PySide6.QtWidgets import QTabWidget

    from mabinogi_addon.ui.cooking_tab import CookingTab
    fg = _Fg()
    tabs = QTabWidget()
    tab = CookingTab(fg)
    tabs.addTab(tab, "요리")
    tabs.addTab(QLabel("다른"), "다른")
    tabs.show()
    tab.select("모둠회덮밥")
    tab.set_overlay(True)
    o = tab.overlay

    def shown():
        tab._sync_overlay()
        return o.isVisible()
    assert shown()                      # 게임 앞
    fg.front = "self"
    assert shown()                      # 애드온 앞 + 요리 탭 보임(위치 맞추는 중)
    tabs.setCurrentIndex(1)
    assert not shown()                  # 애드온 앞 + 다른 탭
    o._drag = QPoint(1, 1)
    assert shown()                      # 끄는 중엔 숨지 않음
    o._drag = None
    tabs.hide()                         # 트레이로 숨김
    tabs.setCurrentIndex(0)
    assert not shown()
    fg.front = "other"
    tabs.show()
    assert not shown()                  # 다른 프로그램 앞
    fg.front = "game"
    tabs.hide()
    assert shown()                      # 앱이 숨어 있어도 게임 앞이면 보임
    tab.shutdown()
    tabs.close()


def test_bar_overlay_excluded_from_reading_capture():
    """QA 반려 11-20: 바가 판독 캡처에 찍히면 요리창 게이지 자리를 덮어 자동 찾기가 실패 — 캡처 제외 목록에 있어야 함."""
    from mabinogi_addon.ui import overlay_capture
    from mabinogi_addon.ui.cooking_gauge import CookingBarOverlay
    o = CookingBarOverlay()
    assert "CookingBarOverlay" in overlay_capture.OVERLAYS and overlay_capture.is_overlay(o)
    o.close()


# ---- 능력치 검색 정렬·★ (사용자 결정 11-21, 0.54.0) ----
def _d(name, method, **stats):
    return cooking.Dish(name, method, (cooking.Ingredient("물", 1),), tuple(stats.items()))


def test_stat_ranked_and_top_pure():
    dishes = [_d("가", "굽기", 생명력=30), _d("나", "굽기", 생명력=50), _d("다", "굽기"), _d("라", "굽기", 생명력=50),
              _d("마", "굽기", 마나=10), _d("바", "혼합", 생명력=50)]
    order = [(d.name, v) for d, v in cooking.ranked(dishes[:5], "생명력")]
    assert order == [("나", 50), ("라", 50), ("가", 30), ("다", None), ("마", None)]  # 높은 순·같으면 이름순, 없는 건 이름순 아래
    assert cooking.top_dishes(dishes, "생명력") == {"나", "라", "바"}                 # 전체 최고 동점 모두
    assert cooking.top_dishes(dishes, "행운") == set()
    assert [v for _d_, v in cooking.ranked([_d("x", "삶기")], "생명력")] == [None]     # 능력치 없는 카테고리
    assert cooking.stat_value(_d("y", "굽기", 생명력=-12), " 생명 력") == -12


def test_tab_stat_search_orders_values_and_stars():
    from mabinogi_addon.ui.cooking_tab import _DISH, _VALUE, CookingTab
    tab = CookingTab()
    tab.kind.setCurrentText("능력치")
    tab.stat.setCurrentIndex(tab.stat.findData("생명력"))
    cats = {tab.category_list.item(i).data(_DISH): tab.category_list.item(i) for i in range(tab.category_list.count())}
    assert cats["굽기"].text() == "★ 굽기 (60)"                    # 전체 최고 300이 굽기
    assert not cats["혼합"].text().startswith("★")
    tab.category_list.setCurrentItem(cats["굽기"])
    rows = [tab.dish_list.item(i) for i in range(tab.dish_list.count())]
    assert rows[0].text() == "★ 까맣게 구워진 드래곤 심장" and rows[0].data(_VALUE) == "+300"
    assert sum(r.text().startswith("★") for r in rows) == 1
    values = [float(r.data(_VALUE)) for r in rows if r.data(_VALUE)]
    assert values == sorted(values, reverse=True)
    greys = [r for r in rows if not r.data(_VALUE)]
    assert greys and all(not (r.flags() & Qt.ItemFlag.ItemIsEnabled) for r in greys)
    assert rows[-len(greys):] == greys and [r.text() for r in greys] == sorted(r.text() for r in greys)
    # 다른 검색 종류·검색 없음은 이름순 그대로(수치·별 없음)
    tab.kind.setCurrentText("요리 이름")
    rows = [tab.dish_list.item(i) for i in range(tab.dish_list.count())]
    assert [r.text() for r in rows] == sorted(r.text() for r in rows)
    assert not any(r.data(_VALUE) for r in rows) and not any(r.text().startswith("★") for r in rows)
    assert not any(tab.category_list.item(i).text().startswith("★") for i in range(tab.category_list.count()))
    tab.shutdown()


def test_tab_stat_change_scrolls_to_top():
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.cooking_tab import _DISH, CookingTab
    tab = CookingTab()
    tab.resize(760, 500)
    tab.show()
    tab.kind.setCurrentText("능력치")
    tab.stat.setCurrentIndex(tab.stat.findData("생명력"))
    row = next(i for i in range(tab.category_list.count()) if tab.category_list.item(i).data(_DISH) == "굽기")
    tab.category_list.setCurrentRow(row)
    QApplication.processEvents()
    bar = tab.dish_list.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert bar.value() > 0
    tab.stat.setCurrentIndex(tab.stat.findData("행운"))  # 능력치를 바꾸면 순서가 바뀌므로 맨 위
    assert bar.value() == 0
    tab.shutdown()


def test_tab_name_and_ingredient_search_puts_hits_on_top():
    """사용자 결정 11-21: 이름·재료로 찾을 때도 맞는 요리는 위(이름순), 안 맞는 요리는 회색 아래(이름순), 수치·★ 없음."""
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.cooking_tab import _DISH, _VALUE, CookingTab
    tab = CookingTab()
    tab.resize(760, 500)
    tab.show()
    for kind, query in (("재료", "밥"), ("요리 이름", "버거")):
        tab.kind.setCurrentText(kind)
        tab.query.setText(query)
        row = next(i for i in range(tab.category_list.count()) if tab.category_list.item(i).data(_DISH) == "혼합")
        tab.category_list.setCurrentRow(row)
        QApplication.processEvents()
        rows = [tab.dish_list.item(i) for i in range(tab.dish_list.count())]
        hit = [bool(r.flags() & Qt.ItemFlag.ItemIsEnabled) for r in rows]
        n = sum(hit)
        assert 0 < n < len(rows) and hit == [True] * n + [False] * (len(rows) - n)   # 맞는 것 위, 회색 아래
        assert [r.text() for r in rows[:n]] == sorted(r.text() for r in rows[:n])
        assert [r.text() for r in rows[n:]] == sorted(r.text() for r in rows[n:])
        assert not any(r.data(_VALUE) or r.text().startswith("★") for r in rows)
    bar = tab.dish_list.verticalScrollBar()
    tab.query.setText("")
    bar.setValue(bar.maximum())
    tab.query.setText("버")                       # 검색어가 바뀌면 맨 위
    assert bar.value() == 0
    tab.shutdown()


# ---- 0.54.0 QA 반려: 선택 줄 글자색은 스타일이 정한다(Windows 11 = 옅은 칸 + Text 글자) ----
def _stat_tab():
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.cooking_tab import _DISH, CookingTab
    tab = CookingTab()
    tab.resize(760, 500)
    tab.show()
    tab.kind.setCurrentText("능력치")
    tab.stat.setCurrentIndex(tab.stat.findData("마법공격력"))
    row = next(i for i in range(tab.category_list.count()) if tab.category_list.item(i).data(_DISH) == "혼합")
    tab.category_list.setCurrentRow(row)
    tab.select(tab.dish_list.item(0).data(_DISH))
    QApplication.processEvents()
    return tab


def _light_selection_style():
    """선택을 Highlight로 채우지 않고 옅은 칸 + Text 글자로 그리는 스타일(Windows 11 흉내) + drawControl 기록."""
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QProxyStyle, QStyle, QStyleFactory

    class Style(QProxyStyle):
        def __init__(self):
            super().__init__(QStyleFactory.create("Fusion"))
            self.calls = []

        def drawControl(self, element, option, painter, widget=None):
            if element == QStyle.ControlElement.CE_ItemViewItem:
                self.calls.append((option.text, bool(option.state & QStyle.StateFlag.State_Selected)))
                if option.state & QStyle.StateFlag.State_Selected:
                    from PySide6.QtWidgets import QStyleOptionViewItem
                    light = QStyleOptionViewItem(option)
                    light.state &= ~QStyle.StateFlag.State_Selected
                    painter.fillRect(option.rect, QColor(225, 222, 235))  # 옅은 선택 칸
                    pal = QPalette(light.palette)
                    pal.setColor(QPalette.ColorRole.Text, QColor(20, 20, 20))
                    light.palette = pal
                    light.backgroundBrush = QColor(0, 0, 0, 0)
                    return super().drawControl(element, light, painter, widget)
            return super().drawControl(element, option, painter, widget)
    return Style()


def test_selected_value_row_text_drawn_by_style_and_visible_on_light_selection():
    from PySide6.QtGui import QColor, QPalette

    from mabinogi_addon.ui.cooking_tab import _VALUE
    tab = _stat_tab()
    style = _light_selection_style()
    lst = tab.dish_list
    lst.setStyle(style)
    pal = lst.palette()
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(225, 222, 235))  # on-accent를 일부러 옅은 칸과 같게
    lst.setPalette(pal)
    item = lst.item(0)
    assert item.isSelected() and item.data(_VALUE) == "+5"
    image = lst.viewport().grab().toImage()
    texts = [t for t, sel in style.calls if sel]
    assert any(t.startswith("★ 불금") for t in texts) and "+5" in texts   # 이름·수치 모두 스타일이 그림(선택 상태 유지)
    rect = lst.visualItemRect(item)
    right = min(rect.right(), lst.viewport().width() - 1)
    dark = [image.pixelColor(x, y).lightness() for x in range(right - 20, right) for y in range(rect.top(), rect.bottom())]
    assert max(dark) - min(dark) >= 60   # 수치 글자가 옅은 선택 칸과 구분됨
    tab.shutdown()


def test_value_delegate_never_picks_text_color_itself():
    import inspect

    from mabinogi_addon.ui import cooking_tab, optimization_panel
    for cls in (cooking_tab._ValueDelegate, optimization_panel._TwoLineDelegate):
        src = inspect.getsource(cls.paint)
        assert "HighlightedText" not in src and "drawText" not in src


# ---- 0.55.0 요리 즐겨찾기(사용자 결정 11-21) ----
def test_favorites_pure_and_config_roundtrip():
    dishes = cooking.load()
    raw = ["모둠회덮밥", "없는 요리", "모둠회덮밥", 3, "BnR"]
    assert cooking.normalize_favorites(raw, dishes) == ["모둠회덮밥", "BnR"]   # 없는 이름·중복·형식 틀림 무시, 순서 유지
    assert cooking.normalize_favorites("x", dishes) == []
    assert [d.name for d in cooking.favorite_dishes(dishes, ["모둠회덮밥", "BnR"])] == ["BnR", "모둠회덮밥"]
    assert cooking.favorites_count(["a", "b"], None) == 2 and cooking.favorites_count(["a", "b"], {"b"}) == 1
    config.save_cooking_favorites(["모둠회덮밥", "BnR"])
    config.save_cooking_overlay(locked=True)               # 같은 cooking 칸 — 서로 덮지 않음
    assert config.load_cooking_favorites() == ["모둠회덮밥", "BnR"] and config.load_cooking_overlay()["locked"]


def _cat_item(tab, name):
    from mabinogi_addon.ui.cooking_tab import _DISH
    return next(i for i in _items(tab.category_list) if i.data(_DISH) == name)


def _texts(tab):
    return [i.text() for i in _items(tab.dish_list)]


def test_favorites_category_top_empty_grey_and_toggle_saves():
    from mabinogi_addon.ui.cooking_tab import CookingTab
    tab = CookingTab()
    fav = tab.category_list.item(0)
    assert fav.text() == "즐겨찾기 (0)" and not (fav.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert fav.toolTip() == "요리를 오른쪽 클릭해 추가"
    tab.toggle_favorite("모둠회덮밥")
    tab.toggle_favorite("까맣게 구워진 드래곤 심장")
    assert config.load_cooking_favorites() == ["모둠회덮밥", "까맣게 구워진 드래곤 심장"]
    assert fav.text() == "즐겨찾기" and fav.flags() & Qt.ItemFlag.ItemIsEnabled and fav.toolTip() == ""
    tab.category_list.setCurrentItem(fav)
    assert _texts(tab) == ["♥ 까맣게 구워진 드래곤 심장", "♥ 모둠회덮밥"]
    tab.toggle_favorite("모둠회덮밥")                         # 즐겨찾기에서 빼면 바로 사라짐
    assert _texts(tab) == ["♥ 까맣게 구워진 드래곤 심장"]
    tab.shutdown()
    again = CookingTab()                                       # 다시 읽기
    assert again.favorites == ["까맣게 구워진 드래곤 심장"] and again.category_list.item(0).text() == "즐겨찾기"
    again.shutdown()


def test_click_inside_favorites_stays_and_hearts_everywhere():
    from mabinogi_addon.ui.cooking_tab import CookingTab
    config.save_cooking_favorites(["모둠회덮밥", "까맣게 구워진 드래곤 심장"])
    tab = CookingTab()
    tab.category_list.setCurrentItem(tab.category_list.item(0))
    tab._dish_clicked(_items(tab.dish_list)[1])                # 모둠회덮밥(혼합)
    assert tab.selected.name == "모둠회덮밥" and tab._category == "즐겨찾기"
    assert tab.category_list.currentItem() is tab.category_list.item(0)
    tab.open_ingredient("모둠생선회")                           # 재료 ▸는 그 요리의 조리방법 카테고리로
    assert tab._category == "혼합"
    assert "♥ 모둠회덮밥" in _texts(tab) and "모둠생선회" in _texts(tab)
    tab.shutdown()


def test_favorites_follow_search_rules():
    from mabinogi_addon.ui.cooking_tab import _VALUE, CookingTab
    config.save_cooking_favorites(["모둠회덮밥", "까맣게 구워진 드래곤 심장", "불금 반반 치맥 세트"])
    tab = CookingTab()
    fav = tab.category_list.item(0)
    tab.category_list.setCurrentItem(fav)
    assert _texts(tab) == ["♥ 까맣게 구워진 드래곤 심장", "♥ 모둠회덮밥", "♥ 불금 반반 치맥 세트"]
    tab.kind.setCurrentText("능력치")
    tab.stat.setCurrentIndex(tab.stat.findData("생명력"))      # 최고 300 = 드래곤 심장(즐겨찾기 안)
    assert fav.text() == "★ 즐겨찾기 (2)"
    rows = _items(tab.dish_list)
    assert [r.text() for r in rows] == ["★♥ 까맣게 구워진 드래곤 심장", "♥ 모둠회덮밥", "♥ 불금 반반 치맥 세트"]
    assert [r.data(_VALUE) for r in rows] == ["+300", "+35", None]
    assert not (rows[2].flags() & Qt.ItemFlag.ItemIsEnabled)   # 생명력 없는 요리 회색 아래
    tab.kind.setCurrentText("재료")
    tab.query.setText("밥")
    assert fav.text() == "즐겨찾기 (1)"
    assert _texts(tab)[0] == "♥ 모둠회덮밥"
    tab.query.setText("없는재료")
    assert fav.text() == "즐겨찾기 (0)" and not (fav.flags() & Qt.ItemFlag.ItemIsEnabled)
    tab.shutdown()


def test_right_click_menu_toggles_even_grey_rows():
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.cooking_tab import _DISH, CookingTab
    tab = CookingTab()
    tab.resize(760, 500)
    tab.show()
    tab.kind.setCurrentText("재료")
    tab.query.setText("밥")
    tab.category_list.setCurrentItem(_cat_item(tab, "혼합"))
    QApplication.processEvents()
    grey = next(i for i in _items(tab.dish_list) if not (i.flags() & Qt.ItemFlag.ItemIsEnabled))
    name = grey.data(_DISH)
    shown = []
    tab._exec_menu = lambda menu, pos: (shown.append([a.text() for a in menu.actions()]), menu.actions()[0].trigger())
    rect = tab.dish_list.visualItemRect(grey)
    tab.dish_list.customContextMenuRequested.emit(rect.center())
    assert shown == [["즐겨찾기에 추가"]] and name in tab.favorites   # 목록을 다시 채워 예전 줄 객체는 사라짐
    row = next(i for i in _items(tab.dish_list) if i.data(_DISH) == name)
    assert row.text().startswith("♥ ")
    tab.dish_list.customContextMenuRequested.emit(tab.dish_list.visualItemRect(row).center())
    assert shown[-1] == ["즐겨찾기에서 빼기"] and name not in tab.favorites
    tab.dish_list.itemAt = lambda _pos: None                    # 줄이 없는 빈 곳
    tab.dish_list.customContextMenuRequested.emit(QPoint(5, 5))
    assert len(shown) == 2                                    # 메뉴 안 뜸
    tab.shutdown()
