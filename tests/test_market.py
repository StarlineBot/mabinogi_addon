"""경매 편의 계산: 수수료 분배 / 환전 효율 / 조회·표기 유틸."""

import json

from mabinogi_addon.market import auction, exchange, fee


# ---- korean_gold ----
def test_korean_gold():
    assert auction.korean_gold(5000) == "5,000"
    assert auction.korean_gold(10000) == "1만"
    assert auction.korean_gold(88_900_000) == "8,890만"
    assert auction.korean_gold(2_250_000_000) == "22억 5,000만"
    assert auction.korean_gold(100_000_000) == "1억"


# ---- min_unit_price ----
def test_min_unit_price_exact_name_only():
    items = [
        {"item_display_name": "경매장 수수료 10% 할인 쿠폰", "auction_price_per_unit": 300},
        {"item_display_name": "경매장 수수료 10% 할인 쿠폰", "auction_price_per_unit": 250},
        {"item_display_name": "다른 아이템", "auction_price_per_unit": 1},
    ]
    assert auction.min_unit_price(items, "경매장 수수료 10% 할인 쿠폰") == 250
    assert auction.min_unit_price(items, "없는 이름") is None


# ---- fetch_items_by_name (가짜 urlopen, 페이지네이션) ----
def test_fetch_items_paginates():
    pages = [
        {"auction_item": [{"item_display_name": "A", "auction_price_per_unit": 10}], "next_cursor": "c1"},
        {"auction_item": [{"item_display_name": "A", "auction_price_per_unit": 20}], "next_cursor": None},
    ]
    calls = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        return _Resp(pages[len(calls) - 1])

    items = auction.fetch_items_by_name("A", "key", urlopen=fake_urlopen)
    assert len(items) == 2
    assert len(calls) == 2  # next_cursor 따라 2페이지
    assert "cursor=c1" in calls[1]


# ---- 분배 계산 ----
def test_calc_distribution_basic_no_coupon():
    r = fee.calc_distribution(88_900_000, 5, membership=True, coupon_prices={})
    assert r["fee_base"] == 3_556_000  # 4%
    none_row = next(x for x in r["rows"] if x["name"] is None)
    assert none_row["per_person"] == (88_900_000 - 3_556_000) // 5


def test_calc_distribution_picks_best_coupon():
    # 100% 할인 쿠폰이 아주 싸면 그게 최적(수수료 전액 면제 + 저렴한 쿠폰값).
    prices = {
        "경매장 수수료 10% 할인 쿠폰": 10_000_000,
        "경매장 수수료 100% 할인 쿠폰": 100,
    }
    r = fee.calc_distribution(100_000_000, 4, membership=False, coupon_prices=prices)
    assert r["best"]["name"] == "경매장 수수료 100% 할인 쿠폰"
    # 조회 안 된 쿠폰(가격 None)은 제외.
    row20 = next(x for x in r["rows"] if x["pct"] == 0.20)
    assert row20["available"] is False and row20["per_person"] is None


def test_calc_distribution_base_rate_5pct():
    r = fee.calc_distribution(100_000_000, 1, membership=False, coupon_prices={})
    assert r["fee_base"] == 5_000_000


# ---- 환전 효율 ----
def test_calc_region_efficiency_sorted():
    prices = {
        "끈적이게 엉긴 식물 덩어리": 300,  # coin 3 → 100
        "고리아스 동력원": 400_000,  # coin 200 → 2000
        "빛바랜 에너지 회로": None,  # 매물 없음
    }
    rows = exchange.calc_region("탈라가흐", lambda name: prices.get(name))
    assert rows[0]["name"] == "고리아스 동력원"  # 효율 최고 먼저
    assert rows[0]["efficiency"] == 2000
    # 매물 없는 재료는 efficiency None, 맨 뒤.
    assert rows[-1]["efficiency"] is None


def test_calc_region_unknown():
    assert exchange.calc_region("없는지역", lambda n: None) is None
