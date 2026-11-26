"""펫이 걸어 다닐 바닥 — 보이는 게임 화면을 피함(QA 11-26, 사용자 결정 ①안). OS와 무관한 순수 계산.

진짜 창모드에서 게임이 포그라운드가 아니어도(디스코드·브라우저에 포커스) 게임 창이 화면에 보이면, 그 창이 바닥 띠와
겹치는 x 구간을 '막힌 구간'으로 두고 펫은 그 밖의 빈 바닥에서만 돌아다닌다. 보이는 사각형은 system/game_visibility가
(다른 창에 가려진 부분을 빼고) 구해 논리 px로 넘긴다.
"""
from __future__ import annotations

PET_WIDTH = 300.0   # 펫 창 폭(논리 px) — 빈 구간이 이보다 좁으면 설 자리 없음(clamp_x half 150과 같은 기준)

Span = tuple[float, float]
Rect = tuple[float, float, float, float]   # (left, top, right, bottom)


def merge(spans) -> list[Span]:
    """겹치거나 맞닿은 x 구간 합치기(정렬)."""
    out: list[list[float]] = []
    for lo, hi in sorted((float(a), float(b)) for a, b in spans if b > a):
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [(lo, hi) for lo, hi in out]


def blocked_spans(rects, floor, figure_h: float) -> list[Span]:
    """보이는 게임 사각형들 → 바닥 띠(바닥 y − 펫 키 ~ 바닥 y)와 겹치는 x 구간(바닥 좌우 안으로 자름)."""
    band_top, band_bottom = floor.y - figure_h, floor.y
    spans = []
    for left, top, right, bottom in rects:
        if bottom <= band_top or top >= band_bottom or right <= left or bottom <= top:
            continue
        lo, hi = max(floor.left, left), min(floor.right, right)
        if hi > lo:
            spans.append((lo, hi))
    return merge(spans)


def free_spans(floor, blocked, width: float = PET_WIDTH) -> list[Span]:
    """막힌 구간 밖 빈 바닥(폭 width 이상만)."""
    out, x = [], floor.left
    for lo, hi in merge(blocked):
        if lo - x >= width:
            out.append((x, lo))
        x = max(x, hi)
    if floor.right - x >= width:
        out.append((x, floor.right))
    return out


def to_logical(rects, scale: float) -> list[Rect]:
    """Win32 물리 px 사각형 → Qt 논리 px(주 화면 배율)."""
    s = scale if scale and scale > 0 else 1.0
    return [(l / s, t / s, r / s, b / s) for l, t, r, b in rects]
