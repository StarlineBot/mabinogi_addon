"""디버프 트래커 엔진 (기획서 3.2).

보스 디버프 줄 영역에서 등록 디버프 아이콘을 2D 검색해, **아직 안 걸린(미감지)**
디버프만 등록 순서로 돌려준다. 버프와 반대 로직이다:
- 걸림(감지) → 즉시 숨김(오버레이에서 뺀다).
- 안 걸림(미감지) → 다시 표시는 reappear_sec 연속 미감지일 때만(깜빡임 방지).

지속시간·알림·앵커 없음. 보스가 없으면 전부 미감지 = 전부 표시(의미상 맞음).
결과는 BuffEngine과 같은 TickResult 형태라 BuffController가 그대로 쓸 수 있다.
"""

from __future__ import annotations

import cv2
import numpy as np

from ..detect import match_icon
from .engine import OverlayEntry, TickResult

# 보스 디버프 줄 아이콘의 실제 화면 높이(px). 2560x1440 기준 실측 ≈16.
_ONSCREEN_ICON_PX = 16
# 매칭은 이 높이로 축소해서 한다: 비용↓(영역을 크게 잡아도 됨) + 숫자 겹침 노이즈 완화.
# 너무 작으면(8px) 아이콘이 뭉개져 서로 점수가 겹치므로 10px로.
_MATCH_ICON_PX = 10
# 영역과 템플릿을 같은 비율로 축소 → 화면 아이콘이 _MATCH_ICON_PX가 되게.
_DOWNSCALE = _MATCH_ICON_PX / _ONSCREEN_ICON_PX  # 0.625
# 이력 임계(hysteresis): 실데이터에서 걸린 것 ≥0.70 / 안 걸린 것 ≤0.61.
# 감지 시작은 높게(0.68), 해제는 낮게(0.58) 잡아 경계 점수의 프레임별 요동을 없앤다.
DEBUFF_DETECT_THRESHOLD = 0.68
DEBUFF_RELEASE_THRESHOLD = 0.58
DEBUFF_THRESHOLD = DEBUFF_DETECT_THRESHOLD  # 진단 스크립트 표시용


def _variant(template: np.ndarray, target_h: int) -> np.ndarray:
    h, w = template.shape[:2]
    tw = max(4, round(w * target_h / h))
    return cv2.resize(template, (tw, target_h), interpolation=cv2.INTER_AREA)


class DebuffEngine:
    def __init__(
        self,
        templates: dict[str, np.ndarray],
        order: list[str],
        *,
        detect_threshold: float = DEBUFF_DETECT_THRESHOLD,
        release_threshold: float = DEBUFF_RELEASE_THRESHOLD,
        reappear_sec: float = 1.0,
    ) -> None:
        self._templates = templates
        self._order = list(order)
        self._detect_thr = detect_threshold
        self._release_thr = release_threshold
        self._reappear = reappear_sec
        # 템플릿을 매칭 크기(축소 후 화면 아이콘 크기)로 미리 맞춘다.
        self._variants = {
            bid: [_variant(t, _MATCH_ICON_PX)] for bid, t in templates.items()
        }
        # shown=True면 '안 걸림' → 오버레이 표시. 초기엔 전부 표시(보스 전 상태).
        self._shown = {bid: True for bid in templates}
        self._matched = {bid: False for bid in templates}  # 이력 임계용 직전 판정
        self._absent_since: dict[str, float | None] = {bid: None for bid in templates}

    def set_order(self, order: list[str]) -> None:
        self._order = list(order)

    @staticmethod
    def _scale(region: np.ndarray) -> np.ndarray:
        """영역을 _DOWNSCALE로 축소 — 화면 아이콘이 _MATCH_ICON_PX가 되도록."""
        if region.shape[0] == 0 or region.shape[1] == 0:
            return region
        return cv2.resize(
            region,
            (
                max(1, round(region.shape[1] * _DOWNSCALE)),
                max(1, round(region.shape[0] * _DOWNSCALE)),
            ),
            interpolation=cv2.INTER_AREA,
        )

    def best_scores(self, region: np.ndarray) -> dict[str, float]:
        """각 디버프의 최고 매칭 점수(진단용). 임계 판정 없이 점수만."""
        small = self._scale(region)
        out: dict[str, float] = {}
        for bid in self._variants:
            out[bid] = self._best(small, bid)
        return out

    def _best(self, small: np.ndarray, bid: str) -> float:
        best = -1.0
        for variant in self._variants.get(bid, ()):
            if (
                variant.shape[0] <= small.shape[0]
                and variant.shape[1] <= small.shape[1]
            ):
                best = max(best, match_icon(small, variant).score)
        return best

    def _detect(self, small: np.ndarray, bid: str) -> bool:
        """이력 임계: 시작은 detect_thr 이상, 해제는 release_thr 미만. 그 사이는 유지."""
        score = self._best(small, bid)
        if score >= self._detect_thr:
            matched = True
        elif score < self._release_thr:
            matched = False
        else:
            matched = self._matched.get(bid, False)  # 경계 구간 → 직전 판정 유지
        self._matched[bid] = matched
        return matched

    def tick(self, region: np.ndarray, now: float) -> TickResult:
        small = self._scale(region)
        for bid in self._templates:
            detected = self._detect(small, bid)
            if detected:
                self._shown[bid] = False  # 걸림 → 즉시 숨김
                self._absent_since[bid] = None
            elif not self._shown[bid]:
                # 미감지 + 현재 숨김 상태: reappear_sec 연속되면 다시 표시
                if self._absent_since[bid] is None:
                    self._absent_since[bid] = now
                elif now - self._absent_since[bid] >= self._reappear:
                    self._shown[bid] = True
                    self._absent_since[bid] = None
            # 이미 표시 중(shown)이면 그대로 유지

        entries = [
            OverlayEntry(bid, None, False)
            for bid in self._order
            if self._shown.get(bid, False)
        ]
        return TickResult(entries=entries, alerts=[], frame_valid=True)
