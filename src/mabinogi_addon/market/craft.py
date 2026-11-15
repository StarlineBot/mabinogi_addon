"""제작 재료 계산기(docs/craft-material-calculator-spec.md) — 화면과 무관한 데이터·계산·시세 캐시.

- 데이터: assets/craft/*.json 한 파일 = 한 시리즈. `kind`로 모양을 고른다.
  · simple(소울 리버레이트): `{series, kind, item_label, items: [{name, skill, materials: [[재료, 개수], …]}]}` — 재료 × 1.
  · process(더스크 바운드): `{series, kind, item_label, default_processes, items: [{name, class, skill, parts: [[짧은 이름, 이름], …],
    process_materials, finish_materials}]}` — 공정 재료 = 1공정 × 공정 횟수 × 부위 수, 마감 재료 = 수량 × 부위 수(명세 5절).
  시리즈는 파일만 늘리면 된다(화면 코드에 장비 이름을 쓰지 않는다). 순서는 파일의 `order`(없으면 파일 이름).
  `categories: [{name, items: [장비 이름]}]`가 있으면 드롭다운을 분류 머리로 묶는다(소울 리버레이트: 근접·마법·원거리·악기).
- 계산은 순수 함수(네트워크 없음). 시세는 재료별 10분 세션 메모리 캐시(장비끼리 공유, 영구 저장 안 함).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .. import paths

CACHE_SECONDS = 600.0
OWNED_MAX = 9999
PROCESS_MIN, PROCESS_MAX = 1, 30
FAILED = "failed"  # 시세 칸: 조회 실패(매물 없음 = None, 값 = 최저 개당가)
SIMPLE, PROCESS = "simple", "process"
GROUP_PROCESS, GROUP_FINISH = "process", "finish"


@dataclass(frozen=True)
class Item:
    name: str
    skill: str
    materials: tuple[tuple[str, int], ...] = ()  # simple
    cls: str = ""  # process: 중갑·경갑·천옷
    parts: tuple[tuple[str, str], ...] = ()  # process: (짧은 이름, 부위 이름)
    process_materials: tuple[tuple[str, int], ...] = ()  # process: 1공정 수량
    finish_materials: tuple[tuple[str, int], ...] = ()  # process: 부위마다 1번

    @property
    def label(self) -> str:
        """드롭다운 글자(세트는 '이지스 · 중갑')."""
        return f"{self.name} · {self.cls}" if self.cls else self.name

    def material_names(self) -> list[str]:
        """시세를 조회할 재료 전부(부위·공정과 무관)."""
        names = [m for m, _ in self.materials + self.process_materials + self.finish_materials]
        return list(dict.fromkeys(names))


@dataclass(frozen=True)
class Series:
    name: str
    source: str
    items: tuple[Item, ...]
    kind: str = SIMPLE
    item_label: str = "무기"
    default_processes: int = 7
    # 드롭다운 분류(0.50.0, 사용자 결정 11-15): ((분류 이름, (items 순번, …)), …). 비면 분류 없이 데이터 순서.
    categories: tuple[tuple[str, tuple[int, ...]], ...] = ()

    def menu(self) -> list[tuple[str, int | None]]:
        """드롭다운 줄: [(글자, items 순번 | None=분류 머리)]. 분류가 없으면 장비만."""
        if not self.categories:
            return [(item.label, i) for i, item in enumerate(self.items)]
        out: list[tuple[str, int | None]] = []
        for name, indexes in self.categories:
            out.append((name, None))
            out += [(self.items[i].label, i) for i in indexes]
        return out


def data_dir() -> Path:
    return paths.resource_dir() / "craft"


def _pairs(raw) -> tuple[tuple[str, int], ...]:
    out = tuple((str(m), int(n)) for m, n in raw)
    if any(n <= 0 for _, n in out):
        raise ValueError("개수는 양의 정수")
    return out


def _item(raw: dict, kind: str) -> Item:
    if kind == PROCESS:
        return Item(str(raw["name"]), str(raw["skill"]), cls=str(raw.get("class", "")),
                    parts=tuple((str(a), str(b)) for a, b in raw["parts"]),
                    process_materials=_pairs(raw["process_materials"]), finish_materials=_pairs(raw["finish_materials"]))
    return Item(str(raw["name"]), str(raw["skill"]), materials=_pairs(raw["materials"]))


def _categories(raw, items: tuple[Item, ...]) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """`categories: [{name, items: [장비 이름, …]}]` → 순번. 모든 장비가 정확히 한 번씩이 아니면 분류를 쓰지 않는다."""
    if not raw:
        return ()
    index = {item.name: i for i, item in enumerate(items)}
    out = tuple((str(c["name"]), tuple(index[str(n)] for n in c["items"])) for c in raw)
    flat = [i for _n, idx in out for i in idx]
    if sorted(flat) != list(range(len(items))):
        raise ValueError("분류에 모든 장비가 정확히 한 번씩 있어야 함")
    return out


def load_series(directory: Path | None = None) -> list[Series]:
    """시리즈 목록(`order`, 그다음 파일 이름 순). 형식이 틀린 파일은 건너뛴다."""
    directory = data_dir() if directory is None else Path(directory)
    found: list[tuple[int, str, Series]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            kind = raw.get("kind", SIMPLE)
            if kind not in (SIMPLE, PROCESS):
                continue
            items = tuple(_item(i, kind) for i in raw["items"])
            if items:
                try:
                    categories = _categories(raw.get("categories"), items)
                except (KeyError, TypeError, ValueError):
                    categories = ()  # 분류가 틀리면 분류 없이(장비는 그대로 보임)
                series = Series(str(raw["series"]), str(raw.get("source", "")), items, kind,
                                str(raw.get("item_label") or ("세트" if kind == PROCESS else "무기")),
                                int(raw.get("default_processes", 7)), categories)
                found.append((int(raw.get("order", 100)), path.name, series))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return [s for _o, _n, s in sorted(found, key=lambda x: (x[0], x[1]))]


def requirements(item: Item, parts: int = 1, processes: int = 1) -> list[tuple[str, list[tuple[str, int]]]]:
    """[(묶음, [(재료, 필요 수량)])]. simple = [("", 재료)], process = [(공정, 1공정 × 공정 × 부위), (마감, 수량 × 부위)].
    부위 0개면 빈 목록."""
    if item.materials:
        return [("", list(item.materials))]
    parts = max(0, int(parts))
    processes = max(PROCESS_MIN, min(PROCESS_MAX, int(processes)))
    if parts == 0:
        return []
    return [(GROUP_PROCESS, [(m, n * processes * parts) for m, n in item.process_materials]),
            (GROUP_FINISH, [(m, n * parts) for m, n in item.finish_materials])]


@dataclass(frozen=True)
class Row:
    material: str
    need: int
    owned: int
    left: int
    price: int | None | str  # 최저 개당가 | None(매물 없음) | FAILED | "" (아직 모름)
    cost: int | None  # 남은 가격(남음 × 최저가) — 값을 모르면 None
    group: str = ""  # 묶음(process: 공정 재료 / 마감 재료)

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


def compute(item: Item, owned: dict[str, int], prices: dict, *, parts: int = 1, processes: int = 1) -> Summary:
    """장비 하나의 표·합계. owned = {재료: 보유}, prices = {재료: 최저가|None(매물 없음)|FAILED}, 없는 재료 = 아직 모름.
    줄 순서: 묶음 순서대로, 묶음 안에서는 남은 재료 위·다 모은 재료 아래(각각 데이터 순서)."""
    ordered, left_rows = [], []
    for group, materials in requirements(item, parts, processes):
        rows = []
        for material, need in materials:
            have = clamp_owned(owned.get(material, 0))
            left = max(0, need - have)
            price = prices.get(material, "")
            cost = left * price if isinstance(price, int) and not isinstance(price, bool) else None
            rows.append(Row(material, need, have, left, price, cost, group))
        ordered += [r for r in rows if not r.done] + [r for r in rows if r.done]
        left_rows += [r for r in rows if not r.done]
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
