"""던전 구슬 환전 효율 계산 (discord_bot exchangeRate 이식).

지역별로 '구슬 N개 → 재료 1개' 교환 데이터(coin, 고정 게임 데이터)를 두고, 재료의
현재 경매장 개당가를 받아 효율(구슬당 골드 = 개당가 // 구슬수)을 구해 내림차순 정렬.
경매장 개당가 조회는 외부에서 넣는다 — 이 모듈은 순수 계산만 한다.
"""

from __future__ import annotations

from collections.abc import Callable

# 지역별 교환 재료: name = 경매장 정확명, coin = 재료 1개 교환에 드는 구슬 수.
REGIONS: dict[str, list[dict]] = {
    "탈라가흐": [
        {"name": "끈적이게 엉긴 식물 덩어리", "coin": 3},
        {"name": "빛바랜 에너지 회로", "coin": 35},
        {"name": "고리아스 동력원", "coin": 200},
        {"name": "순도 높은 힐웬 강판 조각", "coin": 6},
        {"name": "희미하게 빛나는 명주실", "coin": 3},
        {"name": "순도 높은 실리엔 섬유 다발", "coin": 6},
        {"name": "달아오른 광두정", "coin": 3},
        {"name": "순도 높은 힐웬 주괴 조각", "coin": 6},
    ],
    "브리레흐": [
        {"name": "브리 레흐의 코어", "coin": 100},
        {"name": "브리 레흐의 정수", "coin": 100},
        {"name": "녹음이 깃든 마법사의 보석", "coin": 1},
        {"name": "텅 빈 마력석", "coin": 3},
        {"name": "깨어난 힘의 정수", "coin": 5},
        {"name": "순백의 가죽 조각", "coin": 1},
        {"name": "녹음이 감도는 칼날 조각", "coin": 1},
        {"name": "순백의 깃털", "coin": 1},
        {"name": "초록빛 기억의 조각", "coin": 25},
        {"name": "오묘한 마력석", "coin": 3},
        {"name": "주황빛 기억의 조각", "coin": 25},
        {"name": "오묘한 가죽 조각", "coin": 3},
        {"name": "단단한 늑대의 이빨", "coin": 1},
        {"name": "금빛 기억의 조각", "coin": 25},
        {"name": "순도 높은 마력의 결정", "coin": 3},
        {"name": "녹음이 감도는 나무 장작", "coin": 1},
        {"name": "단단한 힐웬 광석 조각", "coin": 1},
        {"name": "무른 금속 파편", "coin": 3},
        {"name": "녹음이 감도는 광석 조각", "coin": 1},
        {"name": "빛바랜 자수실", "coin": 3},
        {"name": "브리 레흐의 기운이 깃든 문장", "coin": 3},
        {"name": "투명한 연금술 결정", "coin": 1},
        {"name": "마력석", "coin": 1},
        {"name": "아라고나이트", "coin": 3},
        {"name": "오피먼트", "coin": 3},
        {"name": "오묘한 금속 조각", "coin": 3},
        {"name": "바리사이트", "coin": 3},
        {"name": "무딘 칼날 조각", "coin": 3},
        {"name": "녹음이 감도는 금속 조각", "coin": 1},
    ],
    "글렌베르나": [
        {"name": "결정화된 겨울의 잔해", "coin": 35},
        {"name": "잘려 나간 겨울의 꿈 결정", "coin": 200},
        {"name": "얼어붙은 백철 조각", "coin": 6},
        {"name": "얼어붙은 직물 조각", "coin": 6},
        {"name": "얼어붙은 판금 조각", "coin": 6},
    ],
    "크롬바스": [
        {"name": "아다만티움", "coin": 200},
        {"name": "글라스 기브넨의 심장", "coin": 200},
        {"name": "손상된 글라스 기브넨의 깃털", "coin": 200},
    ],
}

REGION_NAMES: list[str] = list(REGIONS.keys())


def calc_region(
    region: str, price_lookup: Callable[[str], int | None]
) -> list[dict] | None:
    """한 지역 재료별 효율(구슬당 골드) 계산 + 효율 내림차순. price_lookup(name)은
    재료의 현재 경매장 최저 개당가(없으면 None)를 돌려준다. 없는 지역이면 None."""
    mats = REGIONS.get(region)
    if mats is None:
        return None
    rows: list[dict] = []
    for m in mats:
        per_unit = price_lookup(m["name"])
        efficiency = per_unit // m["coin"] if per_unit is not None else None
        rows.append(
            {
                "name": m["name"],
                "coin": m["coin"],
                "per_unit": per_unit,
                "efficiency": efficiency,
            }
        )
    rows.sort(key=lambda r: r["efficiency"] if r["efficiency"] is not None else -1, reverse=True)
    return rows
