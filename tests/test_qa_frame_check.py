"""QA 그림 검증 도구(사용자 지시 11-27) — 원본 그대로인 그림은 통과, 입을 합성해 얼룩이 생긴 그림은 잡는지."""
import subprocess

import cv2
import numpy as np
import pytest

from scripts import qa_frame_check as q


def test_block_diff_flags_composited_blotch_but_not_webp_loss():
    src = q.source_map("Starline")
    if not src:
        pytest.skip("Starline 원본 없음")
    clean = q.read(q.CHARS / "Starline" / "stand_12.webp")
    original = q.read(src["stand_12"])
    assert q.block_diff(clean, original)[0] < q.BLOCK_LIMIT
    blot = clean.copy()
    x, y = 96, 120
    rng = np.random.default_rng(0)
    blot[y:y + 12, x:x + 12, :3] = np.clip(blot[y:y + 12, x:x + 12, :3].astype(int)
                                            + rng.integers(-60, 60, (12, 12, 3)), 0, 255).astype(np.uint8)
    assert q.block_diff(blot, original)[0] > q.BLOCK_LIMIT


def test_reverted_bad_mouth_build_is_caught_when_available():
    """0.59.1 입 합성 판(6bd27072) — 기록이 있으면 대부분의 서 있기 장이 '원본과 다름'으로 잡혀야 함."""
    src = q.source_map("Starline")
    caught = 0
    for i in range(30):
        raw = subprocess.run(["git", "show", f"6bd27072:src/mabinogi_addon/assets/characters/Starline/stand_{i}.webp"],
                             cwd=q.ROOT, capture_output=True).stdout
        if not raw or f"stand_{i}" not in src:
            pytest.skip("기록 없음")
        bad = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
        caught += q.block_diff(bad, q.read(src[f"stand_{i}"]))[0] > q.BLOCK_LIMIT
    assert caught >= 25


def test_current_starline_has_no_source_edits():
    problems = q.check("Starline")
    assert not [p for p in problems if p.startswith("원본과 다름")], problems


def test_current_starline_sitting_loop_to_rise_has_no_jump():
    """QA 11-28: 앉아 있다 일어나기는 반복 중 아무 장에서나 시작 — 반복의 모든 장 → rise 첫 장에 튐이 없어야 함."""
    problems = q.check("Starline")
    assert not [p for p in problems if "(아무 장)→rise" in p], problems


@pytest.mark.parametrize("folder", ["Starline", "다래"])
def test_mouth_composite_spill_is_caught(folder):
    """QA 11-28: 입 합성 장은 입 상자 밖이 몸 장과 같아야 함 — 지금 그림은 통과, 상자 밖에 얼룩을 넣으면 잡힘."""
    boxes = q.composite_boxes(folder)
    assert boxes
    assert not [p for p in q.check(folder) if p.startswith("입 합성 번짐")]
    name, (bx, by, bw, bh) = next(iter(boxes.items()))
    img = q.read(q.CHARS / folder / f"{name}.webp")
    y = max(0, by - 30)
    img[y:y + 12, bx:bx + 12, :3] = 255 - img[y:y + 12, bx:bx + 12, :3]
    base = q.read(q.CHARS / folder / "talk_base_0.webp")
    out = img.copy()
    out[by:by + bh, bx:bx + bw] = base[by:by + bh, bx:bx + bw]
    assert q.block_diff(out, base)[0] > q.BLOCK_LIMIT
