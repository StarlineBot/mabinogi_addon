"""보스 디버프 줄 아이콘 아래 시간 글자 읽기 — 디버프 오버레이 '걸린 것 + 시간' 보기(docs/debuff-applied-overlay-spec.md 2절).

게임 표시: 1분 이상 `NM`(1~9M), 1분 미만 `NN`/`N`(초), 시간 없는 디버프는 글자 없음. 작은 픽셀 글꼴(높이 7px, 숫자 5px·M 7px 폭)이라
흰 글자 마스크의 글자 덩어리를 글자(0~9·M, 7px·9px 두 크기) 템플릿과 비교한 뒤, 글자 왼쪽 끝이 어느 아이콘 칸에 드는지로 나눈다
(`4M4M3M`처럼 붙어 있어도 칸으로 나뉨). 템플릿은 tests/data 보스 화면 디버프 줄에서 뽑았다(assets/debuff_time_glyphs).

틀린 숫자를 보이지 않는다: 칸 안 흰 픽셀을 맞춘 글자로 거의 다 설명하지 못하면(밝은 바닥·이펙트) 그 칸은 None.
비용: 띠 하나(높이 12px)의 글자 덩어리를 같은 크기 템플릿과 픽셀 비교 — 1ms 미만.
"""

from __future__ import annotations

import re

import cv2
import numpy as np

from .. import paths
from ..image_io import imread

_GLYPH_DIR = paths.resource_dir() / "debuff_time_glyphs"
_TOP, _BAND = 1, 12  # 아이콘 아래 1px부터 12px 띠(글자 7px — 위아래 어긋남 여유)
_UNEXPLAINED = 3  # 칸 안 흰 픽셀 중 글자로 설명 못 하는 것이 이보다 많으면 못 읽음(밝은 바닥·이펙트)
_LEFT = 2  # 글자는 아이콘 왼쪽 끝 조금 앞에서 시작할 수 있다
_VALID = re.compile(r"^(?:[1-9]M|\d{1,2})$")


def _load() -> list[tuple[str, np.ndarray]]:
    """(글자, 0/1 그림) — 파일 이름 '{글자}_{크기}{번호}.png': s = 7px 글꼴, t = 9px 글꼴(같은 2560에서도 두 크기가 보임 — 10-09·11-03·11-09 4K 화면)."""
    out = []
    if _GLYPH_DIR.exists():
        for p in sorted(_GLYPH_DIR.glob("*.png")):
            img = imread(p, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                out.append((p.stem.split("_")[0], (img > 127).astype(np.float32)))
    return out


_GLYPHS = _load()


_KERNEL = np.ones((3, 3), np.uint8)
_EDGE = 60  # 글자 테두리: 3×3 안 가장 어두운 픽셀보다 이만큼 밝아야 글자


def text_mask(bgr: np.ndarray) -> np.ndarray:
    """흰 글자 = 밝고 채도 낮으면서 바로 옆(3×3)에 그보다 확 어두운(테두리) 픽셀이 있는 것. 글자 획은 1px이라 모든 글자 픽셀이 테두리에 닿고,
    밝은 바닥(돌·눈)은 고르게 밝아 빠진다(바닥이 밝은 화면에서 글자가 바닥과 붙어 못 읽던 것)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    bright = (v >= 170) & (hsv[..., 1] <= 90)
    edge = v.astype(np.int16) - cv2.erode(v, _KERNEL).astype(np.int16) >= _EDGE
    return (bright & edge).astype(np.float32)


_BY_SHAPE: dict[tuple[int, int], tuple[list[str], list[int], np.ndarray]] = {}
for _gi, (_ch, _t) in enumerate(_GLYPHS):
    _chars, _ids, _stack = _BY_SHAPE.get(_t.shape, ([], [], np.zeros((0, *_t.shape), bool)))
    _BY_SHAPE[_t.shape] = (_chars + [_ch], _ids + [_gi], np.concatenate((_stack, (_t > 0)[None])))
_MISS = 2  # 글자 하나에서 템플릿과 다른 픽셀을 이만큼까지 허용(번짐)


def _match(bitmap: np.ndarray) -> int | None:
    """같은 크기 템플릿 중 다른 픽셀이 가장 적은 것(_MISS 이하) — 템플릿 번호 또는 None."""
    group = _BY_SHAPE.get(bitmap.shape)
    if group is None:
        return None
    diff = (group[2] != bitmap[None]).sum(axis=(1, 2))
    k = int(diff.argmin())
    return group[1][k] if diff[k] <= _MISS else None


def _split(bitmap: np.ndarray) -> list[tuple[int, int]] | None:
    """붙은 글자 덩어리를 왼쪽부터 템플릿 폭만큼 떼어 — [(x, 템플릿 번호)] 또는 None(못 나눔)."""
    out, x, h, w = [], 0, bitmap.shape[0], bitmap.shape[1]
    while x < w:
        if not bitmap[:, x].any():
            x += 1
            continue
        for tw in sorted({s[1] for s in _BY_SHAPE if s[0] == h}, reverse=True):
            if x + tw <= w:
                gi = _match(bitmap[:, x:x + tw])
                if gi is not None:
                    out.append((x, gi))
                    x += tw
                    break
        else:
            return None
    return out


def _glyphs_in(mask: np.ndarray) -> list[tuple[int, int, str, int]]:
    """띠 안 글자들 (x, y, 글자, 템플릿 번호). 작은 픽셀 글꼴이라 덩어리(8방향 연결)를 같은 크기 템플릿과 픽셀 단위로 비교한다
    (매 칸 템플릿 맞춤보다 빠름 — 1ms 미만 목표). 붙은 글자는 왼쪽부터 템플릿 폭만큼 나눈다."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, _a = st[i]
        if h < 5:
            continue
        bitmap = lab[y:y + h, x:x + w] == i
        gi = _match(bitmap)
        parts = [(0, gi)] if gi is not None else (_split(bitmap) if w > 7 else None)
        for dx, g in parts or ():
            out.append((int(x + dx), int(y), _GLYPHS[g][0], g))
    return sorted(out)


def read_times(region: np.ndarray, boxes: dict) -> dict[str, str | None]:
    """디버프 영역(BGR)과 아이콘 자리 {id: (x, y, w, h)} → {id: 게임 시간 글자('4M', '43', '0') 또는 None}.
    시간 없는 디버프·못 읽음(밝은 바닥·이펙트·모양이 안 맞음)은 None."""
    out: dict[str, str | None] = {bid: None for bid in boxes}
    boxes = {bid: b for bid, b in boxes.items() if b is not None}
    if region is None or region.size == 0 or not boxes or not _GLYPHS:
        return out
    # 아이콘 줄은 한 줄 — 띠는 아이콘 아래쪽 기준
    bottom = int(np.median([y + h for _x, y, _w, h in boxes.values()]))
    top = bottom + _TOP
    right = max(x + w for x, _y, w, _h in boxes.values()) + 2 * _LEFT
    band = region[top:top + _BAND, :right]  # 아이콘이 있는 데까지만(비용)
    if band.shape[0] < 7:
        return out
    mask = text_mask(band)
    glyphs = _glyphs_in(mask)
    explained = np.zeros_like(mask, dtype=bool)
    for x, y, _ch, gi in glyphs:
        t = _GLYPHS[gi][1]
        explained[y:y + t.shape[0], x:x + t.shape[1]] |= t > 0
    for bid, (x, _y, w, _h) in boxes.items():
        x0, x1 = max(0, x - _LEFT), x + w
        cell = [g for g in glyphs if x0 <= g[0] < x1]
        # 칸(다음 아이콘 칸 앞까지) 안 흰 픽셀이 글자로 설명되는지
        span = slice(x0, min(mask.shape[1], x + w + _LEFT))
        loose = int(((mask[:, span] > 0) & ~explained[:, span]).sum())
        if loose > _UNEXPLAINED:
            continue  # 밝은 바닥·이펙트 — 비움(틀린 숫자 금지)
        text = "".join(g[2] for g in cell)
        if text and _VALID.match(text) and (len(cell) < 2 or abs(cell[0][1] - cell[-1][1]) <= 1):
            out[bid] = text
    return out


def display_text(game: str | None) -> tuple[str, bool] | None:
    """게임 시간 글자 → (표시 글자, 1분 미만 빨강). 'NM' → 'Nm', 초 → 'Ns'(버프 오버레이 duration.format_duration과 같은 단위)."""
    if not game:
        return None
    if game.endswith("M"):
        return f"{int(game[:-1])}m", False
    return f"{int(game)}s", True
