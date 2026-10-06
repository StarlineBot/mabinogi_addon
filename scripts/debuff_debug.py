"""디버프 매칭 진단.

전체화면 스크린샷과 디버프 영역(없으면 config.local.json의 debuffTracker 영역)을
받아, 등록된 디버프별 최고 매칭 점수를 출력한다. 점수로 원인을 가린다:
- 특정 디버프가 0.8 이상인데 안 사라진다 → 임계/안정화 쪽 문제
- 화면에 걸린 디버프인데 점수가 0.6~0.75 → 크기/숫자 겹침 → 임계 낮추거나 크롭 개선
- 전부 0.3 이하 → 아이콘 그림 자체가 보스 줄과 다름(다시 크롭 필요)

사용:
  uv run python scripts/debuff_debug.py <스크린샷.png> [x y w h]
좌표 생략 시 config.local.json의 debuffTracker.captureRegion 사용.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mabinogi_addon import config  # noqa: E402
from mabinogi_addon.catalog import build_templates, load_debuff_catalog  # noqa: E402
from mabinogi_addon.image_io import imread  # noqa: E402
from mabinogi_addon.tracker.debuff_engine import DebuffEngine  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 1:
        print(__doc__)
        return 2
    shot_path = Path(argv[0])
    image = imread(shot_path)
    if image is None:
        print(f"스크린샷을 못 읽음: {shot_path}")
        return 1

    if len(argv) >= 5:
        x, y, w, h = (int(v) for v in argv[1:5])
    else:
        region = config.load_capture_region("debuffTracker")
        if not region:
            print("디버프 영역이 저장돼 있지 않음. 좌표를 인자로 주세요: x y w h")
            return 1
        x, y, w, h = region["x"], region["y"], region["w"], region["h"]

    crop = image[y : y + h, x : x + w]
    print(f"스크린샷 {image.shape[1]}x{image.shape[0]}, 영역 ({x},{y}) {w}x{h} "
          f"→ crop {crop.shape[1]}x{crop.shape[0]}")

    catalog = load_debuff_catalog()
    engine = DebuffEngine(build_templates(catalog), [b.id for b in catalog])
    scores = engine.best_scores(crop)

    print("\n디버프별 최고 매칭 점수(높은 순):")
    for bid, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        mark = "◀ 감지" if score >= 0.8 else ""
        print(f"  {score:5.2f}  {bid}  {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
