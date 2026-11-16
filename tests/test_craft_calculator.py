"""제작 재료 계산기(docs/craft-material-calculator-spec.md 5절, 0.50.0 모든 사용자)."""
import io
import json
import os

import pytest

from mabinogi_addon import config
from mabinogi_addon.market import auction, craft

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

WARRIOR_SHIELD = [  # 인게임 화면(11-15)과 대조
    ("브리 레흐의 정수", 8), ("브리 레흐의 코어", 4), ("견고한 기억의 결정", 5), ("마력이 충만한 스핀 기어", 1),
    ("순도 높은 융합의 힐웬 합금", 1), ("단단한 금속", 10), ("마력이 깃든 가죽 조각", 24), ("날카롭게 결정화된 광물 조각", 30)]


# ---- 데이터 ----
def _series():
    series = craft.load_series()
    assert [s.name for s in series] == ["소울 리버레이트", "더스크 바운드"]  # 파일의 order 순
    assert [s.kind for s in series] == [craft.SIMPLE, craft.PROCESS]
    return series[0]


def test_data_29_weapons_with_8_materials():
    s = _series()
    assert len(s.items) == 29
    assert len({i.name for i in s.items}) == 29  # 이름 중복 없음
    for item in s.items:
        assert len(item.materials) == 8 and item.skill
        assert len({m for m, _ in item.materials}) == 8
        assert all(type(n) is int and n > 0 for _, n in item.materials)


def test_warrior_shield_matches_ingame():
    item = next(i for i in _series().items if i.name.endswith("워리어 실드"))
    assert item.skill == "힐웬 공학"
    assert list(item.materials) == WARRIOR_SHIELD


def test_series_grow_by_adding_a_data_file(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"series": "새 시리즈", "items": [
        {"name": "무기", "skill": "목공", "materials": [["재료", 3]]}]}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert [s.name for s in craft.load_series(tmp_path)] == ["새 시리즈"]


def test_screen_code_has_no_weapon_names():
    from pathlib import Path
    src = (Path(craft.__file__).parents[1] / "ui" / "craft_tab.py").read_text(encoding="utf-8")
    assert not any(word in src for word in ("소울", "리버레이트", "더스크", "이지스", "비고러스", "에테리얼", "광두정"))


# ---- 계산 ----
ITEM = craft.Item("무기", "힐웬 공학", (("가", 10), ("나", 4), ("다", 2), ("라", 5)))


def test_compute_left_cost_total_and_order():
    s = craft.compute(ITEM, {"가": 3, "나": 4, "다": 9}, {"가": 1000, "나": 5, "다": None, "라": craft.FAILED})
    rows = {r.material: r for r in s.rows}
    assert (rows["가"].left, rows["가"].cost) == (7, 7000)
    assert rows["나"].done and rows["다"].done  # 보유 > 필요도 다 모음
    assert rows["다"].left == 0
    assert [r.material for r in s.rows] == ["가", "라", "나", "다"]  # 남은 위(데이터 순서), 다 모은 아래
    assert s.left_kinds == 2 and s.total == 7000
    assert s.no_listing == 0 and s.failed == 1  # 다 모은 재료의 매물 없음은 세지 않음


def test_no_listing_and_failed_left_out_of_total():
    s = craft.compute(ITEM, {}, {"가": 100, "나": None, "다": craft.FAILED})
    assert s.total == 1000 and s.no_listing == 1 and s.failed == 1 and s.left_kinds == 4
    assert {r.material: r.cost for r in s.rows}["라"] is None  # 아직 모름


def test_owned_is_clamped():
    assert craft.clamp_owned(-3) == 0 and craft.clamp_owned(10**6) == craft.OWNED_MAX and craft.clamp_owned("x") == 0


# ---- 보유 저장 ----
def test_owned_shared_by_material_and_persisted():
    s = _series()
    sword = next(i for i in s.items if i.name.endswith(" 소드"))
    blade = next(i for i in s.items if i.name.endswith(" 블레이드"))
    common = next(m for m, _ in sword.materials if m in dict(blade.materials))
    config.set_craft_owned(common, 7)
    owned = config.load_craft_owned()  # 다시 읽기 = 재시작 후
    assert {r.material: r.owned for r in craft.compute(blade, owned, {}).rows}[common] == 7
    config.set_craft_owned(common, 0)
    assert common not in config._read_local_config().get("craftOwned", {})  # 0은 저장 안 함


def test_owned_is_exported_and_synced():
    from mabinogi_addon import cloud_sync
    config.set_craft_owned("브리 레흐의 정수", 5)
    assert cloud_sync.strip_for_sync(config._read_local_config())["craftOwned"] == {"브리 레흐의 정수": 5}
    assert "craftOwned" not in config._LOCAL_ONLY_KEYS


# ---- 시세 ----
def _fake_urlopen(table, calls):
    def urlopen(request, timeout):
        from urllib.parse import parse_qs, urlparse
        name = parse_qs(urlparse(request.full_url).query)["item_name"][0]
        calls.append(name)
        value = table[name]
        if isinstance(value, Exception):
            raise value
        items = [] if value is None else [{"item_display_name": name, "auction_price_per_unit": value}]
        return io.BytesIO(json.dumps({"auction_item": items}).encode())
    return urlopen


def test_fetch_success_no_listing_and_partial_failure():
    calls = []
    table = {"가": 100, "나": None, "다": OSError("down")}
    got = auction.fetch_min_prices(list(table), "k", urlopen=_fake_urlopen(table, calls), failed=craft.FAILED)
    assert got == {"가": 100, "나": None, "다": craft.FAILED}
    assert auction.fetch_min_prices(["다"], "k", urlopen=_fake_urlopen(table, []))["다"] is None  # 기본은 예전처럼 None


def test_price_cache_ten_minutes():
    now = [0.0]
    cache = craft.PriceCache(clock=lambda: now[0])
    cache.put("가", 100)
    cache.put("나", None)
    assert cache.get("가") == (True, 100) and cache.get("나") == (True, None)
    now[0] = 599
    assert cache.missing(["가", "나", "다"]) == ["다"]
    now[0] = 600
    assert cache.missing(["가", "나"]) == ["가", "나"]


# ---- 화면 ----
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab_env(app, monkeypatch):
    from mabinogi_addon.ui import craft_tab as ct
    started = []

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.call = (target, args)

        def start(self):
            started.append(self.call)
    monkeypatch.setattr(ct.threading, "Thread", FakeThread)
    monkeypatch.setattr(config, "get_nexon_api_key", lambda: "k")
    return ct, started


def _finish(tab, started, prices):
    while started:
        _target, (q, names, _key, _c) = started.pop(0)
        q.put({n: prices.get(n, craft.FAILED) for n in names})
        tab._receive()


def test_tab_fetches_weapon_materials_and_reuses_cache(tab_env):
    ct, started = tab_env
    tab = ct.CraftTab()
    try:
        item = tab.current_item()
        names = [m for m, _ in item.materials]
        assert tab.status.text() == ct.LOADING and started[0][1][1] == names  # 무기 재료 8종 조회
        _finish(tab, started, {n: 1000 for n in names})
        assert "경매 시세는 약 10분 지연돼요." in tab.status.text()
        tab.select_item(item.name)
        tab._on_weapon()
        assert not started  # 10분 안 — 캐시 재사용
        tab.refresh.click()
        assert started and started[0][1][1] == names  # 새로고침 = 그 무기 8종 강제
    finally:
        tab.shutdown()
        tab.deleteLater()


def test_tab_without_key(app, monkeypatch, tab_env):
    ct, started = tab_env
    monkeypatch.setattr(config, "get_nexon_api_key", lambda: "")
    tab = ct.CraftTab()
    try:
        assert tab.status.text() == ct.NO_KEY and not started
    finally:
        tab.deleteLater()


def test_tab_typing_does_not_reorder_and_hide_done(tab_env):
    ct, started = tab_env
    tab = ct.CraftTab()
    try:
        item = tab.current_item()
        _finish(tab, started, {m: 10 for m, _ in item.materials})
        first, need = item.materials[0]
        order = list(tab._order)
        tab._spins[first][0].setValue(need)  # 첫 재료를 다 모음
        assert tab._order == order  # 입력 중에는 줄이 그대로
        assert tab.table.topLevelItem(0).text(3) == "✓"
        assert config.load_craft_owned()[first] == need
        assert "남은 재료 7종" in tab.summary.text()
        tab._resort()  # 탭에 다시 들어오면
        assert tab._order[-1] == ("row", first)
        tab.hide_done.setChecked(True)
        assert ("row", first) not in tab._order and config.load_craft_hide_done()
    finally:
        tab.shutdown()
        tab.deleteLater()


def test_tab_shows_no_listing_and_failed(tab_env):
    ct, started = tab_env
    tab = ct.CraftTab()
    try:
        names = [m for m, _ in tab.current_item().materials]
        prices = {n: 100 for n in names}
        prices[names[0]] = None
        prices[names[1]] = craft.FAILED
        _finish(tab, started, prices)
        texts = {tab.table.topLevelItem(r).text(0): tab.table.topLevelItem(r).text(4) for r in range(tab.table.topLevelItemCount())}
        assert texts[names[0]] == "매물 없음" and texts[names[1]] == "조회 실패"
        assert "매물 없는 재료 1종" in tab.status.text() and "조회에 실패한 재료 1종" in tab.status.text()
    finally:
        tab.shutdown()
        tab.deleteLater()


# ---- 더스크 바운드(공정형 세트, 명세 5절·6절) ----
def _dusk():
    return craft.load_series()[1]


def _set(name):
    return next(i for i in _dusk().items if i.name == name)


def test_dusk_three_sets_four_parts():
    d = _dusk()
    assert d.item_label == "세트" and d.default_processes == 7
    assert [i.label for i in d.items] == ["이지스 · 중갑", "비고러스 · 경갑", "에테리얼 · 천옷"]
    assert [i.skill for i in d.items] == ["블랙스미스", "블랙스미스", "천옷 만들기"]
    for item in d.items:
        assert len(item.parts) == 4
        assert [m for m, _ in item.finish_materials] == ["고리아스 동력원", "희미한 에너지 조각"]
        names = item.material_names()
        assert len(names) == len(set(names))


def test_dusk_required_quantities():
    aegis = _set("이지스")
    need = {m: n for _g, mats in craft.requirements(aegis, parts=4, processes=7) for m, n in mats}
    assert need["달아오른 광두정"] == 840 and need["고리아스 동력원"] == 4  # 30 × 7 × 4, 1 × 4
    assert need["희미한 에너지 조각"] == 400 and need["순도 높은 힐웬 주괴 조각"] == 84
    two = {m: n for _g, mats in craft.requirements(aegis, parts=2, processes=3) for m, n in mats}
    assert two["달아오른 광두정"] == 180 and two["고리아스 동력원"] == 2
    assert craft.requirements(aegis, parts=0, processes=7) == []
    groups = [g for g, _ in craft.requirements(aegis, parts=1, processes=1)]
    assert groups == [craft.GROUP_PROCESS, craft.GROUP_FINISH]


def test_dusk_rows_grouped_left_first_within_group():
    aegis = _set("이지스")
    s = craft.compute(aegis, {"미스릴 대못": 9999, "고리아스 동력원": 4}, {}, parts=4, processes=7)
    order = [(r.group, r.material) for r in s.rows]
    assert order[:5] == [(craft.GROUP_PROCESS, m) for m in
                         ("달아오른 광두정", "미스릴판", "빛바랜 에너지 회로", "순도 높은 힐웬 주괴 조각", "미스릴 대못")]
    assert order[5:] == [(craft.GROUP_FINISH, "희미한 에너지 조각"), (craft.GROUP_FINISH, "고리아스 동력원")]


def test_choice_saved_per_set():
    config.set_craft_choice("더스크 바운드", "이지스", [True, False, True, False], 9)
    assert config.load_craft_choice("더스크 바운드", "이지스", 4, 7) == ([True, False, True, False], 9)
    assert config.load_craft_choice("더스크 바운드", "비고러스", 4, 7) == ([True] * 4, 7)  # 다른 세트는 기본
    from mabinogi_addon import cloud_sync
    assert "craftChoice" in cloud_sync.strip_for_sync(config._read_local_config())


def _open_dusk(ct, started):
    tab = ct.CraftTab()
    _finish(tab, started, {})  # 처음 열린 소울 리버레이트 조회를 끝내고
    tab.series_list.setCurrentRow(1)
    return tab


def test_dusk_tab_parts_processes_and_group_rows(tab_env):
    ct, started = tab_env
    tab = _open_dusk(ct, started)
    try:
        assert tab.item_label.text() == "세트" and tab.weapon.currentText() == "이지스 · 중갑"
        assert [b.text() for b in tab.part_checks] == ["가드", "헬멧", "건틀릿", "그리브"]
        assert all(b.isChecked() for b in tab.part_checks) and tab.processes.value() == 7
        assert tab.note.text() == ct.PROCESS_NOTE
        names = _set("이지스").material_names()
        assert sorted(started[-1][1][1]) == sorted(names)  # 세트 재료 전부 조회
        _finish(tab, started, {n: 1000 for n in names})
        heads = [tab.table.topLevelItem(i).text(0) for i, (k, _m) in enumerate(tab._order) if k == "head"]
        assert heads == ["공정 재료 · 1공정 수량 × 공정 7회 × 4부위", "마감 재료 · 부위마다 1번 × 4부위"]
        need = {m: tab.table.topLevelItem(i).text(1) for i, (k, m) in enumerate(tab._order) if k == "row"}
        assert need["달아오른 광두정"] == "840" and need["고리아스 동력원"] == "4"
        tab.part_checks[1].setChecked(False)  # 헬멧 빼기 → 3부위
        tab.processes.setValue(5)
        need = {m: tab.table.topLevelItem(i).text(1) for i, (k, m) in enumerate(tab._order) if k == "row"}
        assert need["달아오른 광두정"] == "450" and need["고리아스 동력원"] == "3"  # 30 × 5 × 3
        assert config.load_craft_choice("더스크 바운드", "이지스", 4, 7) == ([True, False, True, True], 5)
        for box in tab.part_checks:
            box.setChecked(False)
        assert tab.table.topLevelItemCount() == 0 and tab.summary.text() == ct.NO_PARTS
    finally:
        tab.shutdown()
        tab.deleteLater()


def test_dusk_shared_owned_across_sets_and_simple_hides_choice(tab_env):
    ct, started = tab_env
    tab = _open_dusk(ct, started)
    try:
        tab._spins["빛바랜 에너지 회로"][0].setValue(5)
        tab.weapon.setCurrentIndex(2)  # 에테리얼
        assert tab.skill.text() == "천옷 만들기"
        assert tab._spins["빛바랜 에너지 회로"][0].value() == 5  # 공통 재료 보유 공유
        assert [b.text() for b in tab.part_checks] == ["슈트", "튜더 베레모", "글러브", "슈즈"]
        tab.series_list.setCurrentRow(0)  # 소울 리버레이트
        assert tab.item_label.text() == "무기"
        assert not any(b.isVisibleTo(tab) for b in tab.part_checks) and not tab.processes.isVisibleTo(tab)
        assert tab.note.text() == ct.SUB_NOTE  # 소울 리버레이트는 하위 재료 안내(명세 6절 그림)
        assert all(k == "row" for k, _m in tab._order)  # simple은 묶음 줄 없음
    finally:
        tab.shutdown()
        tab.deleteLater()


# ---- 소울 리버레이트 무기 분류(0.50.0 사용자 결정 11-15) ----
CATEGORIES = [
    ("근접", ["소드", "해머", "액스", "실드", "워리어 실드", "블레이드", "랜스", "워리어 해머", "워리어 액스", "너클", "핸들",
              "콜로서스 미니어처", "피에로 미니어처", "체인 블레이드"]),
    ("마법", ["스태프", "원드", "힐링 원드", "마도서", "실린더", "가드실린더", "사이드", "오브"]),
    ("원거리", ["보우", "이터널 애로우", "크로스보우", "이터널 볼트", "스로잉 스타", "듀얼건"]),
    ("악기", ["리라"]),
]


def test_soul_categories_cover_each_weapon_once_in_order():
    s = _series()
    got = [(name, [s.items[i].name.replace("소울리버레이트 ", "") for i in idx]) for name, idx in s.categories]
    assert got == CATEGORIES
    flat = [i for _n, idx in s.categories for i in idx]
    assert sorted(flat) == list(range(29))  # 29종 모두 정확히 한 번
    assert not _dusk().categories and [i for _t, i in _dusk().menu()] == [0, 1, 2]  # 분류 없는 시리즈는 그대로


def test_bad_categories_fall_back_to_plain_list(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"series": "x", "categories": [{"name": "근접", "items": ["무기"]}], "items": [
        {"name": "무기", "skill": "s", "materials": [["재료", 1]]}, {"name": "둘", "skill": "s", "materials": [["재료", 1]]}]},
        ensure_ascii=False), encoding="utf-8")
    s = craft.load_series(tmp_path)[0]
    assert s.categories == () and [t for t, _i in s.menu()] == ["무기", "둘"]


def test_menu_headers_not_selectable_and_keys_skip_them(tab_env):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    ct, _started = tab_env
    tab = ct.CraftTab()
    try:
        model = tab.weapon.model()
        texts = [model.item(r).text() for r in range(model.rowCount())]
        assert texts[0] == "근접" and len(texts) == 33
        heads = [r for r in range(model.rowCount()) if model.item(r).data(Qt.ItemDataRole.UserRole) is None]
        assert [texts[r] for r in heads] == ["근접", "마법", "원거리", "악기"]
        assert all(not model.item(r).isSelectable() and not model.item(r).isEnabled() for r in heads)
        assert tab.weapon.currentIndex() == 1 and tab.current_item().name.endswith(" 소드")
        tab.select_item("소울리버레이트 체인 블레이드")  # 근접 마지막
        QTest.keyClick(tab.weapon, Qt.Key.Key_Down)
        assert tab.current_item().name.endswith(" 스태프")  # '마법' 머리 건너뜀
        QTest.keyClick(tab.weapon, Qt.Key.Key_Up)
        assert tab.current_item().name.endswith(" 체인 블레이드")
        tab.weapon.setCurrentIndex(heads[2])  # 코드에서 머리를 골라도 그 아래 첫 무기로
        assert tab.current_item().name.endswith(" 보우")
    finally:
        tab.shutdown()
        tab.deleteLater()


def test_last_selection_restored(tab_env):
    ct, _started = tab_env
    tab = ct.CraftTab()
    tab.select_item("소울리버레이트 리라")
    tab.series_list.setCurrentRow(1)
    tab.weapon.setCurrentIndex(2)  # 에테리얼
    tab.shutdown()
    tab.deleteLater()
    again = ct.CraftTab()  # 다시 열면 마지막 시리즈·세트
    try:
        assert again.current_series().name == "더스크 바운드" and again.current_item().name == "에테리얼"
        again.series_list.setCurrentRow(0)
        assert again.current_item().name == "소울리버레이트 리라"  # 시리즈마다 마지막 장비
    finally:
        again.shutdown()
        again.deleteLater()


# ---- 더스크 바운드 구슬(명세 5절 '구슬 합계'·'구슬 열', 7절) ----
def test_bead_total_aegis_zero_owned_and_owned():
    aegis = _set("이지스")
    s = craft.compute(aegis, {}, {}, parts=4, processes=7)
    assert craft.bead_total(s) == ({"탈라가흐": 840 * 3 + 28 * 35 + 84 * 6 + 4 * 200}, 4)  # 4,804
    s2 = craft.compute(aegis, {"달아오른 광두정": 840, "빛바랜 에너지 회로": 5}, {}, parts=4, processes=7)
    assert craft.bead_total(s2) == ({"탈라가흐": 23 * 35 + 84 * 6 + 4 * 200}, 3)  # 다 모은 광두정 제외
    assert craft.coin_of("미스릴 대못") is None and craft.coin_of("희미한 에너지 조각") is None  # 교환표에 없음


def test_bead_follows_exchange_table(monkeypatch):
    from mabinogi_addon.market import exchange
    table = {k: [dict(m) for m in v] for k, v in exchange.REGIONS.items()}
    next(m for m in table["탈라가흐"] if m["name"] == "고리아스 동력원")["coin"] = 250
    monkeypatch.setattr(exchange, "REGIONS", table)
    s = craft.compute(_set("이지스"), {}, {}, parts=4, processes=7)
    assert craft.bead_total(s)[0]["탈라가흐"] == 840 * 3 + 28 * 35 + 84 * 6 + 4 * 250


def test_dusk_bead_line_and_columns(tab_env):
    ct, started = tab_env
    tab = _open_dusk(ct, started)
    try:
        assert tab.beads.isVisible() or tab.beads.isVisibleTo(tab)
        assert "탈라가흐 구슬 <span" in tab.beads.text() and "4,804개" in tab.beads.text()
        assert "구슬 교환 재료 4종 기준" in tab.beads.text()
        assert not tab.table.isColumnHidden(6) and not tab.table.isColumnHidden(7)
        rows = {tab.table.topLevelItem(i).text(0): tab.table.topLevelItem(i) for i in range(tab.table.topLevelItemCount())}
        assert (rows["달아오른 광두정"].text(6), rows["달아오른 광두정"].text(7)) == ("3", "2,520")
        assert (rows["미스릴 대못"].text(6), rows["미스릴 대못"].text(7)) == ("", "")  # 교환표에 없음
        column = sum(int(e.text(7).replace(",", "")) for e in rows.values() if e.text(7))
        assert column == 4804  # 남은 구슬 열 합 = 구슬 합계 줄
        tab._spins["달아오른 광두정"][0].setValue(840)
        assert rows["달아오른 광두정"].text(7) == ""  # 다 모은 재료는 남은 구슬 비움
        tab.series_list.setCurrentRow(0)  # 소울 리버레이트도 구슬 열·구슬 줄(사용자 요청 11-16)
        assert not tab.table.isColumnHidden(6) and not tab.table.isColumnHidden(7) and tab.beads.isVisibleTo(tab)
    finally:
        tab.shutdown()
        tab.deleteLater()


# ---- 하위 재료 펼치기(명세 6절, 7절) ----
def _soul_item(name):
    return next(i for i in _series().items if i.name.endswith(name))


def test_crafts_data_28_no_cycles_no_tags():
    s = _series()
    assert len(s.crafts) == 28 and s.shop == frozenset({"마력이 깃든 융합제", "각성된 힘의 가루"})
    for skill, mats in s.crafts.values():
        assert skill and mats and all(not any(t in n for t in ("(제작)", "(분해)", "(상점)")) for n, _ in mats)

    def depth(name, seen=()):
        assert name not in seen, f"순환 {seen + (name,)}"
        recipe = s.recipe(name)
        return 0 if recipe is None else 1 + max(depth(n, seen + (name,)) for n, _ in recipe[1])
    assert all(depth(n) >= 1 for n in s.crafts)
    first_level = {m for item in s.items for m, _ in item.materials}
    assert len(first_level & set(s.crafts)) == 23  # 1단계 재료 중 23종 펼칠 수 있음


def test_sub_rows_need_parent_left_times_per_and_compare():
    s = _series()
    shield = _soul_item("워리어 실드")
    summary = craft.compute(shield, {"견고한 기억의 결정": 2}, {"견고한 기억의 결정": 19_999_999})
    parent = next(r for r in summary.rows if r.material == "견고한 기억의 결정")
    kids = craft.sub_rows(s, parent.material, parent.left, {}, {"퓨어 젬스톤": 1_500_000, "금빛 기억의 조각": 900_000, "오피먼트": 25_000})
    need = {c.material: c.need for c in kids}
    assert need["오피먼트"] == 30 and need["퓨어 젬스톤"] == 6  # 남음 3 × 개당
    assert {c.material: c.price for c in kids}["마력이 깃든 융합제"] == craft.SHOP
    cmp = craft.make_compare(s, parent, kids)
    assert cmp.make == 6 * 1_500_000 + 9 * 900_000 + 30 * 25_000 and cmp.buy == 3 * 19_999_999
    assert cmp.shop_left_out and not cmp.no_listing_left_out
    done = craft.sub_rows(s, parent.material, 0, {}, {})
    assert all(c.need == 0 and c.done for c in done)  # 부모 다 모음 → 하위 필요 0


def test_tree_expand_two_levels_compare_row_and_top_total_unchanged(tab_env):
    ct, started = tab_env
    config.set_craft_owned("견고한 기억의 결정", 2)  # 명세 6절 그림과 같은 보유 → 남음 3
    tab = ct.CraftTab()
    try:
        _finish(tab, started, {})
        tab.select_item("소울리버레이트 워리어 실드")
        prices = {"견고한 기억의 결정": 19_999_999, "퓨어 젬스톤": 1_500_000, "금빛 기억의 조각": 900_000, "오피먼트": 25_000}
        _finish(tab, started, prices)
        before = tab.summary.text()
        top = {tab.table.topLevelItem(i).text(0): tab.table.topLevelItem(i) for i in range(tab.table.topLevelItemCount())}
        crystal = top["견고한 기억의 결정"]
        assert crystal.childIndicatorPolicy() == crystal.ChildIndicatorPolicy.ShowIndicator
        tab._on_item_clicked(crystal, 0)  # 줄을 누르면 펼침
        assert crystal.isExpanded()
        asked = started[-1][1][1] if started else []
        assert "마력이 깃든 융합제" not in asked and "퓨어 젬스톤" in asked  # 하위 시세는 펼칠 때, 상점 재료는 조회 안 함
        _finish(tab, started, prices)
        assert crystal.child(0).isFirstColumnSpanned()
        assert crystal.child(0).text(0).startswith("만들기 · ") and "직접 만들면 약 1,785만 (사면 5,999만)" in crystal.child(0).text(0)
        assert crystal.child(0).text(0).endswith("· 상점 재료 제외")
        kids = {crystal.child(i).text(0): crystal.child(i) for i in range(1, crystal.childCount())}
        assert kids["마력이 깃든 융합제"].text(4) == "상점" and kids["오피먼트"].text(1) == "30"
        gem = kids["퓨어 젬스톤"]
        assert gem.childIndicatorPolicy() == gem.ChildIndicatorPolicy.ShowIndicator
        gem.setExpanded(True)  # 2단계
        _finish(tab, started, {})
        grand = [gem.child(i) for i in range(1, gem.childCount())]
        assert grand and all(g.childIndicatorPolicy() != g.ChildIndicatorPolicy.ShowIndicator for g in grand)  # 최대 깊이 2
        assert tab.summary.text() == before  # 위쪽 합계는 1단계 기준 그대로
        tab._spins["견고한 기억의 결정"][0].setValue(5)  # 부모 다 모음 → 하위 필요 0
        assert kids["오피먼트"].text(1) == "0"
        tab.select_item("소울리버레이트 실드")
        assert not tab._expanded  # 무기를 바꾸면 모두 접힘
    finally:
        tab.shutdown()
        tab.deleteLater()


# ---- 소울 리버레이트 구슬(사용자 요청 11-16 — 두 시리즈 공통, 하위 줄은 표시만) ----
def test_soul_beads_brileh_first_level_only(tab_env):
    ct, started = tab_env
    config.set_craft_owned("브리 레흐의 코어", 1)
    config.set_craft_owned("브리 레흐의 정수", 8)
    config.set_craft_owned("견고한 기억의 결정", 2)
    tab = ct.CraftTab()
    try:
        _finish(tab, started, {})
        tab.select_item("소울리버레이트 워리어 실드")
        _finish(tab, started, {})
        assert "브리레흐 구슬" in tab.beads.text() and "300개" in tab.beads.text()  # 코어 남음 3 × 100
        assert "구슬 교환 재료 1종 기준" in tab.beads.text()  # 정수는 다 모음 → 제외
        top = {tab.table.topLevelItem(i).text(0): tab.table.topLevelItem(i) for i in range(tab.table.topLevelItemCount())}
        assert (top["브리 레흐의 코어"].text(6), top["브리 레흐의 코어"].text(7)) == ("100", "300")
        assert (top["브리 레흐의 정수"].text(6), top["브리 레흐의 정수"].text(7)) == ("100", "")  # 다 모음 → 남은 구슬 비움
        assert top["마력이 충만한 스핀 기어"].text(6) == ""  # 교환표에 없음
        crystal = top["견고한 기억의 결정"]
        crystal.setExpanded(True)
        _finish(tab, started, {})
        kids = {crystal.child(i).text(0): crystal.child(i) for i in range(1, crystal.childCount())}
        assert (kids["오피먼트"].text(6), kids["오피먼트"].text(7)) == ("3", "90")  # 하위 줄에도 구슬 칸
        assert (kids["금빛 기억의 조각"].text(6), kids["금빛 기억의 조각"].text(7)) == ("25", "225")
        assert "300개" in tab.beads.text()  # 위쪽 구슬 합계는 1단계만(펼쳐도 그대로)
    finally:
        tab.shutdown()
        tab.deleteLater()
