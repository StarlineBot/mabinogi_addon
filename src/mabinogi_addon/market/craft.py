"""제작 재료 계산기(docs/craft-material-calculator-spec.md) — 화면과 무관한 데이터·계산·시세 캐시.

- 데이터: assets/craft/*.json 한 파일 = 한 시리즈 `{series, source, items: [{name, skill, materials: [[재료, 개수], …]}]}`.
  시리즈는 파일만 늘리면 된다(화면 코드에 무기 이름을 쓰지 않는다).
- 계산은 순수 함수(네트워크 없음). 시세는 재료별 10분 세션 메모리 캐시(무기끼리 공유, 영구 저장 안 함).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .. import paths

CACHE_SECONDS = 600.0
OWNED_MAX = 9999
FAILED = "failed"  # 시세 칸: 조회 실패(매물 없음 = None, 값 = 최저 개당가)


@dataclass(frozen=True)
class Item:
    name: str
    skill: str
    materials: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Series:
    name: str
    source: str
    items: tuple[Item, ...]


def data_dir() -> Path:
    return paths.resource_dir() / "craft"


def load_series(directory: Path | None = None) -> list[Series]:
    """시리즈 목록(파일 이름 순). 형식이 틀린 파일은 건너뛴다."""
    directory = data_dir() if directory is None else Path(directory)
    out: list[Series] = []
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = tuple(
                Item(str(i["name"]), str(i["skill"]), tuple((str(m), int(n)) for m, n in i["materials"]))
                for i in raw["items"])
            if items:
                out.append(Series(str(raw["series"]), str(raw.get("source", "")), items))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


@dataclass(frozen=True)
class Row:
    material: str
    need: int
    owned: int
    left: int
    price: int | None | str  # 최저 개당가 | None(매물 없음) | FAILED | "" (아직 모름)
    cost: int | None  # 남은 가격(남음 × 최저가) — 값을 모르면 None

    @property
    def done(self) -> bool:
        return self.left == 0


@dataclass(frozen=True)
class Summary:
    rows: tuple[Row, ...]  # 남은 재료 위, 다 모은 재료 아래(각 묶음 안은 데이터 순서)
    left_kinds: int  # 남은 재료 종 수
    total: int  # 값을 아는 남은 재료의 남은 가격 합
    no_listing: int  # 남은 재료 중 매물 없음 종 수(합계에서 빠짐)
    failed: int  # 남은 재료 중 조회 실패 종 수(합계에서 빠짐)


def clamp_owned(value) -> int:
    try:
        return max(0, min(OWNED_MAX, int(value)))
    except (TypeError, ValueError):
        return 0


def compute(item: Item, owned: dict[str, int], prices: dict) -> Summary:
    """무기 하나의 표·합계. owned = {재료: 보유}, prices = {재료: 최저가|None(매물 없음)|FAILED}, 없는 재료 = 아직 모름."""
    rows = []
    for material, need in item.materials:
        have = clamp_owned(owned.get(material, 0))
        left = max(0, need - have)
        price = prices.get(material, "")
        cost = left * price if isinstance(price, int) and not isinstance(price, bool) else None
        rows.append(Row(material, need, have, left, price, cost))
    ordered = [r for r in rows if not r.done] + [r for r in rows if r.done]
    left_rows = [r for r in rows if not r.done]
    return Summary(
        rows=tuple(ordered),
        left_kinds=len(left_rows),
        total=sum(r.cost for r in left_rows if r.cost is not None),
        no_listing=sum(1 for r in left_rows if r.price is None),
        failed=sum(1 for r in left_rows if r.price == FAILED),
    )


def order_by(rows, order: list[str]):
    """입력 중에는 줄이 움직이지 않게 — 정한 재료 순서(order)대로 다시 늘어놓는다."""
    index = {name: i for i, name in enumerate(order)}
    return sorted(rows, key=lambda r: index.get(r.material, len(index)))


class PriceCache:
    """재료별 시세 세션 캐시(10분). 값 = 최저가 | None(매물 없음). 조회 실패는 넣지 않는다(다음에 다시 조회)."""

    def __init__(self, clock=time.monotonic, seconds: float = CACHE_SECONDS) -> None:
        self._clock = clock
        self._seconds = seconds
        self._data: dict[str, tuple[float, int | None]] = {}

    def get(self, name: str):
        """(있음, 값). 10분 지났거나 없으면 (False, None)."""
        hit = self._data.get(name)
        if hit is None or self._clock() - hit[0] >= self._seconds:
            return False, None
        return True, hit[1]

    def put(self, name: str, value: int | None) -> None:
        self._data[name] = (self._clock(), value)

    def missing(self, names) -> list[str]:
        return [n for n in names if not self.get(n)[0]]

    def drop(self, names) -> None:
        for n in names:
            self._data.pop(n, None)
