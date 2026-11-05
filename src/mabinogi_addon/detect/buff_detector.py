"""버프 디텍터 (기획서 2.1 / 4.2).

등록 아이콘들을 캡처 영역의 '아이콘 열'(x 고정, 세로 띠)에서 검색한다.
버프가 추가/제거되면 목록이 당겨져 y가 바뀌므로, 위치를 캐시하지 않고
매 프레임 세로 띠 전체를 다시 검색한다. x를 좁혀 성능을 확보한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .icon_matcher import DEFAULT_THRESHOLD, match_icon


def _gray(img: np.ndarray) -> np.ndarray:
    """BGR이면 그레이스케일로. 이미 1채널이면 그대로."""
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


@dataclass(frozen=True)
class Detection:
    buff_id: str
    score: float
    y: int  # 영역 기준 아이콘 상단 y (시간 판독 시 이 행을 쓴다)


# 4K(0.33.0 QA): 4K 화면의 버프 아이콘은 미세하게 흐려 실제 버프 점수가 0.83~0.87(2560·창·1080은 1.0)로 기준 0.8에 붙는다.
# 기준을 낮추면 비슷한 아이콘(마기그래프·마법 공격력 강화/증가 등 0.70~0.77)이 '있음'이 되므로 기준은 그대로 두고
#  ① 첫 검출 구제: 점수가 기준 바로 아래(RESCUE_MIN~기준)면 양쪽을 살짝 흐려 다시 비교해 RESCUE_BLUR 이상일 때만 인정
#    (tests/data: 4K 123333 행진곡 0.786→0.912 / 비슷한 아이콘 최고 0.771·0.758 → 원 점수에서 탈락)
#  ② 유지 이력: 직전 프레임에 있던 버프는 같은 줄(±HOLD_ROWS)에서 HOLD_THRESHOLD 이상이고 흐림 비교도 RESCUE_BLUR 이상이면 계속 '있음'
#    (점수가 0.8 근처에서 흔들려 '있음→3초 없음'이 반복 → 사라짐 경고가 계속 울리던 것. 디버프 0.68/0.58 이력과 같은 방식)
RESCUE_MIN = 0.78
RESCUE_BLUR = 0.9
HOLD_THRESHOLD = 0.75
HOLD_ROWS = 3
# 색 확인(제작자 11-05 요새화 추가 때): 회색 비교는 아이콘 테두리(주황·갈색)가 점수를 채워, 색이 전혀 다른 아이콘에도
# 0.80 안팎이 나왔다(요새화 ↔ '시간 분열: 낮' 0.803·'재생' 0.799). 확실하지 않은(회색 < COLOR_CHECK_BELOW) 검출만 색으로 한 번 더 —
# tests/data 실제 검출의 색 점수 최저 0.772(4K 흐림), 오인 0.594·0.666.
COLOR_CHECK_BELOW = 0.95
COLOR_MIN = 0.72


def _soft(img: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(img, (3, 3), 0.6)


def detect_buffs(
    region: np.ndarray,
    templates: dict[str, np.ndarray],
    icon_column: tuple[int, int],
    threshold: float = DEFAULT_THRESHOLD,
    held: dict[str, int] | None = None,
) -> list[Detection]:
    """영역 안에서 등록 아이콘들을 찾아 present인 것만 y 오름차순으로 반환.

    icon_column: 영역 기준 (x0, x1) — 아이콘이 있는 세로 띠. 이 폭 안에서만 검색.
    held: 직전 프레임에 있던 버프 {id: 아이콘 y} — 그 줄에서는 유지 이력 기준(HOLD_THRESHOLD)으로 본다.
    """
    x0, x1 = icon_column
    # 아이콘 '존재' 판정엔 색이 거의 불필요하고, 그레이스케일 매칭이 BGR 3채널보다
    # ~3배 빠르다(실측상 등록 아이콘은 그레이에서도 ~1.0, 오탐은 <임계로 분리). 매칭을
    # 가볍게 해 더 짧은 주기로 아이콘 생성/소멸을 빠르게 캐치하기 위함.
    strip = _gray(region[:, x0:x1])
    soft_strip = None

    detections: list[Detection] = []

    def color_ok(template, x, y) -> bool:
        if template.ndim != 3 or region.ndim != 3:
            return True
        t3 = template[:, :, :3]
        th, tw = t3.shape[:2]
        win = region[max(0, y - 1):y + th + 1, x0 + max(0, x - 1):x0 + x + tw + 1]
        if win.shape[0] < th or win.shape[1] < tw:
            return True
        return float(cv2.matchTemplate(np.ascontiguousarray(win), t3, cv2.TM_CCOEFF_NORMED).max()) >= COLOR_MIN

    for buff_id, template in templates.items():
        t = _gray(template)
        if t.shape[0] > strip.shape[0] or t.shape[1] > strip.shape[1]:
            continue
        scores = cv2.matchTemplate(strip, t, cv2.TM_CCOEFF_NORMED)
        _lo, score, _lo_at, at = cv2.minMaxLoc(scores)
        y = int(at[1])
        sure = score >= COLOR_CHECK_BELOW
        if score >= threshold and (sure or color_ok(template, at[0], y)):
            detections.append(Detection(buff_id, float(score), y))
            continue
        if threshold > score >= RESCUE_MIN:
            if soft_strip is None:
                soft_strip = _soft(strip)
            window = soft_strip[y:y + t.shape[0], at[0]:at[0] + t.shape[1]]
            if (window.shape == t.shape and match_icon(window, _soft(t)).score >= RESCUE_BLUR
                    and color_ok(template, at[0], y)):
                detections.append(Detection(buff_id, float(score), y))
                continue
        if held and buff_id in held:
            hy = held[buff_id]
            band = scores[max(0, hy - HOLD_ROWS):hy + HOLD_ROWS + 1]
            if band.size:
                _lo, kept, _lo_at, kept_at = cv2.minMaxLoc(band)
                ky, kx = max(0, hy - HOLD_ROWS) + int(kept_at[1]), int(kept_at[0])
                # 유지도 구제와 같은 흐림 확인(0.33.0 QA): 원 점수만 보면 마기그래프가 미등록 '재생'에 0.758로 붙어
                # 그 줄 시간을 마기그래프 시간으로 계속 읽었다(흐림 0.858~0.864, 진짜 4K 버프 0.912~0.949).
                if kept >= HOLD_THRESHOLD:
                    if soft_strip is None:
                        soft_strip = _soft(strip)
                    window = soft_strip[ky:ky + t.shape[0], kx:kx + t.shape[1]]
                    if (window.shape == t.shape and match_icon(window, _soft(t)).score >= RESCUE_BLUR
                            and (kept >= COLOR_CHECK_BELOW or color_ok(template, kx, ky))):
                        detections.append(Detection(buff_id, float(kept), ky))

    detections = _one_per_row(detections, templates)
    detections.sort(key=lambda d: d.y)
    return detections


SAME_ICON = 0.95  # 두 버프 아이콘끼리 이 이상 닮으면 '같은 그림' — 한 줄에 함께 둔다(사용자가 같은 그림으로 두 버프를 등록한 경우)


def _one_per_row(detections: list[Detection], templates: dict[str, np.ndarray]) -> list[Detection]:
    """게임 목록 한 줄(같은 y ± 아이콘 높이 반)에는 버프가 하나뿐 — 점수가 가장 높은 것만 남긴다.

    예전엔 한 줄에 여러 버프가 함께 잡혔다(제작자 11-05: 요새화 줄을 비바체로 오인해 요새화 시간을 비바체로 읽음,
    y=652 공격력 증가·급소 관통 함께). 같은 그림을 쓰는 버프끼리는 어느 쪽인지 알 수 없으니 함께 둔다."""
    kept: list[Detection] = []
    for det in sorted(detections, key=lambda d: -d.score):
        half = max(1, _gray(templates[det.buff_id]).shape[0] // 2)
        rivals = [k for k in kept if abs(k.y - det.y) <= half]
        if all(_same_icon(templates[det.buff_id], templates[k.buff_id]) for k in rivals):
            kept.append(det)
    return kept


def _same_icon(a: np.ndarray, b: np.ndarray) -> bool:
    a, b = _gray(a), _gray(b)
    if a.shape != b.shape:
        return False
    return float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED).max()) >= SAME_ICON
