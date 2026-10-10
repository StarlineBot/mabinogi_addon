"""경매장 조회(넥슨 오픈 API) + 표기 유틸.

파티 모집(client.py)과 같은 방식: 표준 urllib만 쓰고 urlopen을 주입할 수 있어
테스트에서 네트워크 없이 가짜 응답을 넣는다. auction/list는 item_name을 정확히
주면 그 이름의 매물을 돌려주며, next_cursor로 페이지네이션한다.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

API_BASE = "https://open.api.nexon.com"
_LIST_PATH = "/mabinogi/v1/auction/list"


def fetch_items_by_name(
    item_name: str,
    api_key: str,
    *,
    timeout: float = 10.0,
    urlopen: Callable = urllib.request.urlopen,
) -> list[dict]:
    """정확한 아이템명으로 현재 경매장 매물 전부(페이지네이션) 조회."""
    items: list[dict] = []
    cursor: str | None = None
    while True:
        params = {"item_name": item_name}
        if cursor:
            params["cursor"] = cursor
        url = f"{API_BASE}{_LIST_PATH}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"x-nxopen-api-key": api_key})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items.extend(data.get("auction_item") or [])
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return items


def min_unit_price(items: Iterable[dict], name: str) -> int | None:
    """이름이 정확히 일치하는 매물의 최저 개당가. 없으면 None."""
    prices = [
        it["auction_price_per_unit"]
        for it in items
        if it.get("item_display_name") == name
        and it.get("auction_price_per_unit") is not None
    ]
    return min(prices) if prices else None


def fetch_min_prices(
    names: Iterable[str],
    api_key: str,
    *,
    timeout: float = 10.0,
    max_workers: int = 8,
) -> dict[str, int | None]:
    """여러 아이템의 현재 경매장 최저 개당가를 병렬 조회(브리레흐 등 재료가 많아
    순차로는 느림). 각 이름 → 최저가(없으면 None). 개별 실패는 None 처리."""
    names = list(names)

    def _one(name: str) -> tuple[str, int | None]:
        try:
            items = fetch_items_by_name(name, api_key, timeout=timeout)
            return name, min_unit_price(items, name)
        except Exception:  # noqa: BLE001 — 한 아이템 실패가 전체를 막지 않게
            return name, None

    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(names)))) as ex:
        return dict(ex.map(_one, names))


def korean_gold(n: int) -> str:
    """금액 한글 표기: 2,250,000,000 → "22억 5,000만" (1만 미만은 원값)."""
    if n < 10000:
        return f"{n:,}"
    eok = n // 100_000_000
    man = (n % 100_000_000) // 10000
    s = ""
    if eok:
        s += f"{eok:,}억"
    if man:
        s += (" " if s else "") + f"{man:,}만"
    return s or f"{n:,}"
