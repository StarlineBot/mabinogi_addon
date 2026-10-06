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

# 매칭 전 영역을 이 높이로 정규화한다(디버프 줄 아이콘≈영역 높이로 가정).
# 템플릿도 같은 높이로 맞춰 matchTemplate 크기 불일치를 없애고, 좁은 영역이라 빠르다.
_NORM_H = 18
# 아이콘이 영역을 꽉 채우거나(1.0) 위아래 여백이 좀 있는 경우(0.75)까지 커버.
_VARIANT_FACTORS = (1.0, 0.75)
# 디버프는 아이콘이 작고 숫자(4M 등)가 겹쳐 실데이터 점수가 ~0.65~0.84로 낮게 나온다.
# (안 걸린 것은 ≤0.56) → 버프(0.8)보다 낮은 전용 임계값을 쓴다.
DEBUFF_THRESHOLD = 0.6


def _variant(template: np.ndarray, target_h: int) -> np.ndarray:
    h, w = template.shape[:2]
    tw = max(6, round(w * target_h / h))
    return cv2.resize(template, (tw, target_h), interpolation=cv2.INTER_AREA)


class DebuffEngine:
    def __init__(
        self,
        templates: dict[str, np.ndarray],
        order: list[str],
        *,
        threshold: float = DEBUFF_THRESHOLD,
        reappear_sec: float = 1.5,
    ) -> None:
        self._templates = templates
        self._order = list(order)
        self._threshold = threshold
        self._reappear = reappear_sec
        # 정규화 높이 기준 배율 변형을 미리 생성(틱마다 resize 비용 제거).
        self._variants = {
            bid: [_variant(t, max(6, round(_NORM_H * f))) for f in _VARIANT_FACTORS]
            for bid, t in templates.items()
        }
        # shown=True면 '안 걸림' → 오버레이 표시. 초기엔 전부 표시(보스 전 상태).
        self._shown = {bid: True for bid in templates}
        self._absent_since: dict[str, float | None] = {bid: None for bid in templates}

    def set_order(self, order: list[str]) -> None:
        self._order = list(order)

    @staticmethod
    def _normalize(region: np.ndarray) -> np.ndarray:
        """영역을 고정 높이(_NORM_H)로 축소 — 아이콘 크기 정규화 + 매칭 비용 절감."""
        h = region.shape[0]
        if h == _NORM_H or h == 0:
            return region
        scale = _NORM_H / h
        return cv2.resize(
            region,
            (max(1, round(region.shape[1] * scale)), _NORM_H),
            interpolation=cv2.INTER_AREA,
        )

    def best_scores(self, region: np.ndarray) -> dict[str, float]:
        """각 디버프의 최고 매칭 점수(진단용). 임계 판정 없이 점수만."""
        norm = self._normalize(region)
        out: dict[str, float] = {}
        for bid, variants in self._variants.items():
            best = -1.0
            for variant in variants:
                if (
                    variant.shape[0] <= norm.shape[0]
                    and variant.shape[1] <= norm.shape[1]
                ):
                    best = max(best, match_icon(norm, variant).score)
            out[bid] = best
        return out

    def _detected(self, norm: np.ndarray, bid: str) -> bool:
        """정규화 영역에서 배율 변형 중 하나라도 임계 이상이면 '걸림'."""
        for variant in self._variants.get(bid, ()):
            if (
                variant.shape[0] <= norm.shape[0]
                and variant.shape[1] <= norm.shape[1]
                and match_icon(norm, variant).present(self._threshold)
            ):
                return True
        return False

    def tick(self, region: np.ndarray, now: float) -> TickResult:
        norm = self._normalize(region)
        for bid in self._templates:
            detected = self._detected(norm, bid)
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
