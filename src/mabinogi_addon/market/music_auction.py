"""음악 버프 계산기 — 부위별 경매장 최저가(docs/music-buff-calculator-spec.md 6절, 0.52.0). Qt 없는 순수 함수.

흐름: 부위(악기·모자·옷·장갑·신발·액세서리 1·2·에코스톤) + 계산기 입력(state) → 조건(`criteria`)
→ 검색어(`queries`: 이름 또는 카테고리)로 매물을 모두 받고(`fetch`, next_cursor 끝까지) → 조건에 맞는 매물의
`auction_price_per_unit` 최소(`lowest`).

매물 글자 맞추기(명세 6.1):
- 세공: `option_type` '세공 옵션'(에코스톤은 '에코스톤 각성 능력'도), `option_value` '옵션명(N레벨:…)' 또는 '옵션명 N 레벨'.
  이름은 표의 `auction_name`(게임 표기)과 띄어쓰기를 빼고 비교. 같은 옵션을 두 줄 고르면 레벨 합 이상.
- 인챈트: `option_type` '인챈트', `option_sub_type` 접두/접미, `option_value`에 인챈트 이름(랭크 표기는 무시) — 이름 포함이면 맞음.
  같은 이름 여러 수치(폴리포니 +6~9 등)는 `option_desc`에 '음악 버프 … N' 숫자가 **있을 때만** 그 숫자로 가른다.
- 특개: `option_type` '특별 개조', `option_value` 단계 숫자 — 고른 단계 이상.
- 모자 장비(플루아의 풀잎 관): 아이템 이름에 장비명 포함 + 매물 옵션 글자에 음악 버프 숫자가 있으면 같은 +N.
※ 실제 매물 픽스처로 확정 전(이 개발 환경에서 넥슨 API 접속 불가) — `scripts/fetch_music_auction_fixtures.py`.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from . import auction
from . import music_buff as mb

PARTS = ("instrument", "head", "armor", "gloves", "shoes", "acc1", "acc2", "eco")
ECHOSTONE = "블루 에코스톤"
# 부위 → 검색어 [(종류, 값)] (명세 6절 '검색 대상'). 악기는 고른 악기 이름이라 queries()에서 채운다.
CATEGORY_QUERIES = {
    "head": (("category", "모자/가발"),),
    "armor": (("category", "경갑옷"), ("category", "중갑옷"), ("category", "천옷")),
    "gloves": (("category", "장갑"),),
    "shoes": (("category", "신발"),),
    "acc1": (("category", "액세서리"),),
    "acc2": (("category", "액세서리"),),
    "eco": (("name", ECHOSTONE),),
}
# 부위가 쓰는 계산기 입력 키(옵션을 바꾸면 그 부위 결과 줄을 지우는 기준)
PART_KEYS = {
    "instrument": ("instrument", "inst_prefix", "inst_suffix", "special_mod", "inst_reforge"),
    "head": ("head_equipment", "head_suffix"),
    "armor": ("armor_prefix",),
    "gloves": ("gloves_prefix",),
    "shoes": ("shoes_prefix", "shoes_reforge"),
    "acc1": ("acc1_prefix", "acc1_suffix", "acc1_reforge"),
    "acc2": ("acc2_prefix", "acc2_suffix", "acc2_reforge"),
    "eco": ("eco_reforge",),
}
_ENCHANT_KEYS = {  # 부위 → [(입력 키, 접두/접미)]
    "instrument": (("inst_prefix", "접두"), ("inst_suffix", "접미")),
    "head": (("head_suffix", "접미"),),
    "armor": (("armor_prefix", "접두"),),
    "gloves": (("gloves_prefix", "접두"),),
    "shoes": (("shoes_prefix", "접두"),),
    "acc1": (("acc1_prefix", "접두"), ("acc1_suffix", "접미")),
    "acc2": (("acc2_prefix", "접두"), ("acc2_suffix", "접미")),
}
_REFORGE_KEY = {"instrument": "inst_reforge", "shoes": "shoes_reforge", "acc1": "acc1_reforge",
                "acc2": "acc2_reforge", "eco": "eco_reforge"}
# 표 이름과 게임 표기가 다른 인챈트 검색어(명세 6.1 — 조화(앙상블)은 둘 다)
_ENCHANT_ALIASES = {"조화(앙상블)": ("앙상블", "조화")}
_REFORGE_TYPES = ("세공 옵션", "에코스톤 각성 능력")
_LEVEL = re.compile(r"^(.*?)\s*\(?\s*(\d+)\s*레벨")
_MUSIC_N = re.compile(r"음악 버프[^\d\n]*?(\d+)")


def _plain(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _base(name: str) -> str:
    """'폴리포니 (+9)' → '폴리포니'."""
    return re.sub(r"\s*\(\+\d+\)\s*$", "", name).strip()


@dataclass(frozen=True)
class Enchant:
    affix: str                 # 접두/접미
    names: tuple[str, ...]     # 매물 option_value에 들어 있어야 할 이름(하나라도)
    buff: int | None           # 같은 이름 여러 수치일 때만 option_desc 숫자로 구분


@dataclass(frozen=True)
class Criteria:
    part: str
    enchants: tuple[Enchant, ...] = ()
    reforges: tuple[tuple[str, int], ...] = ()   # (게임 세공 이름, 최소 레벨)
    special_mod: int = 0
    name_contains: str | None = None
    name_buff: int | None = None
    queries: tuple[tuple[str, str], ...] = field(default=())

    @property
    def empty(self) -> bool:
        return not (self.enchants or self.reforges or self.special_mod or self.name_contains)


def part_snapshot(part: str, state: dict) -> tuple:
    """옵션을 바꿨는지 비교하는 값(결과 줄 지우기)."""
    return tuple(json.dumps(state.get(k), sort_keys=True) for k in PART_KEYS[part])


def criteria(part: str, state: dict, t: dict | None = None) -> Criteria:
    t = t or mb.tables()
    enchants = []
    for key, affix in _ENCHANT_KEYS.get(part, ()):
        chosen = next((e for e in mb.options(key, t) if e["id"] == state.get(key)), None)
        if chosen is None:
            continue
        base = _base(chosen["name"])
        same = [e for e in mb.options(key, t) if _base(e["name"]) == base]
        enchants.append(Enchant(affix, _ENCHANT_ALIASES.get(base, (base,)),
                                chosen["buff"] if len(same) > 1 else None))
    reforges: dict[str, int] = {}
    if part in _REFORGE_KEY:
        key = _REFORGE_KEY[part]
        names = {o["id"]: o["auction_name"] for o in mb.reforge_options(key, t)}
        for opt, lv in state.get(key, []):
            if opt in names:
                reforges[names[opt]] = reforges.get(names[opt], 0) + max(lv, 1)  # Lv 0이면 그 옵션이 붙은 것만
    name_contains = name_buff = None
    if part == "head":
        equip = next((e for e in mb.options("head_equipment", t) if e["id"] == state.get("head_equipment")), None)
        if equip is not None:
            name_contains, name_buff = _base(equip["name"]), equip["buff"]
    special = int(state.get("special_mod") or 0) if part == "instrument" else 0
    if part == "instrument":
        inst = next((e for e in t["instruments"] if e["id"] == (state.get("instrument") or "lyre")), t["instruments"][0])
        queries = (("name", inst["name"]),)
    else:
        queries = CATEGORY_QUERIES[part]
    return Criteria(part, tuple(enchants), tuple(sorted(reforges.items())), special, name_contains, name_buff, queries)


# ---- 매물 글자 ----
def reforge_levels(item: dict) -> dict[str, int]:
    """매물의 세공(띄어쓰기 뺀 이름 → 레벨)."""
    out: dict[str, int] = {}
    for o in item.get("item_option") or []:
        if o.get("option_type") not in _REFORGE_TYPES:
            continue
        m = _LEVEL.match(str(o.get("option_value") or "").strip())
        if m:
            name = _plain(m.group(1))
            out[name] = max(out.get(name, 0), int(m.group(2)))
    return out


def _music_number(*texts) -> int | None:
    for text in texts:
        m = _MUSIC_N.search(str(text or ""))
        if m:
            return int(m.group(1))
    return None


def _enchant_ok(item: dict, want: Enchant) -> bool:
    for o in item.get("item_option") or []:
        if o.get("option_type") != "인챈트" or o.get("option_sub_type") != want.affix:
            continue
        value = str(o.get("option_value") or "")
        if not any(n in value for n in want.names):
            continue
        # 매물 인챈트는 보통 이름(+랭크)만 담긴다 → 이름으로 맞춘다. 효과 문구에 음악 버프 숫자가 있을 때만
        # 같은 이름 다른 수치(폴리포니 +8/+9 등)를 그 숫자로 가른다(없으면 수치 구분 없이 이름만).
        n = _music_number(o.get("option_desc"))
        if want.buff is None or n is None or n == want.buff:
            return True
    return False


def _special_mod(item: dict) -> int:
    for o in item.get("item_option") or []:
        if o.get("option_type") == "특별 개조":
            m = re.search(r"\d+", str(o.get("option_value") or ""))
            if m:
                return int(m.group())
    return 0


def matches(item: dict, c: Criteria) -> bool:
    if c.name_contains:
        if c.name_contains not in str(item.get("item_display_name") or item.get("item_name") or ""):
            return False
        n = _music_number(*(o.get("option_desc") for o in item.get("item_option") or []),
                          *(o.get("option_value") for o in item.get("item_option") or []
                            if o.get("option_type") != "인챈트"))
        if n is not None and c.name_buff is not None and n != c.name_buff:
            return False
    if not all(_enchant_ok(item, e) for e in c.enchants):
        return False
    have = reforge_levels(item)
    if any(have.get(_plain(name), 0) < lv for name, lv in c.reforges):
        return False
    return _special_mod(item) >= c.special_mod


def lowest(items: Iterable[dict], c: Criteria) -> int | None:
    prices = [it.get("auction_price_per_unit") for it in items if matches(it, c)]
    prices = [p for p in prices if type(p) is int and p > 0]
    return min(prices) if prices else None


# ---- 조회 ----
def fetch(queries: Iterable[tuple[str, str]], api_key: str, *, timeout: float = 10.0,
          urlopen: Callable = urllib.request.urlopen) -> list[dict]:
    """검색어마다 매물 전부(next_cursor 끝까지). 카테고리는 `auction_item_category`(디스코드 봇과 같은 파라미터)."""
    items: list[dict] = []
    for kind, value in queries:
        cursor = None
        while True:
            params = {"auction_item_category" if kind == "category" else "item_name": value}
            if cursor:
                params["cursor"] = cursor
            url = f"{auction.API_BASE}{auction._LIST_PATH}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers={"x-nxopen-api-key": api_key} if api_key else {})
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            items.extend(data.get("auction_item") or [])
            cursor = data.get("next_cursor")
            if not cursor:
                break
    return items
