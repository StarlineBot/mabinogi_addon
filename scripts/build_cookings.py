"""요리 계산기 데이터 만들기(docs/cooking-spec.md 2절) — 봇 저장소의 modules/cookings.js → assets/cooking/cookings.json.

원본은 봇 저장소 `StarlineBot/discord_bot`의 `modules/cookings.js` 하나(공개 main). 봇 데이터를 고치면 다음 앱 배포에
자동 반영되도록 Windows 빌드(packaging/build_windows.py)가 시작할 때 이 스크립트를 돌린다. 앱 실행 중 네트워크는 쓰지 않는다.

    uv run python -m scripts.build_cookings              # 공개 main에서 받아 만들기
    uv run python -m scripts.build_cookings --source 경로 # 내려받은 cookings.js로 만들기

넣는 요리: isCatering이 참이고 조리방법(localCookingType)·레시피(localRecipe)가 있는 것. 형식이 틀린 항목은 빼고 개수를 출력한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/StarlineBot/discord_bot/main/modules/cookings.js"
OUT = Path(__file__).resolve().parents[1] / "src" / "mabinogi_addon" / "assets" / "cooking" / "cookings.json"
MIN_COUNT = 380  # 11-19 기준 387개 — 크게 줄면 원본이 깨진 것
_KEY = re.compile(r'^(\s*)([A-Za-z_]\w*)\s*:', re.MULTILINE)
_PART = re.compile(r'\s*([^()]+?)\s*\(\s*(\d+(?:\.\d+)?)\s*%\s*\)')


def parse_js(text: str) -> list[dict]:
    """`const cookings = [...]` 객체 리터럴 → 파이썬 목록. 키는 줄 맨 앞 식별자만 따옴표로 감싼다(값 문자열은 건드리지 않음)."""
    start, end = text.index("["), text.rindex("]")
    body = _KEY.sub(lambda m: f'{m.group(1)}"{m.group(2)}":', text[start:end + 1])
    body = re.sub(r",(\s*[\]}])", r"\1", body)  # 끝 쉼표
    return json.loads(body)


def parse_recipe(text: str) -> list[dict] | None:
    """'브리흐네 위스키(40%) 라인산 진(40%) 얼음(30%)' → [{name, ratio}] (원문 순서). 형식이 틀리면 None."""
    text = (text or "").strip()
    parts, pos = [], 0
    for m in _PART.finditer(text):
        if text[pos:m.start()].strip():
            return None
        parts.append({"name": m.group(1).strip(), "ratio": float(m.group(2))})
        pos = m.end()
    if not parts or text[pos:].strip() or any(p["ratio"] <= 0 for p in parts):
        return None
    for p in parts:
        if p["ratio"].is_integer():
            p["ratio"] = int(p["ratio"])
    return parts


def select(raw: list[dict]) -> tuple[list[dict], dict]:
    """앱에 넣을 요리와 센 값({'catering', 'no_method', 'bad', 'kept'})."""
    out, stats = [], {"catering": 0, "no_method": 0, "bad": 0, "kept": 0}
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or item.get("isCatering") is not True:
            continue
        stats["catering"] += 1
        method, recipe_text = (item.get("localCookingType") or "").strip(), (item.get("localRecipe") or "").strip()
        if not method or not recipe_text:
            stats["no_method"] += 1  # 레시피 없는 이벤트·NPC·상점 품목
            continue
        name = (item.get("localName") or "").strip()
        recipe = parse_recipe(recipe_text)
        status = [{"name": str(s["name"]).strip(), "value": s["value"]} for s in item.get("status") or []
                  if isinstance(s, dict) and str(s.get("name") or "").strip()
                  and isinstance(s.get("value"), (int, float)) and not isinstance(s.get("value"), bool)]
        if not name or recipe is None or name in seen:
            stats["bad"] += 1
            continue
        seen.add(name)
        out.append({"name": name, "method": method, "recipe": recipe, "status": status})
    out.sort(key=lambda d: d["name"])
    stats["kept"] = len(out)
    return out, stats


def fetch(url: str = URL, timeout: float = 30.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def build(text: str, out: Path = OUT) -> dict:
    dishes, stats = select(parse_js(text))
    if len(dishes) < MIN_COUNT:
        raise ValueError(f"요리가 {len(dishes)}개뿐이에요(최소 {MIN_COUNT}) — 원본 형식을 확인해 주세요: {stats}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": URL, "dishes": dishes}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="내려받은 cookings.js 경로(없으면 공개 main에서 받음)")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # 콘솔이 cp1252여도 한글 요약 줄 때문에 실패하지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    text = Path(args.source).read_text(encoding="utf-8") if args.source else fetch()
    stats = build(text, Path(args.out))
    print(f"요리 데이터: 단체 요리 {stats['catering']}개 중 넣음 {stats['kept']}개 · 조리방법 없음 {stats['no_method']}개 · "
          f"형식 틀림 {stats['bad']}개 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
