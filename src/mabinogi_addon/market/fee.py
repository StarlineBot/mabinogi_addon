"""경매장 수수료 분배 계산 (discord_bot auctionFee 이식).

판매가·인원·멤버십으로 수수료(멤버십 4% / 기본 5%)를 계산하고, 수수료 할인 쿠폰별로
1인당 분배금을 구해 '쿠폰값까지 포함해 가장 이득인' 쿠폰을 고른다. 쿠폰 현재가는
외부(경매장 조회)에서 받아 넣는다 — 이 모듈은 순수 계산만 한다.
"""

from __future__ import annotations

import math

FEE_RATE_BASE = 0.05
FEE_RATE_MEMBERSHIP = 0.04

# 수수료 할인 쿠폰(경매장 '기타'). pct = 수수료를 깎는 비율. name = 경매장 조회용 정확명.
COUPONS: list[dict] = [
    {"pct": 0.0, "label": "쿠폰 없음", "name": None},
    {"pct": 0.10, "label": "10% 할인", "name": "경매장 수수료 10% 할인 쿠폰"},
    {"pct": 0.20, "label": "20% 할인", "name": "경매장 수수료 20% 할인 쿠폰"},
    {"pct": 0.30, "label": "30% 할인", "name": "경매장 수수료 30% 할인 쿠폰"},
    {"pct": 0.50, "label": "50% 할인", "name": "경매장 수수료 50% 할인 쿠폰"},
    {"pct": 1.00, "label": "100% 할인", "name": "경매장 수수료 100% 할인 쿠폰"},
]

# 쿠폰 조회에 쓸 이름들(경매장에서 최저가를 받아올 대상).
COUPON_NAMES: list[str] = [c["name"] for c in COUPONS if c["name"]]


def _round(x: float) -> int:
    # JS Math.round와 동일(.5는 올림) — discord_bot 결과와 일치시키기 위함.
    return math.floor(x + 0.5)


def calc_distribution(
    sale_price: int,
    headcount: int,
    membership: bool,
    coupon_prices: dict[str, int | None],
    etc: int = 0,
) -> dict:
    """쿠폰별 1인당 분배금 + 최적 쿠폰.

    수수료 = 판매가 × 세율, 할인후수수료 = 수수료 × (1-할인율)
    1인당 = (판매가 - 할인후수수료 - 쿠폰값 - 기타) // 인원
    최적 = 1인당이 가장 큰 쿠폰(쿠폰 현재가가 없으면 그 행은 제외).
    """
    rate = FEE_RATE_MEMBERSHIP if membership else FEE_RATE_BASE
    fee_base = _round(sale_price * rate)
    rows: list[dict] = []
    for c in COUPONS:
        fee_after = _round(fee_base * (1 - c["pct"]))
        if c["name"] is None:
            coupon_price: int | None = 0
            available = True
        else:
            coupon_price = coupon_prices.get(c["name"])
            available = coupon_price is not None
        if available:
            total_cost = fee_after + (coupon_price or 0) + etc
            per_person: int | None = (sale_price - total_cost) // headcount
        else:
            total_cost = None
            per_person = None
        rows.append(
            {
                "pct": c["pct"],
                "label": c["label"],
                "name": c["name"],
                "fee_after": fee_after,
                "coupon_price": coupon_price,
                "available": available,
                "total_cost": total_cost,
                "per_person": per_person,
            }
        )
    avail = [r for r in rows if r["available"] and r["per_person"] is not None]
    best = max(avail, key=lambda r: r["per_person"]) if avail else None
    return {"fee_base": fee_base, "rows": rows, "best": best}
