"""기본 디버프 아이콘을 게임 원본 16px로 교체(2026-10-26 사용자 결정: 10종 + 방해 카드·붕괴의 파동·쿤).

예전 28px는 다른 곳에서 가져온 그림으로, 원본 16px를 1.75배 부드럽게 확대한 것과 같았다(유사도 0.997~0.999).
엔진이 다시 16px로 줄이며 두 번 번져 정답 점수는 0.9 안팎, 바닥·다른 아이콘에는 더 높게 붙었다.
원본은 보스 스크린샷의 디버프 줄에서 픽셀 그대로 잘랐고(10종은 2026-10-25 원본, 3종은 10-16 원본 — QA 자료 크롭과 동일),
예전 28px는 오버레이 표시용(image/)으로 바이트 그대로 보존한다.
"""

import hashlib
import json
from pathlib import Path

import pytest

from mabinogi_addon import catalog, image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/data/스크린샷 2026-10-25 150822.png"
MANIFEST = json.loads((ROOT / "docs/qa/assets/debuff_native_20261016/manifest.json").read_text(encoding="utf-8"))
NAMES = {item["id"]: item["name"] for item in MANIFEST["icons"]}
# 원본 위치(x, y)와 예전 28px의 Git blob. 10종은 새 원본의 보스 디버프 줄(시작 1025,1214 · 간격 18).
NATIVE = {
    "물리 방어력 보호 감소": (SOURCE, 1025, 1214, "fc955df93058ee4bb0d51bef064884aabad9064a"),
    "마법 방어력 보호 감소": (SOURCE, 1043, 1214, "f89a78bf8dd27d88ceed090fb1472de0981316e8"),
    "받는 대미지 증가": (SOURCE, 1061, 1214, "fb43371422b2a2d04a3d410cb74359234a93a6fb"),
    "케라": (SOURCE, 1079, 1214, "a8f39357796f740c7b3706b3cdbb91c8ce87deb4"),
    "물풍선": (SOURCE, 1169, 1214, "9eb5c8754924b982628c758e024e52e270b3fb3e"),
    "야옹이": (SOURCE, 1187, 1214, "681bd3b296412141e37076e11ea2f28816a465fb"),
    "프라가라흐(물리)": (SOURCE, 1205, 1214, "5059e75ab861fdb639568190883d67e7942f38c6"),
    "프라가라흐(마법)": (SOURCE, 1223, 1214, "d85e54b45fee6c4d2dc140db7ceeff8de0ca75ea"),
    "모모": (SOURCE, 1277, 1214, "42fee9a1695da6710a85b5a84e4aee0ca8625afc"),
    "불협화음": (SOURCE, 1295, 1214, "432933fb331febb1a264f5f9cf286f30ba1bd955"),
    "방해 카드": (ROOT / "tests/data/스크린샷 2026-10-16 213733.png", 1113, 1212, "1428de0a148a20860b45a54da4baed5acc6c33a3"),
    "붕괴의 파동": (ROOT / "tests/data/스크린샷 2026-10-16 213830.png", 1023, 1212, "7f818046c7b4f8edbc55aad7f62e46bf1f2d1730"),
    "쿤": (ROOT / "tests/data/스크린샷 2026-10-16 213335.png", 1023, 1212, "c13675f67a0f60f8c7942f3c9d7d784d7a01460a"),
}
# 원본 외에 같은 아이콘이 확인된 칸(라벨 장면 밖): 붕괴의 파동 다중 장면, 쿤 화면 중앙
EXTRA = [("붕괴의 파동", ROOT / "tests/data/스크린샷 2026-10-16 213733.png", 1077, 1212),
         ("쿤", ROOT / "tests/data/스크린샷 2026-10-16 213335.png", 1366, 379)]


def entries():
    return {item.id: item for item in catalog.load_debuff_catalog(icon_dirs=(catalog.DEFAULT_DEBUFF_ICON_DIR,))}


def blob(path):
    raw = path.read_bytes()
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


@pytest.mark.parametrize("name", sorted(NATIVE))
def test_match_icon_is_native_crop_and_old_picture_is_kept_for_display(name):
    source, x, y, old_blob = NATIVE[name]
    item = entries()[name]
    assert (image_io.imread(item.match_icon) == image_io.imread(source)[y:y + 16, x:x + 16]).all()
    assert item.display_image is not None and blob(item.display_image) == old_blob
    assert image_io.imread(item.display_image).shape == (28, 28, 3)


def _detected(runtime, patch):
    """실제 판정 경로(디바운스·물/마 구분 포함)로 0.6초 동안 같은 칸을 넣고 '걸림'으로 숨긴 디버프."""
    order = list(runtime._order)
    result = None
    for step in range(5):
        result = runtime.tick(patch, now=step * 0.15)
    return set(order) - {entry.buff_id for entry in result.entries}


def _labeled_slots():
    frames = {}
    for scene in MANIFEST["scenes"]:
        frame = frames.setdefault(scene["source"], image_io.imread(ROOT / scene["source"]))
        x0, y = scene["row_xy"]
        for index, label in enumerate(scene["labels"]):
            if label.startswith("D"):
                x = x0 + index * scene["stride"]
                yield scene["id"], index, NAMES[label], frame[y - 2:y + 18, x - 2:x + 18]
    for name, source, x, y in [(name, *value[:3]) for name, value in NATIVE.items()] + EXTRA:
        frame = frames.setdefault(source, image_io.imread(source))
        yield source.name, x, name, frame[y - 2:y + 18, x - 2:x + 18]


def test_each_identified_slot_hides_only_its_own_debuff():
    """라벨이 확정된 모든 칸(흐린 S21 포함)에서 그 디버프만 '걸림'이고 다른 기본 디버프는 걸리지 않는다."""
    templates = catalog.build_templates(list(entries().values()))
    failures = []
    for scene, index, name, patch in _labeled_slots():
        runtime = DebuffEngine(templates, list(templates))
        expected = {name} if name in templates else set()
        got = _detected(runtime, patch)
        if got != expected:
            failures.append((scene, index, name, sorted(got)))
    assert failures == []


@pytest.mark.parametrize("name, old_floor", [("모모", 0.68), ("방해 카드", 0.64)])
def test_native_low_detail_icons_score_lower_on_empty_floor(name, old_floor):
    """정보가 적어 바닥에 잘 붙던 모모·방해 카드: 예전 흐린 그림은 빈 바닥(보스 없음)에 모모 0.686·방해 카드 0.648,
    원본은 0.580·0.551로 일반 감지 기준(0.68) 아래, 예전보다 0.09 이상 낮다."""
    floor = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-12 024008.png")[1210:1289, 1017:1541]
    item = entries()[name]
    native = DebuffEngine({name: image_io.imread(item.match_icon)}, [name])
    old = DebuffEngine({name: image_io.imread(item.display_image)}, [name])
    before, after = old.best_scores(floor)[name], native.best_scores(floor)[name]
    assert before >= old_floor
    assert after < 0.68 and after <= before - 0.09
