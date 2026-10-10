"""투아림 % 게이지 알림 트래커 (기획서 3.3 변형).

화면의 투아림 게이지(%, 0→100 반복)를 읽은 값을 받아, 임계값을 '실시간으로 완만히
넘는 순간(edge)'에만 소리 알림을 1회 낸다. 게이지가 리셋(100→0) 후 다시 완만히
오르면 다음 주기에 또 울린다. 오버레이는 없다(소리만).

왜 'level(값이 임계 이상이면 울림)'이 아니라 'edge(완만한 상승 교차)'인가:
- 자리를 비웠다 돌아오면 값이 '점프'해(예 85→93) 이미 임계 이상인데, level이면 매번
  다시 울린다. edge+상승폭 제한이면 점프는 교차로 안 봐서 재진입마다 울리지 않는다.
- 판독 오탐(한 틱만 다른 값)으로 값이 급락·급등해도 큰 점프라 교차로 치지 않는다.

임계값은 여러 개(예 95, 98). 화면 읽기·소리 재생과 분리되어 테스트 가능.
"""

from __future__ import annotations

# 한 틱(확정값) 사이 허용 상승폭. 이보다 크게 오르면 실시간 교차가 아니라
# 재진입/오탐복구/리셋후재상승으로 보고 울리지 않는다. 게이지는 틱당 천천히 오른다.
MAX_RISE = 5
# 한 번 울린 임계는 게이지가 이만큼 아래로 내려가야(=리셋/하강) 다시 무장된다.
# 임계 경계(예 95%)에서 판독값이 흔들려(94→95→94→95) 같은 교차가 2~3번 울리던
# 문제 방지(히스테리시스). 게이지는 매 주기 0까지 떨어지므로 다음 주기엔 반드시 재무장.
REARM_DROP = 10


class TuarimTracker:
    def __init__(self, thresholds: list[int]) -> None:
        self.set_thresholds(thresholds)

    def set_thresholds(self, thresholds: list[int]) -> None:
        self._thresholds = sorted({int(t) for t in thresholds})
        self._prev: int | None = None  # 직전 값(교차 판정 기준)
        self._fired: set[int] = set()  # 이번 주기에 이미 울린 임계(재무장 전까지 억제)

    def observe(self, value: int | None) -> list[int]:
        """현재 % 값을 넣고, 이번에 '완만히 넘은' 임계 목록을 돌려준다.

        value=None(판독 실패)이면 상태 변화 없이 빈 목록(직전 값 유지).
        """
        if value is None:
            return []
        prev = self._prev
        self._prev = value
        # 임계보다 충분히 내려오면(리셋/하강) 그 임계를 재무장 → 다음 상승에 다시 울림.
        for t in self._thresholds:
            if value <= t - REARM_DROP:
                self._fired.discard(t)
        if prev is None:
            return []  # 첫 값은 기준점만 잡음
        rise = value - prev
        if not (0 < rise <= MAX_RISE):
            return []  # 하강·정체·큰 점프 → 교차 아님
        crossed = [
            t for t in self._thresholds if prev < t <= value and t not in self._fired
        ]
        self._fired.update(crossed)  # 울린 임계는 재무장 전까지 억제(경계 흔들림 방지)
        return crossed
