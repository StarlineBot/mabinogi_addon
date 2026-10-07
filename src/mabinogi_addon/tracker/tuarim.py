"""투아림 % 게이지 알림 트래커 (기획서 3.3 변형).

화면의 투아림 게이지(%, 0→100 반복)를 읽은 값을 받아, 지정한 임계값 이상이 되면
'소리 알림'을 1회 발생시킨다. 값이 임계 아래로 떨어지면(100%→0% 리셋 포함) 다시
무장되어 다음 주기에 또 울린다. 오버레이는 없다(소리만).

임계값은 독립적으로 여러 개(예: 95, 98). 화면 읽기·소리 재생과 분리되어 테스트 가능.
"""

from __future__ import annotations


class TuarimTracker:
    def __init__(self, thresholds: list[int]) -> None:
        self.set_thresholds(thresholds)

    def set_thresholds(self, thresholds: list[int]) -> None:
        self._thresholds = sorted({int(t) for t in thresholds})
        # 각 임계는 처음엔 무장 상태(한 번 울릴 준비).
        self._armed = {t: True for t in self._thresholds}

    def observe(self, value: int | None) -> list[int]:
        """현재 % 값을 넣고, 이번에 '울려야 할' 임계 목록을 돌려준다.

        value=None(판독 실패)이면 상태 변화 없이 빈 목록.
        """
        if value is None:
            return []
        fired: list[int] = []
        for t in self._thresholds:
            if value < t:
                self._armed[t] = True  # 미달/리셋 → 재무장
            elif self._armed[t]:
                fired.append(t)
                self._armed[t] = False  # 이번 주기엔 한 번만
        return fired
