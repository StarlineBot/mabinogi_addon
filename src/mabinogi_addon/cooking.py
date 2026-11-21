"""요리 계산기 순수 로직(docs/cooking-spec.md 2~4절) — Qt 없음.

- 데이터: assets/cooking/cookings.json(봇 저장소 modules/cookings.js에서 빌드 때 만든 것, scripts/build_cookings.py).
- 검색 = 필터: 요리 이름·재료(공백 무시·부분 일치)·능력치(이름 정확히). 맞는 요리 이름 묶음을 돌려주고 화면이 회색·개수로 쓴다.
- 비율: 원문 숫자는 상대 비율 — 각 값 ÷ 합계(50:20:40 → 45.45%·18.18%·36.36%, 경계 45.45%·63.64%).
- 재료 요리로 이동·되돌아가기: History(들어간 순서를 거꾸로).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import paths

# 3절: 카테고리 순서 고정(데이터에 없는 조리방법이 생기면 뒤에 붙인다)
CATEGORIES = ("혼합", "굽기", "삶기", "반죽", "끓이기", "면 만들기", "튀기기", "볶기", "파스타 만들기", "잼 만들기",
              "파이 만들기", "찌기", "피자 만들기", "발효", "수비드", "저미기")
SEARCH_KINDS = ("요리 이름", "재료", "능력치")
FAVORITES = "즐겨찾기"  # 카테고리 맨 위 가상 카테고리(사용자 결정 11-21, 0.55.0)


@dataclass(frozen=True)
class Ingredient:
    name: str
    ratio: float


@dataclass(frozen=True)
class Dish:
    name: str
    method: str
    recipe: tuple[Ingredient, ...]
    status: tuple[tuple[str, float], ...] = field(default=())


def data_path() -> Path:
    return paths.resource_dir() / "cooking" / "cookings.json"


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[Dish, ...]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for d in raw.get("dishes", []):
        try:
            recipe = tuple(Ingredient(str(r["name"]), float(r["ratio"])) for r in d["recipe"])
            status = tuple((str(s["name"]), s["value"]) for s in d.get("status", []))
            if recipe and all(r.ratio > 0 for r in recipe):
                out.append(Dish(str(d["name"]), str(d["method"]), recipe, status))
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(sorted(out, key=lambda x: x.name))


def load(path: Path | None = None) -> tuple[Dish, ...]:
    return _load(str(path or data_path()))


def norm(text: str | None) -> str:
    """공백 무시 비교용."""
    return "".join((text or "").split())


def categories(dishes) -> list[str]:
    extra = sorted({d.method for d in dishes} - set(CATEGORIES))
    return [*CATEGORIES, *extra]


def in_category(dishes, category: str) -> list[Dish]:
    """그 카테고리 요리, 이름순."""
    return sorted((d for d in dishes if d.method == category), key=lambda d: d.name)


def stat_names(dishes) -> list[str]:
    """능력치 검색 목록(데이터에 있는 이름, 가나다순)."""
    return sorted({name for d in dishes for name, _ in d.status})


def matches(dish: Dish, kind: str, query: str) -> bool:
    q = norm(query)
    if not q:
        return True
    if kind == "요리 이름":
        return q in norm(dish.name)
    if kind == "재료":
        return any(q in norm(i.name) for i in dish.recipe)
    if kind == "능력치":
        return any(norm(name) == q for name, _ in dish.status)
    return True


def search(dishes, kind: str, query: str) -> set[str] | None:
    """맞는 요리 이름 묶음. 검색어가 비면 None(검색 안 함 — 숫자·회색 없음)."""
    if not norm(query):
        return None
    return {d.name for d in dishes if matches(d, kind, query)}


def stat_value(dish: Dish, stat: str) -> float | None:
    """그 요리의 능력치 값(이름 공백 무시·정확히). 없으면 None."""
    q = norm(stat)
    for name, value in dish.status:
        if norm(name) == q:
            return value
    return None


def ranked(dishes, stat: str) -> list[tuple[Dish, float | None]]:
    """능력치 검색 목록 순서(사용자 결정 11-21): 그 능력치가 있는 요리를 수치 높은 순(같으면 이름순) 위로,
    없는 요리는 이름순으로 아래(화면에선 회색). [(요리, 값 또는 None)]."""
    pairs = [(d, stat_value(d, stat)) for d in dishes]
    hits = sorted((p for p in pairs if p[1] is not None), key=lambda p: (-p[1], p[0].name))
    misses = sorted((p for p in pairs if p[1] is None), key=lambda p: p[0].name)
    return hits + misses


def top_dishes(dishes, stat: str) -> set[str]:
    """그 능력치의 전체 요리 중 최고값 요리 이름(동점이면 모두, 없으면 빈 묶음) — ★ 표시."""
    values = {d.name: v for d in dishes if (v := stat_value(d, stat)) is not None}
    if not values:
        return set()
    best = max(values.values())
    return {name for name, v in values.items() if v == best}


def normalize_favorites(raw, dishes) -> list[str]:
    """저장된 즐겨찾기 → 데이터에 있는 요리 이름만, 추가 순서 유지·중복 없음."""
    names = {d.name for d in dishes}
    out: list[str] = []
    for name in raw if isinstance(raw, list) else []:
        if isinstance(name, str) and name in names and name not in out:
            out.append(name)
    return out


def favorite_dishes(dishes, favorites) -> list[Dish]:
    """즐겨찾기 카테고리의 요리(이름순 — 다른 카테고리와 같은 기본 순서)."""
    names = set(favorites)
    return sorted((d for d in dishes if d.name in names), key=lambda d: d.name)


def favorites_count(favorites, hits: set[str] | None) -> int:
    """즐겨찾기 줄 개수(검색 중이면 맞는 것만)."""
    return len(favorites) if hits is None else sum(1 for n in favorites if n in hits)


def category_counts(dishes, hits: set[str] | None) -> dict[str, int]:
    """카테고리별 (맞는) 요리 수."""
    counts = dict.fromkeys(categories(dishes), 0)
    for d in dishes:
        if hits is None or d.name in hits:
            counts[d.method] = counts.get(d.method, 0) + 1
    return counts


def ratios(recipe) -> list[float]:
    """각 값 ÷ 합계(0~1), 원문 순서."""
    values = [i.ratio for i in recipe]
    total = sum(values)
    return [v / total for v in values] if total > 0 else [0.0 for _ in values]


def boundaries(recipe) -> list[float]:
    """재료 경계(누적 비율, 마지막 1.0은 뺌)."""
    out, acc = [], 0.0
    for r in ratios(recipe)[:-1]:
        acc += r
        out.append(acc)
    return out


def dish_index(dishes) -> dict[str, Dish]:
    """공백 무시 이름 → 요리(재료가 요리인지 볼 때)."""
    return {norm(d.name): d for d in dishes}


def ingredient_dish(name: str, index: dict[str, Dish]) -> Dish | None:
    return index.get(norm(name))


class History:
    """재료 요리로 들어간 순서 — `← 바로 앞 요리`는 거꾸로 하나씩. 직접 고르거나 검색으로 바뀌면 지운다."""

    def __init__(self) -> None:
        self._stack: list[str] = []

    def enter(self, current: str, target: str) -> None:
        if current == target:
            return
        if target in self._stack:  # 순환(같은 요리 재등장): 그 요리까지 되감는다 — 같은 요리가 두 번 쌓이지 않게
            del self._stack[self._stack.index(target):]
            return
        self._stack.append(current)

    def back(self) -> str | None:
        return self._stack.pop() if self._stack else None

    def peek(self) -> str | None:
        return self._stack[-1] if self._stack else None

    def clear(self) -> None:
        self._stack.clear()

    def __len__(self) -> int:
        return len(self._stack)
