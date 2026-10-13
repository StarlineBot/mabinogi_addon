"""투아림 % 게이지 알림 트래커 (기획서 3.3 변형).

화면의 투아림 게이지(%, 0→100 반복)를 읽은 값을 받아, 임계값에 **도달하면** 소리 알림을
1회 낸다. 게이지가 리셋(100→0)돼 다시 차면 다음 주기에 또 울린다. 오버레이는 없다(소리만).

왜 'level(도달하면 울림)'인가 — 과거엔 'edge(틱당 ≤5로 완만히 넘는 순간)'였는데, 실게임
데이터로 보니 **게이지가 한두 프레임 만에 저값→90대로 꽉 찬다**(완만한 상승이 캡처에 거의
안 잡힘). 그래서 edge는 교차 순간을 못 봐 **한 번도 안 울렸다**. 도달(level)로 바꿔 '임계에
닿으면' 울린다.

노이즈 대책(틀린 값에 휘둘리지 않도록):
- **발화**: 임계 이상이 FIRE_FRAMES프레임 연속이어야 울린다(단발 오독 고값 무시).
- **재무장**: 임계보다 REARM_DROP 넘게 낮은 값이 RESET_FRAMES프레임 연속일 때만(=게이지가
  실제로 리셋/하강). 한두 틱짜리 오독 급락엔 재무장하지 않아, 한 주기에 여러 번 울리지 않는다.
- value=None(판독 실패/보류)은 상태 변화 없이 건너뛴다(직전 상태 유지).

임계값은 여러 개(예 90, 95). 화면 읽기·소리 재생과 분리되어 테스트 가능.
"""

from __future__ import annotations

# 한 번 울린 임계는 게이지가 이만큼 아래로 내려가야 다시 무장된다(리셋/하강 판정 기준).
REARM_DROP = 10
# 발화: 임계 이상이 이만큼 연속이어야(단발 오독 고값 무시). 게이지는 꽉 차면 여러 프레임
# 머무르므로 2면 충분하다.
FIRE_FRAMES = 2
# 재무장: 임계−REARM_DROP 이하가 이만큼 연속이어야(진짜 리셋). 한두 틱짜리 오독 급락으로
# 재무장돼 같은 주기에 또 울리는 것을 막는다. 리셋 뒤 게이지는 한동안 낮으므로 넉넉하다.
RESET_FRAMES = 5


class TuarimTracker:
    def __init__(self, thresholds: list[int]) -> None:
        self.set_thresholds(thresholds)

    def set_thresholds(self, thresholds: list[int]) -> None:
        self._thresholds = sorted({int(t) for t in thresholds})
        self._fired: set[int] = set()  # 이미 울린 임계(재무장 전까지 억제)
        self._hi: dict[int, int] = {t: 0 for t in self._thresholds}  # 임계 이상 연속 수
        self._lo: dict[int, int] = {t: 0 for t in self._thresholds}  # 리셋권 연속 수

    def observe(self, value: int | None) -> list[int]:
        """현재 % 값을 넣고, 이번에 '도달'한 임계 목록을 돌려준다.

        value=None(판독 실패/보류)이면 상태 변화 없이 빈 목록.
        """
        if value is None:
            return []
        crossed: list[int] = []
        for t in self._thresholds:
            # 재무장: 충분히 낮은 값이 연속 지속되면(진짜 리셋) 억제 해제.
            if value <= t - REARM_DROP:
                self._lo[t] += 1
                if self._lo[t] >= RESET_FRAMES:
                    self._fired.discard(t)
            else:
                self._lo[t] = 0
            # 발화: 임계 이상이 연속 지속되고 아직 안 울렸으면 1회.
            if value >= t:
                self._hi[t] += 1
                if self._hi[t] >= FIRE_FRAMES and t not in self._fired:
                    self._fired.add(t)
                    crossed.append(t)
            else:
                self._hi[t] = 0
        return crossed
