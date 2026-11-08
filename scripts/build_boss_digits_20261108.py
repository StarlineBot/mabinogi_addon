"""저HP 회색 바탕 위 흰 숫자 샘플(gray_d*_*.png)을 tests/data 보스 수집에서 뽑는다(사용자 11-08, QA dee7b93).

채움이 숫자 칸 왼쪽에서 끝나면 숫자가 회색 빈 바 위 흰 글자라 채도 마스크로 소수를 못 읽는다 → 밝기 마스크(흰 글자만)로 읽을 샘플.
이름 붙이기: 기본 경로(채도 마스크)가 정수·소수를 모두 읽은 프레임(앱 입력 = 오른쪽 42%)에서, 같은 프레임의 밝기 마스크 숫자 칸
글자 덩어리(왼쪽부터, '.'·'%' 앞)를 그 값의 글자로 이름 붙인다. 흰 글자 모양은 바탕색과 무관하게 같아 높은 HP 프레임으로 충분하다.
더해서 저HP(20% 이하) 프레임의 정수 자리 — 앱이 지금 읽는 정수 값으로, '.'(키 작은 덩어리) 왼쪽 글자 수가 정수 자리 수와 같을 때만
(2560 두 줄 수집의 '2'처럼 높은 HP 프레임에 없던 회색 바탕 글자 모양).
고르기: 모은 글자를 차례로 분류해 틀리거나 약한(0.85 미만) 것만 샘플로 추가(세 번 반복, 숫자당 최대 8개). 실행: uv run python -m scripts.build_boss_digits_20261108
"""
import glob
import random
import zipfile
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io, paths
from mabinogi_addon.detect import boss_hp_reader as hp

ROOT = Path(__file__).resolve().parents[1]
ZIPS = ("eotgallin_poinche_hp004_115.zip", "eotgallin_poinche_hp098_058.zip", "gomok_petak_hp019_158.zip",
        "unknown_hpxxx_show001_upper_197.zip")
SIMILAR = 0.85
CAP = 8


def _crops(item):
    kind, a, b = item
    if kind == "zip":
        with zipfile.ZipFile(ROOT / "tests/data" / a) as z:
            im = cv2.imdecode(np.frombuffer(z.read(b), np.uint8), cv2.IMREAD_COLOR)
        return [im] if im.shape[0] < 60 else [im[45:82], im[6:43]]  # 두 줄 수집은 아래·위 줄
    from mabinogi_addon.detect.boss_bar import locate_boss_bar, make_validator
    f = image_io.imread(ROOT / a, cv2.IMREAD_COLOR)
    if f is None or f.shape[1] < 1200:
        return []
    box = locate_boss_bar(f, make_validator())
    if box is None:
        return []
    x, y, w, h = box
    return [f[y:y + h, x:x + w]]


def _parts(crop, with_dot=False):
    """밝기 마스크 숫자 칸의 키 큰 글자 덩어리(왼쪽부터). with_dot: '.'(키 작은 덩어리) 왼쪽 것만."""
    h, w = crop.shape[:2]
    scale = min(h, hp._UI_H) / hp._REF_H
    m = hp._bright_mask(crop)[int(h * hp._YBAND[0]):int(h * hp._YBAND[1]), hp._num_left(w, scale):]
    n, _lab, st, _ = cv2.connectedComponentsWithStats((m > 127).astype(np.uint8), connectivity=8)
    if n <= 1:
        return [], scale
    tall = int(st[1:, cv2.CC_STAT_HEIGHT].max())
    comps = sorted((st[i] for i in range(1, n) if st[i][3] * 2 >= tall and st[i][4] >= 8), key=lambda s: s[0])
    if with_dot:
        dots = [st[i] for i in range(1, n) if st[i][4] >= 2 and st[i][3] * 3 <= tall and st[i][1] + st[i][3] >= tall * 0.7]
        if len(dots) != 1:
            return [], scale
        comps = [c for c in comps if c[0] + c[2] <= dots[0][0]]
    return [(m[y:y + ch, x:x + cw] > 127).astype(np.uint8) * 255 for x, y, cw, ch, _a in comps], scale


def _labelled(item):
    hp._GRAY_SAMPLES = {}  # 이전 결과에 기대지 않게 — 기본 경로 판독만으로 이름 붙인다
    out = []
    for c in _crops(item):
        crop = c[:, int(c.shape[1] * 0.58):]  # 앱 입력(등록 보스: 오른쪽 42%)
        v, fr = hp.read_percent_frac(crop)
        if v is not None and fr is None and v <= hp._LOW_HP_MAX:  # 저HP 정수 자리
            parts, scale = _parts(crop, with_dot=True)
            if len(parts) == len(str(v)) and all(p.shape[1] <= hp._PITCH * scale * 0.95 for p in parts):
                out += list(zip(str(v), parts))
            continue
        if v is None or fr is None:
            continue
        parts, scale = _parts(crop)
        text = f"{v}{fr}"
        if len(parts) < len(text) + 1 or any(p.shape[1] > hp._PITCH * scale * 0.95 for p in parts[:len(text)]):
            continue  # '%'가 없거나 글자가 붙음
        out += list(zip(text, parts[:len(text)]))
    return out


def collect():
    items = []
    for zn in ZIPS:
        with zipfile.ZipFile(ROOT / "tests/data" / zn) as z:
            items += [("zip", zn, n) for n in sorted(z.namelist()) if n.endswith(".png")]
    items += [("shot", str(Path(p).relative_to(ROOT)), "") for p in sorted(glob.glob(str(ROOT / "tests/data/*.png")))]
    with Pool() as pool:
        return [g for gs in pool.map(_labelled, items, chunksize=8) for g in gs]


def choose(glyphs):
    glyphs = list(glyphs)
    random.Random(0).shuffle(glyphs)
    chosen: dict[str, list[np.ndarray]] = {}
    for _ in range(3):
        for d, g in glyphs:
            got, score = hp._classify(g, chosen) if chosen else (None, -1.0)
            if (got != d or score < SIMILAR) and len(chosen.get(d, [])) < CAP:
                chosen.setdefault(d, []).append(g)
    return chosen


def build() -> None:
    folder = paths.resource_dir() / "boss_hp_digits"
    for old in folder.glob("gray_d*_*.png"):
        old.unlink()
    glyphs = collect()
    chosen = choose(glyphs)
    for d, samples in sorted(chosen.items()):
        for i, g in enumerate(samples):
            image_io.imwrite(folder / f"gray_d{d}_{i}.png", g)
    print(f"글자 {len(glyphs)}개 → 샘플", {d: len(v) for d, v in sorted(chosen.items())})


if __name__ == "__main__":
    build()
