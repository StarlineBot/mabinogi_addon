"""보스 HP바 '프레임' 검출.

보스 HP바는 HP·보스가 달라도(색/채움 길이 변해도) **테두리(프레임) 사각형**은 폭·위치가
일정하다. 영역(가로로 넉넉한 밴드) 안에서 그 프레임의 bbox(x0,y0,x1,y1)를 찾는다.

원리: 프레임의 **상/하단 가로 테두리**는 '길고 곧은 가로 엣지'(위아래 밝기차 큼)라,
한 행에서 강한 가로엣지가 아주 길게(수백 px) 이어진다. 그런 행이 바 높이(≈20~70px)
간격으로 위/아래에 쌍으로 나타나는 곳이 바. 바닥 텍스처·일반 UI엔 이런 길고 곧은
가로 테두리 쌍이 없다. 색/채움과 무관해 저HP·멀티컬러 바도 잡힌다.
"""

from __future__ import annotations

import cv2
import numpy as np

_EDGE_MIN = 60  # 이 이상 세로 밝기기울기면 '강한 가로엣지'(테두리)
# 테두리로 인정할 최소 가로엣지 연속 길이: 보스 바는 화면 폭의 ~20%라, 영역(가로 밴드)
# 폭에 비례(12%)해 해상도·배율이 달라도 버틴다. 하한 180px로 노이즈는 거른다.
_RUN_RATIO = 0.12
_RUN_FLOOR = 180
_BAR_H_MIN = 16  # 상/하단 테두리 간격(바 높이) 최소
_BAR_H_MAX = 110  # 〃 최대 (배율↑ 대비 넉넉히)


def _run_min(width: int) -> int:
    return max(_RUN_FLOOR, int(width * _RUN_RATIO))


def _has_run(mask: np.ndarray, need: int) -> np.ndarray:
    """행별로 '길이 need 이상인 True 연속 구간'이 있는지(bool). cumsum 윈도우로 완전
    벡터화 — 폭(수천 px)만큼 파이썬 루프를 돌지 않아 빠르다.

    길이 need의 all-True 창이 하나라도 있으면, 그 창의 합이 정확히 need다.
    """
    if mask.shape[1] < need:
        return np.zeros(mask.shape[0], dtype=bool)
    cs = np.cumsum(mask.astype(np.int32), axis=1)
    cs = np.concatenate([np.zeros((mask.shape[0], 1), np.int32), cs], axis=1)
    win = cs[:, need:] - cs[:, :-need]  # 폭 need 창의 True 개수
    return (win >= need).any(axis=1)


def _longest_run_span(rowmask: np.ndarray) -> tuple[int, int]:
    """1D bool에서 가장 긴 True '연속' 구간의 (x0, x1_exclusive). 없으면 (0,0). 벡터화."""
    edges = np.flatnonzero(
        np.diff(np.concatenate(([0], rowmask.view(np.int8), [0])))
    )
    if edges.size == 0:
        return 0, 0
    starts, ends = edges[0::2], edges[1::2]
    k = int((ends - starts).argmax())
    return int(starts[k]), int(ends[k])


def locate_bar_frame(region: np.ndarray) -> tuple[int, int, int, int] | None:
    """영역에서 보스 HP바 프레임 bbox (x0, y0, x1, y1)를 찾는다. 없으면 None.

    좌표는 입력 region 기준(로컬). 보스 패턴/디버프가 이 bbox로 바를 정확히 집는다.
    """
    if region is None or region.shape[0] < _BAR_H_MIN + 2:
        return None
    need = _run_min(region.shape[1])
    if region.shape[1] < need:
        return None
    g = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    strong = gy > _EDGE_MIN
    border_rows = [int(r) for r in np.where(_has_run(strong, need))[0]]
    if len(border_rows) < 2:
        return None
    # 상·하단 테두리 쌍 탐색: 바 높이 간격이고, '같은 열에서 둘 다 테두리'인 열이
    # 가장 길게 이어지는 쌍이 보스 바(아이콘 줄·UI 패널 엣지는 위아래가 안 맞음).
    best = None  # (span_len, x0, x1, top, bot)
    for i, top in enumerate(border_rows):
        for bot in border_rows[i + 1:]:
            if not (_BAR_H_MIN <= bot - top <= _BAR_H_MAX):
                continue
            both = strong[top] & strong[bot]
            x0, x1 = _longest_run_span(both)
            if x1 - x0 > (best[0] if best else need - 1):
                best = (x1 - x0, x0, x1, top, bot)
    if best is None:
        return None
    _, x0, x1, top, bot = best
    return (x0, top, x1, bot)
