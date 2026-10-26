"""0.24.0에 기본 제공으로 추가한 디버프 4종(공격력 감소·마기그래프·슈터스 아이·집중 도발, 2026-10-26 사용자 결정).

원래 개발 데이터(devdata)에만 있던 사용자 아이콘이라 앱에는 없었다. 게임 원본 16px로 판독하고, 예전 흐린 28px는
다른 기본 디버프처럼 오버레이 표시용(image/)으로 보존한다. 예전 그림은 슈터스 아이가 이름 미확정 칸(U14)에 0.67,
마기그래프가 모모 칸에 0.755(감지 기준 0.68 이상)까지 올랐다. 정답은 잡고 다른 아이콘 칸에선 기준을 넘지 않는지 고정한다.
"""

import hashlib
import json
from pathlib import Path

import pytest

from mabinogi_addon import image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "src/mabinogi_addon/assets/debuff/icon"
IMAGES = ROOT / "src/mabinogi_addon/assets/debuff/image"
SOURCE = ROOT / "tests/data/스크린샷 2026-10-25 150822.png"
MANIFEST = json.loads((ROOT / "docs/qa/assets/debuff_native_20261016/manifest.json").read_text(encoding="utf-8"))
NAMES = {item["id"]: item["name"] for item in MANIFEST["icons"]}
# 새 원본에서 같은 아이콘이 보이는 위치(보스 디버프 줄, 마기그래프는 같은 픽셀 3개 + 머리 위 줄)
POSITIVES = {"슈터스 아이": [(1259, 1214), (1021, 223)],
             "마기그래프": [(1349, 1214), (1367, 1214), (1385, 1214)]}
# 공격력 감소는 2026-10-07 원본(1151,1214, QA 자료 크롭과 동일)에서 잘랐고 10-09 다른 장면(S25)에서도 확인된다.
OTHER_POSITIVES = {"공격력 감소": [("tests/data/스크린샷 2026-10-07 013118.png", 1151, 1214),
                                   ("tests/data/스크린샷 2026-10-09 201512.png", 1187, 1214)],
                   # 집중 도발은 2026-10-26 원본의 보스 머리 위 줄(1348,575, 배경 불투명·선명)에서 잘랐다(사용자 지정).
                   # 같은 화면 보스 디버프 줄(1041,1212)은 칸 배경이 비쳐 보이는 상태라 판독 확인용으로만 쓴다.
                   "집중 도발": [("tests/data/스크린샷 2026-10-26 175307.png", 1348, 575),
                               ("tests/data/스크린샷 2026-10-26 175307.png", 1041, 1212)]}


def engine(name):
    template = image_io.imread(ICONS / f"{name}.png")
    assert template is not None and template.shape == (16, 16, 3)
    return DebuffEngine({name: template}, [name])


@pytest.mark.parametrize("name", sorted(POSITIVES))
def test_native_icon_matches_its_slots(name):
    frame = image_io.imread(SOURCE)
    runtime = engine(name)
    for x, y in POSITIVES[name]:
        assert runtime.best_scores(frame[y - 2:y + 18, x - 2:x + 18])[name] >= 0.95, (name, x, y)


@pytest.mark.parametrize("name", sorted(OTHER_POSITIVES))
def test_native_icon_matches_other_scenes(name):
    runtime = engine(name)
    for source, x, y in OTHER_POSITIVES[name]:
        frame = image_io.imread(ROOT / source)
        assert runtime.best_scores(frame[y - 2:y + 18, x - 2:x + 18])[name] >= 0.9, (source, x, y)


@pytest.mark.parametrize("name", sorted(POSITIVES) + sorted(OTHER_POSITIVES))
def test_native_icon_stays_below_threshold_on_other_identified_slots(name):
    runtime = engine(name)
    threshold = runtime.detect_threshold_for(name)
    frames = {}
    for scene in MANIFEST["scenes"]:
        frame = frames.setdefault(scene["source"], image_io.imread(ROOT / scene["source"]))
        x0, y = scene["row_xy"]
        for index, label in enumerate(scene["labels"]):
            if not label.startswith("D") or NAMES[label] == name:
                continue
            x = x0 + index * scene["stride"]
            score = runtime.best_scores(frame[y - 2:y + 18, x - 2:x + 18])[name]
            assert score < threshold, (name, scene["id"], index, label, score)


# 예전(devdata) 28px의 Git blob — 표시용으로 바이트 그대로 보존
OLD_BLOBS = {"슈터스 아이": "d844443fd25ce4a8fd9b750e55df6226296ef6eb", "마기그래프": "c5d0465c6a22d4ff16ae6d1bb5cfd61770d1abea",
             "공격력 감소": "537fe852c085b7afa11e3aa95543a5dafe1211d2", "집중 도발": "52634ea367a21ec1e51845e2c2e400b402585c90"}


@pytest.mark.parametrize("name", sorted(OLD_BLOBS))
def test_added_default_is_bundled_with_old_picture_for_display(name):
    from mabinogi_addon import catalog
    item = {b.id: b for b in catalog.load_debuff_catalog(icon_dirs=(catalog.DEFAULT_DEBUFF_ICON_DIR,))}[name]
    assert item.match_icon == ICONS / f"{name}.png" and image_io.imread(item.match_icon).shape == (16, 16, 3)
    raw = item.display_image.read_bytes()
    assert hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == OLD_BLOBS[name]
    assert name in catalog.DEFAULT_DEBUFF_ORDER
