"""디버프 트래커 엔진 (기획서 3.2).

보스 디버프 줄 영역에서 등록 디버프 아이콘을 2D 검색해, **아직 안 걸린(미감지)**
디버프만 등록 순서로 돌려준다. 버프와 반대 로직이다:
- 걸림(감지) → 즉시 숨김(오버레이에서 뺀다).
- 안 걸림(미감지) → 다시 표시는 reappear_sec 연속 미감지일 때만(깜빡임 방지).

지속시간·알림·앵커 없음. 보스가 없으면 전부 미감지 = 전부 표시(의미상 맞음).
결과는 BuffEngine과 같은 TickResult 형태라 BuffController가 그대로 쓸 수 있다.
"""

from __future__ import annotations

import numpy as np

from ..detect import DEFAULT_THRESHOLD, match_icon
from .engine import OverlayEntry, TickResult


class DebuffEngine:
    def __init__(
        self,
        templates: dict[str, np.ndarray],
        order: list[str],
        *,
        threshold: float = DEFAULT_THRESHOLD,
        reappear_sec: float = 1.5,
    ) -> None:
        self._templates = templates
        self._order = list(order)
        self._threshold = threshold
        self._reappear = reappear_sec
        # shown=True면 '안 걸림' → 오버레이 표시. 초기엔 전부 표시(보스 전 상태).
        self._shown = {bid: True for bid in templates}
        self._absent_since: dict[str, float | None] = {bid: None for bid in templates}

    def set_order(self, order: list[str]) -> None:
        self._order = list(order)

    def tick(self, region: np.ndarray, now: float) -> TickResult:
        for bid, template in self._templates.items():
            detected = match_icon(region, template).present(self._threshold)
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
