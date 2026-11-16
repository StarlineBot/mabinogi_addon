"""음악 버프 경매장 픽스처 받기(명세 6.1 '개발 확인 필요') — 넥슨 API 키가 있는 PC에서 한 번 실행.

    uv run python -m scripts.fetch_music_auction_fixtures

키는 앱과 같은 순서로 찾는다(.env NEXON_API_KEY → config.local.json nexonApiKey).
클라우드 세션처럼 프록시가 x-nxopen-api-key 헤더를 붙여 주는 곳에서는 `--no-key`(헤더를 직접 넣지 않음).
부위별 검색어(악기 두 이름·블루 에코스톤·모자/가발·경갑옷·중갑옷·천옷·장갑·신발·액세서리)의 매물을 모두 받아,
음악 버프 관련 옵션(음악 세공·음악 인챈트·특개)이 붙은 매물만 골라 `tests/data/music_auction/<검색어>.json`에 저장한다.
가격·이름·item_option만 남긴다(판매자 정보 없음 — API가 주지 않음). 키는 파일에 쓰지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from mabinogi_addon import config
from mabinogi_addon.market import music_auction as ma
from mabinogi_addon.market import music_buff as mb

OUT = Path(__file__).resolve().parents[1] / "tests" / "data" / "music_auction"
KEEP_TYPES = ("인챈트", "세공 옵션", "특별 개조", "에코스톤 등급", "에코스톤 고유 능력", "에코스톤 각성 능력")
PER_QUERY = 60


def _music_names() -> set[str]:
    t = mb.tables()
    return {re.sub(r"\s+", "", o["auction_name"]) for grp in t["reforge_options"].values() for o in grp}


def _relevant(item: dict, names: set[str]) -> bool:
    for o in item.get("item_option") or []:
        kind = o.get("option_type")
        if kind == "인챈트" and "음악" in str(o.get("option_desc") or ""):
            return True
        if kind in ("세공 옵션", "에코스톤 각성 능력") and any(n in re.sub(r"\s+", "", str(o.get("option_value"))) for n in names):
            return True
    return False


def main() -> int:
    key = "" if "--no-key" in sys.argv else config.get_nexon_api_key()
    if key is None:
        print("넥슨 API 키가 없어요(.env NEXON_API_KEY 또는 config.local.json nexonApiKey).")
        return 1
    t = mb.tables()
    queries = [("name", e["name"]) for e in t["instruments"]]
    queries += [q for part in ma.PARTS if part != "instrument" for q in ma.CATEGORY_QUERIES[part]]
    names = _music_names()
    OUT.mkdir(parents=True, exist_ok=True)
    seen = set()
    for q in queries:
        if q in seen:
            continue
        seen.add(q)
        items = ma.fetch([q], key)
        kinds = Counter(o.get("option_type") for it in items for o in it.get("item_option") or [])
        keep = [it for it in items if _relevant(it, names)]
        keep.sort(key=lambda it: it.get("auction_price_per_unit") or 0)
        slim = [{"item_name": it.get("item_name"), "item_display_name": it.get("item_display_name"),
                 "auction_price_per_unit": it.get("auction_price_per_unit"),
                 "item_option": [o for o in it.get("item_option") or [] if o.get("option_type") in KEEP_TYPES]}
                for it in keep[:PER_QUERY]]
        path = OUT / (re.sub(r"[^\w가-힣]+", "_", q[1]).strip("_") + ".json")
        path.write_text(json.dumps({"query": list(q), "total": len(items), "music": len(keep),
                                    "option_types": dict(kinds.most_common()), "items": slim},
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{q[1]}: 전체 {len(items)} · 음악 옵션 {len(keep)} → {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
