"""개발 데이터(devdata) 디버프 아이콘의 원본 16px 교체 회귀(2026-10-26 사용자 요청: 슈터스 아이·마기그래프·공격력 감소·집중 도발).

슈터스 아이·마기그래프는 기본 제공이 아니라 devdata에만 있다. 예전 28px 이미지는 흐려서
슈터스 아이가 이름 미확정 슬롯(U14)에 0.67, 마기그래프가 모모 슬롯에 0.755(감지 기준 0.68 이상)까지
올랐다. 보스 디버프 줄 원본 픽셀(2560x1440)로 바꾸고, 정답은 그대로 잡으면서 다른 아이콘 슬롯에
감지 기준을 넘지 않는지 고정한다.
"""

import json
from pathlib import Path

import pytest

from mabinogi_addon import image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "devdata/debuff/icon"
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
