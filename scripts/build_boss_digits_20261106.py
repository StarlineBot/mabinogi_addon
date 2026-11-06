"""고목의 페타크 두 줄 구간(2026-11-06 스크린샷)에서 보스 HP 숫자 샘플을 뽑는다(QA d52528a).

노란 바탕 '55.00 %'의 5, 보라 바탕 '100.00 %'의 1·0이 기존 샘플과 모양이 조금 달라(최고 점수 0.61·0.76) 못 읽거나 10으로 읽었다.
화면 값을 알고 있는 칸만 쓴다: 저장은 기존 샘플과 같은 방식(채도 마스크 숫자 띠에서 글자 하나를 잘라 둘레를 다듬은 이진 그림).
"""
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io, paths
from mabinogi_addon.detect import boss_hp_reader as hp

ROOT = Path(__file__).resolve().parents[1]
# (스크린샷, 바 y, 화면 값의 정수부) — x 1018, 폭 521, 높이 37(locate_boss_bar 박스)
SOURCES = (("스크린샷 2026-11-06 233618.png", 1214, "55"),
           ("스크린샷 2026-11-06 233616.png", 1182, "55"),
           ("스크린샷 2026-11-06 233838.png", 1252, "100"))


def glyphs(crop: np.ndarray) -> list[np.ndarray]:
    """숫자 띠의 글자 덩어리(왼쪽부터). 오른쪽 40% 칸만(이름 글자 제외)."""
    h, w = crop.shape[:2]
    band = hp._color_mask(crop)[int(h * hp._YBAND[0]):int(h * hp._YBAND[1]), int(w * 0.6):]
    n, labels, stats, _ = cv2.connectedComponentsWithStats((band > 127).astype(np.uint8), connectivity=8)
    comps = sorted((stats[i] for i in range(1, n) if stats[i][4] >= 20 and stats[i][3] >= band.shape[0] // 2),
                   key=lambda s: s[0])  # '.'·작은 조각 제외(숫자 높이의 절반 이상만)
    out = []
    for x, y, cw, ch, _a in comps:
        k = max(1, round(cw / 10.5))  # 붙은 글자(예: '00' 폭 20)는 같은 폭으로 나눈다(숫자 한 칸 약 9~11px)
        for j in range(k):
            x0, x1 = x + round(cw * j / k), x + round(cw * (j + 1) / k)
            out.append((band[:, x0:x1] > 127).astype(np.uint8) * 255)
    return out


def trim(binary: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(binary)
    return binary[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def build() -> None:
    folder = paths.resource_dir() / "boss_hp_digits"
    added = {}
    for name, y, integer in SOURCES:
        frame = image_io.imread(ROOT / "tests/data" / name, cv2.IMREAD_COLOR)
        parts = glyphs(frame[y:y + 37, 1018:1539])
        for digit, part in zip(integer, parts):  # 정수부 글자만(왼쪽부터)
            sample = trim(part)
            i = 0
            while (folder / f"d{digit}_{i}.png").exists():
                i += 1
            if any(np.array_equal(sample, s) for s in added.get(digit, [])):
                continue
            added.setdefault(digit, []).append(sample)
            image_io.imwrite(folder / f"d{digit}_{i}.png", sample)
            print(name, digit, f"d{digit}_{i}.png", sample.shape)


if __name__ == "__main__":
    build()
