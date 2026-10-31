"""번들 보스 패턴 데이터 로더 (기획서 12.4).

assets/boss/<id>/patterns.json = {"name": 표시이름, "thresholds": [..]} 를 읽어 보스 목록을
만든다. 이름 식별(boss_name_matcher)이 준 boss_id로 해당 임계값을 찾아 트래커를 만든다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .. import paths
from .boss_pattern import BossPatternTracker

_BOSS_DIR = paths.resource_dir() / "boss"


@dataclass(frozen=True)
class BossDef:
    id: str
    name: str  # 표시 이름(경고 문구에 사용)
    thresholds: tuple[int, ...]  # 내림차순


def load_bosses() -> dict[str, BossDef]:
    """{boss_id: BossDef}. patterns.json 없거나 깨진 폴더는 건너뛴다.
    순서 = patterns.json의 "order"(보스 탭 지원 목록 순서, 0.33.0 — 브론타나스를 페타크와 레넨 사이에), 없으면 폴더 이름 뒤."""
    found: list[tuple[float, str, BossDef]] = []
    if not _BOSS_DIR.exists():
        return {}
    for sub in sorted(p for p in _BOSS_DIR.iterdir() if p.is_dir()):
        pj = sub / "patterns.json"
        if not pj.exists():
            continue
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = data.get("name") or sub.name
        thr = sorted(
            {int(t) for t in data.get("thresholds", []) if isinstance(t, (int, float))},
            reverse=True,
        )
        order = data.get("order")
        order = float(order) if isinstance(order, (int, float)) and not isinstance(order, bool) else float("inf")
        found.append((order, sub.name, BossDef(id=sub.name, name=str(name), thresholds=tuple(thr))))
    return {boss.id: boss for _order, _name, boss in sorted(found, key=lambda item: item[:2])}


def make_tracker(boss: BossDef) -> BossPatternTracker:
    """보스 정의로 패턴 트래커 생성."""
    return BossPatternTracker(boss.name, list(boss.thresholds))
