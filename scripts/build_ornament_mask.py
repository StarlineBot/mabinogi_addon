"""개발용: 투아림·도르카 원형 장식의 '금속 픽셀만' 마스크를 만든다(0.30.2).

예전 마스크(tuarim_mask.png 왼쪽 45열)는 장식 둘레를 고리로 통째로 잡아 잎사귀 사이의 게임 배경까지
비교했다 → 파란 배경(image55·213520)에서 제자리 점수 0.95대로 기준 0.97 미달. 단축바 마스크 수정(5376862)과 같은 방식으로,
배경이 서로 다른 실제 화면 10장에서 장식을 정렬해 겹쳤을 때 **값이 거의 변하지 않는 픽셀**(최대-최소 < 40)만 남긴다.
가운데 숫자는 예전처럼 제외(예전 마스크와 교집합).

    uv run python scripts/build_ornament_mask.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mabinogi_addon import image_io  # noqa: E402

# 파일 → 투아림 % 상자 왼쪽 위(장식 = 상자 - (34, 45))
FRAMES = {
    "image55.png": (1368, 84), "mabinogi_2026_10_30_213520.png": (1368, 84),
    "mabinogi_2026_10_30_213927.png": (1368, 84), "mabinogi_2026_10_30_213942.png": (1368, 84),
    "mabinogi_2026_10_30_214016.png": (1368, 84), "mabinogi_2026_10_30_214051.png": (1368, 84),
    "mabinogi_2026_10_30_214648.png": (1368, 84), "2026-10-30_windowed_wireweb_1.png": (1384, 116),
    "2026-10-30_windowed_wireweb_2.png": (1384, 116), "2026-10-30_windowed_wireweb_3.png": (1384, 116),
}
STABLE = 40


def main() -> None:
    folder = ROOT / "src/mabinogi_addon/detect/templates/autofind"
    anchor = cv2.cvtColor(image_io.imread(folder / "tuarim_anchor.png")[:, :45], cv2.COLOR_BGR2GRAY)
    ring = image_io.imread(folder / "tuarim_mask.png", cv2.IMREAD_GRAYSCALE)[:, :45]
    h, w = anchor.shape
    crops = []
    for name, (bx, by) in FRAMES.items():
        gray = cv2.cvtColor(image_io.imread(ROOT / "tests/data" / name), cv2.COLOR_BGR2GRAY)
        x0, y0 = bx - 34 - 6, by - 45 - 6
        window = gray[y0:y0 + h + 12, x0:x0 + w + 12]
        scores = cv2.matchTemplate(window, anchor, cv2.TM_CCORR_NORMED, mask=ring)
        _, _, _, (dx, dy) = cv2.minMaxLoc(scores)
        crops.append(gray[y0 + dy:y0 + dy + h, x0 + dx:x0 + dx + w].astype(np.int16))
    stack = np.stack(crops)
    stable = (stack.max(axis=0) - stack.min(axis=0)) < STABLE
    mask = np.where((ring > 0) & stable, 255, 0).astype(np.uint8)
    image_io.imwrite(folder / "ornament_mask.png", mask)
    print("ornament_mask.png", int((mask > 0).sum()), "px (예전", int((ring > 0).sum()), ")")


if __name__ == "__main__":
    main()
