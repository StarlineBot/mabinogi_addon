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
    assert [s.name for s in series] == ["소울 리버레이트"]
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
    assert "소울" not in src and "리버레이트" not in src


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
        tab.weapon.setCurrentIndex(0)
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
        tab._spins[first].setValue(need)  # 첫 재료를 다 모음
        assert tab._order == order  # 입력 중에는 줄이 그대로
        assert tab.table.item(0, 3).text() == "✓"
        assert config.load_craft_owned()[first] == need
        assert "남은 재료 7종" in tab.summary.text()
        tab._resort()  # 탭에 다시 들어오면
        assert tab._order[-1] == first
        tab.hide_done.setChecked(True)
        assert first not in tab._order and config.load_craft_hide_done()
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
        texts = {tab.table.item(r, 0).text(): tab.table.item(r, 4).text() for r in range(tab.table.rowCount())}
        assert texts[names[0]] == "매물 없음" and texts[names[1]] == "조회 실패"
        assert "매물 없는 재료 1종" in tab.status.text() and "조회에 실패한 재료 1종" in tab.status.text()
    finally:
        tab.shutdown()
        tab.deleteLater()
