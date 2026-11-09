"""보스 HP 글자 분류(_classify) 빠른 계산 = 예전 계산(템플릿마다 resize·threshold·matchTemplate) — CPU 과제(사용자 app.log 11-09).

같은 크기 템플릿을 묶어 상관계수를 한 번에 내고, 같은 글자 모양은 다시 계산하지 않는다. 결과(숫자·점수)는 예전과 같아야 한다.
"""
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect import boss_hp_reader as R

ROOT = Path(__file__).resolve().parents[1]


def _reference(glyph, templates):
    best, best_score = None, -2.0
    for d, samples in templates.items():
        for t in samples:
            g = cv2.resize(glyph, (t.shape[1], t.shape[0]), interpolation=cv2.INTER_NEAREST)
            _, g = cv2.threshold(g, 127, 255, cv2.THRESH_BINARY)
            score = float(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED).max())
            if score > best_score:
                best, best_score = d, score
    return best, best_score


def _glyphs():
    """수집 프레임의 숫자 칸에서 잘라 낸 글자 모양(기본 마스크·밝은 마스크) + 한 색 글자."""
    out = [np.full((12, 8), 255, np.uint8), np.zeros((10, 7), np.uint8)]
    z = zipfile.ZipFile(ROOT / "tests/data/unknown_hpxxx_047.zip")
    for name in [n for n in z.namelist() if n.endswith(".png")][:40]:
        img = cv2.imdecode(np.frombuffer(z.read(name), np.uint8), cv2.IMREAD_COLOR)
        pct = img[45:img.shape[0] - 6]
        pct = pct[:, int(pct.shape[1] * .58):]
        h = pct.shape[0]
        for mask in (R._color_mask(pct), R._bright_mask(pct)):
            band = mask[int(h * R._YBAND[0]):int(h * R._YBAND[1])]
            n, lab, st, _ = cv2.connectedComponentsWithStats((band > 127).astype(np.uint8))
            for i in range(1, n):
                x, y, w, hh, a = st[i]
                if a >= R._MIN_PX and 3 <= hh and w <= 20:
                    out.append(band[y:y + hh, x:x + w].copy())
    return out


@pytest.mark.parametrize("which", ["digits", "bright", "gray"])
def test_fast_classify_equals_reference(which):
    templates = {"digits": R._DIGITS, "bright": R._BRIGHT_SAMPLES,
                 "gray": getattr(R, "_GRAY_SAMPLES", None) or R._DIGITS}[which]
    glyphs = _glyphs()
    assert len(glyphs) > 100
    R._SEEN.clear()
    for g in glyphs:
        want = _reference(g, templates)
        got = R._classify(g, templates)
        assert got[0] == want[0] and got[1] == pytest.approx(want[1], abs=1e-5)
        assert R._classify(g, templates) == got  # 같은 모양 다시(캐시) = 같은 결과


def test_cache_is_per_template_set():
    """다른 템플릿 묶음의 결과가 섞이지 않는다(임시 묶음의 id가 재사용돼도)."""
    glyph = _glyphs()[5]
    only = {"7": R._DIGITS["7"]}
    assert R._classify(glyph, only)[0] == "7"
    assert R._classify(glyph, R._DIGITS) == _reference(glyph, R._DIGITS)[:1] + (R._classify(glyph, R._DIGITS)[1],)
