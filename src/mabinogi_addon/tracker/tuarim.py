"""투아림 % 게이지 알림 트래커 (기획서 3.3 변형).

화면의 투아림 게이지(%, 0→100 반복)를 읽은 값을 받아, 임계값에 **도달하면** 소리 알림을
1회 낸다. 게이지가 리셋(100→0)돼 다시 차면 다음 주기에 또 울린다. 오버레이는 없다(소리만).

왜 'level(도달하면 울림)'인가 — 실게임 데이터상 게이지가 한두 프레임 만에 저값→90대로
꽉 찬다(완만한 상승이 캡처에 거의 안 잡힘). 그래서 옛 edge(완만한 상승 교차)는 한 번도 안
울렸다. 도달(level)로 바꿔 '임계에 닿으면' 울린다.

노이즈 대책(틀린 값·클립 요동에 휘둘리지 않도록):
- **발화**: 임계 이상이 FIRE_FRAMES프레임 연속이어야 울린다(단발 오독 고값 무시).
- **재무장**: 게이지가 **0 근처(≤REARM_VALUE)까지 내려간 게 REARM_FRAMES프레임 연속**일
  때만 재무장한다(= 실제 리셋: 게이지가 0부터 다시 참). 100% 유지 중 영역이 "100"의 '1'을
  잘라 "00"으로 보여 판독이 60·80 등으로 요동해도, 그 값은 0 근처가 아니라 재무장되지
  않는다 → 같은 주기에 다시 울리지 않는다. (옛날의 '임계−10 이하' 재무장은 60·80 노이즈를
  리셋으로 오인해 거짓 재알림을 냈다.)
- value=None(판독 실패/보류)은 상태 변화 없이 건너뛴다(직전 상태 유지).

임계값은 여러 개(예 90, 95). 화면 읽기·소리 재생과 분리되어 테스트 가능.
"""

from __future__ import annotations

# 발화: 임계 이상이 이만큼 연속이어야(단발 오독 고값 무시). 게이지는 꽉 차면 여러 프레임
# 머무르므로 2면 충분하다.
FIRE_FRAMES = 2
# 재무장 판정: 게이지가 이 값 이하로 내려가면 '리셋 진행 중'으로 본다. 100% 클립 노이즈
# 값(60·80 등)은 이보다 훨씬 높아 리셋으로 오인되지 않는다. 실제 리셋은 0까지 떨어진다.
REARM_VALUE = 15
# 재무장: 0 근처가 이만큼 '연속'이어야 재무장. 100% 유지 중 "00%" 클립이 0·4로 잠깐
# 읽히는 노이즈의 '≤REARM_VALUE 연속'은 실측 최대 12틱(프레임당 ~2틱)인 반면, 진짜 리셋은
# 게이지가 한동안 비어 164틱 이상 이어진다. 그 사이(20틱 ≈ 150ms틱 기준 약 3초)로 둬서
# 노이즈로는 재무장되지 않게 한다. (4였을 때 100% 유지 중 90% 재발화하던 거짓 알림 수정.)
REARM_FRAMES = 20


class TuarimTracker:
    def __init__(self, thresholds: list[int]) -> None:
        self.set_thresholds(thresholds)

    def set_thresholds(self, thresholds: list[int]) -> None:
        self._thresholds = sorted({int(t) for t in thresholds})
        self._fired: set[int] = set()  # 이미 울린 임계(재무장 전까지 억제)
        self._hi: dict[int, int] = {t: 0 for t in self._thresholds}  # 임계 이상 연속 수
        self._low = 0  # 0 근처(≤REARM_VALUE) 연속 수

    def observe(self, value: int | None) -> list[int]:
        """현재 % 값을 넣고, 이번에 '도달'한 임계 목록을 돌려준다.

        value=None(판독 실패/보류)이면 상태 변화 없이 빈 목록.
        """
        if value is None:
            return []
        # 재무장: 게이지가 0 근처까지 '지속' 내려가면(진짜 리셋) 모든 임계 재무장.
        if value <= REARM_VALUE:
            self._low += 1
            if self._low >= REARM_FRAMES:
                self._fired.clear()
        else:
            self._low = 0
        # 발화: 임계 이상이 연속 지속되고 아직 안 울렸으면 1회.
        crossed: list[int] = []
        for t in self._thresholds:
            if value >= t:
                self._hi[t] += 1
                if self._hi[t] >= FIRE_FRAMES and t not in self._fired:
                    self._fired.add(t)
                    crossed.append(t)
            else:
                self._hi[t] = 0
        return crossed
