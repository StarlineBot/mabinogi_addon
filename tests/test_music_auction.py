"""음악 버프 계산기 — 부위별 경매장 최저가(docs/music-buff-calculator-spec.md 6.2, 0.52.0).

매물 글자는 명세 6.1 + 디스코드 봇 modules/auction.js(세공 '옵션명(N레벨:…)', 인챈트 option_type '인챈트'·
option_sub_type 접두/접미·option_desc, 특별 개조 option_value)의 형식대로 만든 **형식 예시**다.
아래 '실제 매물 픽스처' 테스트는 2026-11-16 넥슨 API로 받은 매물(`tests/data/music_auction/`)로 글자 규칙을 확인한다.
"""
import io
import json
import os
import time
import urllib.parse
from pathlib import Path

import pytest

from mabinogi_addon import config
from mabinogi_addon.market import music_auction as ma
from mabinogi_addon.market import music_buff as mb

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
FIXTURES = Path(__file__).resolve().parent / "data" / "music_auction"


def _ench(affix, name, n=None):
    return {"option_type": "인챈트", "option_sub_type": affix, "option_value": name,
            "option_desc": f"음악 버프 스킬 효과 {n} 증가" if n is not None else "최대대미지 5 증가"}


def _ref(name, lv):
    return {"option_type": "세공 옵션", "option_value": f"{name}({lv}레벨:{lv * 1}% 증가)"}


def _item(price, *options, name="소울 리버레이트 리라"):
    return {"item_name": name, "item_display_name": name, "auction_price_per_unit": price, "item_option": list(options)}


def _crit(part, **state):
    return ma.criteria(part, mb.normalize(state))


# ---- 조건·매칭 ----
def test_reforge_level_at_least_and_both_patterns():
    c = _crit("instrument", inst_reforge=[["inst_music_buff", 20]])
    assert c.reforges == (("악기 연주 효과", 20),)
    assert ma.matches(_item(1, _ref("악기 연주 효과", 20)), c)
    assert ma.matches(_item(1, _ref("악기 연주 효과", 23)), c)
    assert not ma.matches(_item(1, _ref("악기 연주 효과", 19)), c)
    assert ma.matches(_item(1, {"option_type": "세공 옵션", "option_value": "악기 연주 효과 21 레벨"}), c)


def test_reforge_game_names_and_spacing():
    c = _crit("shoes", shoes_reforge=[["shoes_vivace_magic", 3]])
    assert c.reforges == (("비바체 마법 시전속도", 3),)  # 표 '시전 속도' → 게임 '시전속도'
    assert ma.matches(_item(1, _ref("비바체 마법 시전속도", 4), name="신발"), c)
    assert ma.matches(_item(1, _ref("비바체 마법 시전 속도", 4), name="신발"), c)  # 띄어쓰기 달라도
    c = _crit("acc1", acc1_reforge=[["acc_divine_rate", 2]])
    assert c.reforges == (("음악적 지식 신들린 연주 비율", 2),)


def test_same_enchant_name_different_value_uses_desc_number():
    c9 = _crit("instrument", inst_prefix="inst_polyphony_7")  # 폴리포니 (+9)
    c8 = _crit("instrument", inst_prefix="inst_polyphony_6")  # 폴리포니 (+8)
    plus8, plus9 = _item(1, _ench("접두", "폴리포니", 8)), _item(1, _ench("접두", "폴리포니 (랭크 5)", 9))
    assert ma.matches(plus9, c9) and not ma.matches(plus8, c9)
    assert ma.matches(plus8, c8) and not ma.matches(plus9, c8)
    # 매물 인챈트에 이름만 있으면(효과 문구 없음) 수치 구분 없이 이름으로 맞춘다
    name_only = _item(1, {"option_type": "인챈트", "option_sub_type": "접두", "option_value": "폴리포니 (랭크 5)"})
    assert ma.matches(name_only, c9) and ma.matches(name_only, c8)
    # 이름이 하나뿐인 인챈트는 숫자 확인 없이 이름만
    c = _crit("gloves", gloves_prefix="gloves_soloist")
    assert c.enchants[0].buff is None
    assert ma.matches(_item(1, _ench("접두", "솔리스트"), name="장갑"), c)


def test_prefix_only_suffix_only_and_affix_must_match():
    pre = _crit("acc1", acc1_prefix="acc_andante")
    suf = _crit("acc1", acc1_suffix="acc_cadenza")
    both = _crit("acc1", acc1_prefix="acc_andante", acc1_suffix="acc_cadenza")
    a = _item(1, _ench("접두", "안단테", 1), name="귀걸이")
    b = _item(1, _ench("접미", "카덴차", 1), name="귀걸이")
    ab = _item(1, _ench("접두", "안단테", 1), _ench("접미", "카덴차", 1), name="귀걸이")
    assert ma.matches(a, pre) and not ma.matches(b, pre) and ma.matches(ab, pre)
    assert ma.matches(b, suf) and not ma.matches(a, suf)
    assert ma.matches(ab, both) and not ma.matches(a, both) and not ma.matches(b, both)
    wrong_side = _item(1, _ench("접미", "안단테", 1), name="귀걸이")
    assert not ma.matches(wrong_side, pre)


def test_ensemble_matches_either_name():
    c = _crit("instrument", inst_prefix="inst_ensemble")
    assert ma.matches(_item(1, _ench("접두", "앙상블", 5)), c)
    assert ma.matches(_item(1, _ench("접두", "조화", 5)), c)


def test_conditions_and_special_mod_all_required():
    state = {"inst_prefix": "inst_polyphony_7", "inst_suffix": "inst_tempo_3", "special_mod": 6,
             "inst_reforge": [["inst_music_buff", 20], ["inst_divine_effect", 10]]}
    c = _crit("instrument", **state)
    full = [_ench("접두", "폴리포니", 9), _ench("접미", "템포", 5), _ref("악기 연주 효과", 20),
            _ref("음악적 지식 신들린 연주 효과", 10), {"option_type": "특별 개조", "option_sub_type": "R", "option_value": "6"}]
    assert ma.matches(_item(1, *full), c)
    for i in range(len(full)):  # 하나라도 빠지면 아님
        assert not ma.matches(_item(1, *(full[:i] + full[i + 1:])), c), i
    low_mod = full[:-1] + [{"option_type": "특별 개조", "option_sub_type": "R", "option_value": "5"}]
    assert not ma.matches(_item(1, *low_mod), c)
    high_mod = full[:-1] + [{"option_type": "특별 개조", "option_sub_type": "S", "option_value": "7"}]
    assert ma.matches(_item(1, *high_mod), c)


def test_lowest_price_and_no_match():
    c = _crit("instrument", inst_reforge=[["inst_music_buff", 20]])
    items = [_item(500_000_000, _ref("악기 연주 효과", 25)), _item(345_000_000, _ref("악기 연주 효과", 20)),
             _item(100_000_000, _ref("악기 연주 효과", 19))]
    assert ma.lowest(items, c) == 345_000_000
    assert ma.lowest(items[2:], c) is None


def test_head_equipment_name_and_value():
    c = _crit("head", head_equipment="head_fluia_4")
    assert c.name_contains == "플루아의 풀잎 관" and c.queries == (("category", "모자/가발"),)
    assert ma.matches(_item(1, name="플루아의 풀잎 관"), c)
    assert not ma.matches(_item(1, name="다른 모자"), c)
    other = _item(1, {"option_type": "아이템 효과", "option_value": "음악 버프 스킬 효과 3 증가"}, name="플루아의 풀잎 관")
    assert not ma.matches(other, c)  # 같은 +N만


def test_nothing_chosen_is_empty_and_queries():
    state = mb.default_state()
    for part in ma.PARTS:
        assert ma.criteria(part, state).empty, part
    assert ma.criteria("instrument", dict(state, special_mod=1)).queries == (("name", "소울 리버레이트 리라"),)
    assert ma.criteria("instrument", dict(state, instrument="gloomy")).queries == (("name", "데모닉 글루미 선데이"),)
    assert ma.criteria("eco", state).queries == (("name", "블루 에코스톤"),)
    assert [v for _, v in ma.criteria("armor", state).queries] == ["경갑옷", "중갑옷", "천옷"]


# ---- 조회(가짜 urlopen) ----
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_follows_cursor_and_merges_armor_categories():
    calls = []
    pages = {("경갑옷", None): ([_item(3, name="a")], "c1"), ("경갑옷", "c1"): ([_item(4, name="b")], None),
             ("중갑옷", None): ([_item(5, name="c")], None), ("천옷", None): ([_item(6, name="d")], None)}

    def fake(req, timeout):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))
        calls.append(q)
        assert req.get_header("X-nxopen-api-key") == "k"
        items, cursor = pages[(q["auction_item_category"], q.get("cursor"))]
        return _Resp(json.dumps({"auction_item": items, "next_cursor": cursor}).encode())

    got = ma.fetch(ma.CATEGORY_QUERIES["armor"], "k", urlopen=fake)
    assert [i["item_name"] for i in got] == ["a", "b", "c", "d"]
    assert len(calls) == 4


# ---- 실제 매물 픽스처(2026-11-16 넥슨 API, scripts/fetch_music_auction_fixtures.py) ----
def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["items"]


def test_real_fixtures_reforge_and_enchant_text():
    """실제 매물 글자: 음악 세공은 모두 이름·레벨이 읽히고, 음악 인챈트의 효과 숫자는 우리 표의 같은 이름 수치 중 하나."""
    t = mb.tables()
    names = {o["auction_name"].replace(" ", "") for grp in t["reforge_options"].values() for o in grp}
    table = {}
    for key in ma._ENCHANT_KEYS.values():
        for k, affix in key:
            for e in mb.options(k, t):
                table.setdefault((affix, ma._base(e["name"])), set()).add(e["buff"])
    table[("접두", "조화")] = table[("접두", "조화(앙상블)")]
    seen_reforge = seen_enchant = 0
    for path in sorted(FIXTURES.glob("*.json")):
        for item in json.loads(path.read_text(encoding="utf-8"))["items"]:
            levels = ma.reforge_levels(item)
            for o in item["item_option"]:
                if o["option_type"] in ("세공 옵션", "에코스톤 각성 능력"):
                    plain = o["option_value"].replace(" ", "")
                    hit = [n for n in names if plain.startswith(n)]
                    if hit:
                        assert max(hit, key=len) in levels, o
                        seen_reforge += 1
                if o["option_type"] == "인챈트" and "음악 버프 스킬 효과" in (o["option_desc"] or ""):
                    base = o["option_value"].split(" (랭크")[0]
                    n = ma._music_number(o["option_desc"])
                    if (o["option_sub_type"], base) in table:
                        assert n in table[(o["option_sub_type"], base)], (path.name, o)
                        seen_enchant += 1
    assert seen_reforge > 300 and seen_enchant > 50  # 11-16 픽스처: 세공 328 · 음악 인챈트 129


def test_real_fixture_duration_is_not_effect():
    """앙코르: '음악 버프 스킬 지속시간 10 증가'가 '효과 3 증가'보다 앞에 있어도 효과 3."""
    enc = next(o for it in _fixture("경갑옷") for o in it["item_option"]
               if o["option_type"] == "인챈트" and o["option_value"].startswith("앙코르"))
    assert enc["option_desc"].index("지속시간") < enc["option_desc"].index("스킬 효과")
    assert ma._music_number(enc["option_desc"]) == 3
    c = _crit("armor", armor_prefix="armor_encore")
    assert ma.lowest(_fixture("경갑옷") + _fixture("중갑옷") + _fixture("천옷"), c) is not None


def test_real_fixture_same_rank_different_value():
    """소나타 랭크 5에 +5·+6이 함께 있음 → 효과 숫자로 가른다(랭크로는 못 가름)."""
    cloth = _fixture("천옷") + _fixture("경갑옷") + _fixture("중갑옷")
    p6 = ma.lowest(cloth, _crit("armor", armor_prefix="armor_sonata_6"))
    p5 = ma.lowest(cloth, _crit("armor", armor_prefix="armor_sonata_5"))
    assert p6 is not None and p5 is not None and p5 != p6
    six = [it for it in cloth if ma.matches(it, _crit("armor", armor_prefix="armor_sonata_6"))]
    assert all("음악 버프 스킬 효과 6" in o["option_desc"] for it in six for o in it["item_option"]
               if o["option_type"] == "인챈트" and o["option_value"].startswith("소나타"))


def test_real_fixture_instrument_and_echostone():
    lyre = _fixture("소울_리버레이트_리라")
    c = _crit("instrument", inst_reforge=[["inst_divine_effect", 10]], special_mod=7)
    got = [it for it in lyre if ma.matches(it, c)]
    assert got and all(ma._special_mod(it) >= 7 and ma.reforge_levels(it)["음악적지식신들린연주효과"] >= 10 for it in got)
    assert ma.lowest(lyre, c) == min(it["auction_price_per_unit"] for it in got)
    eco = _fixture("블루_에코스톤")
    c = _crit("eco", eco_reforge=[["eco_music_buff", 10]])
    got = [it for it in eco if ma.matches(it, c)]
    assert got and all(ma.reforge_levels(it)["악기연주효과"] >= 10 for it in got)
    assert ma.matches({"item_option": [{"option_type": "에코스톤 각성 능력",
                                        "option_value": "악기 연주 효과 10 레벨 \n(10.00 )"}]}, c)


# ---- 화면 ----
@pytest.fixture
def tab(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.music_buff_tab import MusicBuffTab
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "get_nexon_api_key", lambda: "k")
    t = MusicBuffTab()
    yield t, app
    t.shutdown()
    t.close()


def _wait(app, tab, part, timeout=3.0):
    end = time.monotonic() + timeout
    while tab.auction_state[part] == "loading" and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def test_buttons_disabled_without_options(tab):
    t, _ = tab
    assert set(t.auction_buttons) == set(ma.PARTS)
    assert not any(b.isEnabled() for b in t.auction_buttons.values())
    t.combos["armor_prefix"].set_value("armor_sonata_6")
    assert t.auction_buttons["armor"].isEnabled()
    assert not t.auction_buttons["gloves"].isEnabled()
    t.special_mod.setValue(3)  # 악기는 특개만 골라도
    assert t.auction_buttons["instrument"].isEnabled()
    b = t.auction_buttons["eco"]
    assert b.text() == "경매장" and not b.icon().isNull() and "최저가" in b.toolTip()


def test_found_line_disabled_while_loading_and_cleared_on_change(tab, monkeypatch):
    t, app = tab
    gate = __import__("threading").Event()

    def fake_fetch(queries, key, urlopen=None):
        gate.wait(2)
        return [_item(345_000_000, _ench("접두", "소나타", 6), name="천옷"),
                _item(900_000_000, _ench("접두", "소나타", 6), name="경갑옷")]
    monkeypatch.setattr(ma, "fetch", fake_fetch)
    t.combos["armor_prefix"].set_value("armor_sonata_6")
    t.auction_buttons["armor"].click()
    assert t.auction_state["armor"] == "loading" and not t.auction_buttons["armor"].isEnabled()
    assert t.auction_lines["armor"].text() == "찾는 중…" and not t.auction_lines["armor"].isHidden()
    gate.set()
    _wait(app, t, "armor")
    assert t.auction_state["armor"] == "found" and t.auction_buttons["armor"].isEnabled()
    assert "경매장 최저가" in t.auction_lines["armor"].text() and "3억 4,500만" in t.auction_lines["armor"].text()
    assert not any("auction" in k for k in config.load_music_buff())  # 결과는 저장 안 함
    t.combos["gloves_prefix"].set_value("gloves_soloist")  # 다른 부위는 그대로
    assert t.auction_state["armor"] == "found"
    t.combos["armor_prefix"].set_value("armor_sonata_5")  # 그 부위 옵션 바꾸면 지움
    assert t.auction_state["armor"] is None and t.auction_lines["armor"].isHidden()


def test_late_result_after_change_is_dropped(tab, monkeypatch):
    t, app = tab
    gate = __import__("threading").Event()
    monkeypatch.setattr(ma, "fetch", lambda *a, **k: (gate.wait(2), [_item(1, _ench("접두", "솔리스트"), name="장갑")])[1])
    t.combos["gloves_prefix"].set_value("gloves_soloist")
    t.auction_buttons["gloves"].click()
    t.combos["gloves_prefix"].set_value(None)
    gate.set()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.01)
    assert t.auction_state["gloves"] is None and t.auction_lines["gloves"].isHidden()


@pytest.mark.parametrize("case,text", [("none", "이 옵션 그대로인 매물이 없어요"), ("fail", "경매장 조회에 실패했어요"),
                                       ("nokey", "넥슨 API 키가 없어 조회할 수 없어요")])
def test_none_fail_nokey_lines(tab, monkeypatch, case, text):
    t, app = tab
    if case == "none":
        monkeypatch.setattr(ma, "fetch", lambda *a, **k: [_item(1, _ench("접두", "솔리스트"), name="장갑")])
    elif case == "fail":
        def boom(req, timeout):
            raise OSError("network down")
        monkeypatch.setattr("urllib.request.urlopen", boom)
    else:
        monkeypatch.setattr(config, "get_nexon_api_key", lambda: None)
    t.combos["shoes_prefix"].set_value("shoes_janheo")
    t.auction_buttons["shoes"].click()
    _wait(app, t, "shoes")
    assert t.auction_state["shoes"] == case
    assert t.auction_lines["shoes"].text() == text and not t.auction_lines["shoes"].isHidden()
