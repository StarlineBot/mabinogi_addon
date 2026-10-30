"""개발용: 4K 투아림 % 작은 글자(9px) 세트를 만든다(0.30.2).

기본 작은 글자 세트(small_refs.npz)는 8px. 4K 화면에서는 같은 글자가 9px로 그려져(시간 글자와 같은 현상)
'%' 정렬부터 실패하고 예전 판독으로 넘어가 9%·44%·8%·13%를 못 읽었다(None).
값을 아는 4K 화면에서 read_small과 같은 방식(흰 잉크 → '%' 왼쪽 열 묶음)으로 글자를 떠서
small_uhd_refs.npz(refs (N,9,7) 0/1, labels, percent (K,9,10) 변형)에 저장한다. 자료에 없는 숫자(5·6·7)는 못 읽고 None.

    uv run python scripts/build_tuarim_uhd_refs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mabinogi_addon import image_io  # noqa: E402

# 파일 → (투아림 % 상자 x, y, 화면 값)
SAMPLES = {
    "image55.png": (1368, 83, 9), "mabinogi_2026_10_30_213520.png": (1368, 84, 44),
    "mabinogi_2026_10_30_213927.png": (1368, 84, 0), "mabinogi_2026_10_30_213942.png": (1368, 84, 3),
    "mabinogi_2026_10_30_214016.png": (1368, 84, 8), "mabinogi_2026_10_30_214051.png": (1368, 84, 13),
    "mabinogi_2026_10_30_214648.png": (1368, 84, 24),
}
GH, GW, PW = 9, 7, 10  # 4K 글자는 9px 높이, 굵은 4는 7px 폭, %는 10px 폭


def ink_of(region):
    return ((region.min(axis=2) >= 180) & (np.ptp(region, axis=2) <= 35)).astype(np.uint8)


def groups_of(strip):
    """빈 열로 나눈 묶음. 잉크 3px 미만 묶음은 잡티(밝은 점)라 버린다."""
    columns = np.flatnonzero(strip.any(axis=0))
    groups = np.split(columns, np.flatnonzero(np.diff(columns) > 1) + 1)
    return [g for g in groups if len(g) and int(strip[:, g[0]:g[-1] + 1].sum()) >= 3]


def main() -> None:
    refs, labels, percents = [], [], []
    for name, (x, y, value) in SAMPLES.items():
        frame = image_io.imread(ROOT / "tests/data" / name)
        ink = ink_of(frame[y:y + 16, x:x + 42])
        rows = np.flatnonzero(ink.sum(axis=1) >= 2)  # 글자 행(외딴 밝은 점 제외)
        top = int(rows[0])
        strip = ink[top:top + GH]
        groups = groups_of(strip)
        # 오른쪽 끝 '%'는 여러 묶음(사선+동그라미)이라 폭으로 자른다(4K는 10px)
        right = int(groups[-1][-1]) + 1
        percent = strip[:, right - PW:right]
        percents.append(percent)
        digits = [g for g in groups if int(g[-1]) < right - PW]
        text = str(value)
        if len(digits) != len(text):
            raise SystemExit(f"{name}: 글자 {len(text)}개인데 묶음 {len(digits)}개")
        for group, ch in zip(digits, text):
            glyph = np.zeros((GH, GW), np.uint8)
            left, end = int(group[0]), int(group[-1]) + 1
            glyph[:, :end - left] = strip[:, left:end]
            if not any(np.array_equal(glyph, r) and int(ch) == l for r, l in zip(refs, labels)):
                refs.append(glyph)
                labels.append(int(ch))
    # '%'도 장마다 모양이 조금 달라(214051은 하나로는 0.928 < 0.93) 서로 다른 모양을 모두 변형으로
    variants = []
    for p in percents:
        if not any(np.array_equal(p, q) for q in variants):
            variants.append(p)
    target = ROOT / "src/mabinogi_addon/detect/templates/tuarim/small_uhd_refs.npz"
    np.savez_compressed(target, refs=np.stack(refs), labels=np.array(labels), percent=np.stack(variants))
    print(target.name, len(refs), "글자", sorted(set(labels)))


if __name__ == "__main__":
    main()
