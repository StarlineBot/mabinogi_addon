"""보스 패턴 경고 트래커 (기획서 12).

보스 이름 + 임계% 목록을 받아, 각 임계 T마다 두 번 경고한다. 패턴은 HP가 T.00이 되는
순간 시작하므로, 그 '전'(T보다 위)에 울려야 의미가 있다:
- **준비(pre)**: 확정 HP가 **[T+3, T+5] 구간**에 있을 때 1회. (50% 패턴: 55~53)
- **임박(near)**: 확정 HP가 **[T+1, T+2] 구간**에 있을 때 1회. (50% 패턴: 52~51)
- 판독값 T(실제 T.xx) 이하에서는 울리지 않는다(임박 구간이 T+1부터라 T는 제외).

왜 '지점 교차'가 아니라 '구간'인가 — 판독에 공백/노이즈가 있어 정확히 한 지점을 못 짚는
경우가 많다. 구간 안 아무 프레임에서나 1회 울리면 충분하고, 구간을 (판독 공백으로)
건너뛰면 울리지 않는다(건너뜀). 구간 위로 HP가 다시 오르면 재무장한다(페이즈 리셋 등).

**급락 가드**: 직전 확정 HP − 현재 HP > 8 이면 이번 값은 판정에 쓰지 않고 기준점만 갱신한다.
구간 판정만으로는 50%를 '5'로 오독하면 5% 패턴의 임박 구간 [5,7]에 들어가 거짓 발동하므로,
한 프레임에 8%p 넘게 급락한 값은 (오독으로 보고) 건너뛴다.

순수 로직(화면·Qt 비의존) — 판독기(boss_hp_reader)가 준 정수 HP%를 observe()에 넣는다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 한 프레임(확정값) 사이 허용 하락폭. 이보다 크게 떨어지면 오독으로 보고 판정에 쓰지 않는다.
_DROP_GUARD = 8


@dataclass(frozen=True)
class PatternAlert:
    threshold: int  # 패턴 임계 %
    stage: str  # "pre"(준비) / "near"(임박)
    text: str  # 화면에 띄울 문구
    sound: str  # "pre"/"near" — 호출 측이 소리 파일로 매핑


class BossPatternTracker:
    def __init__(
        self,
        boss_name: str,
        thresholds: list[int],
        *,
        pre_band: tuple[int, int] = (3, 5),
        near_band: tuple[int, int] = (1, 2),
    ) -> None:
        self.boss_name = boss_name
        # 각 임계 T → (구간 lo, 구간 hi, T, stage). pre가 near보다 위 구간.
        self._bands: list[tuple[int, int, int, str]] = []
        for t in thresholds:
            self._bands.append((t + pre_band[0], t + pre_band[1], t, "pre"))
            self._bands.append((t + near_band[0], t + near_band[1], t, "near"))
        self._armed = [True] * len(self._bands)
        self._prev: int | None = None
        self._last_upcoming: list[int] = []  # 판독 실패 프레임에 유지할 직전 목록

    def observe(self, hp: int | None) -> list[PatternAlert]:
        """현재 HP%를 넣어, 이번에 발동한 경고 목록을 돌려준다(없으면 빈 리스트)."""
        if hp is None:
            return []  # 판독 실패 프레임은 무시(직전 상태 유지)
        prev = self._prev
        # 급락 가드: 한 프레임에 8%p 넘게 떨어졌으면(50→'5' 오독 등) 판정에 안 쓰고 기준점만.
        if prev is not None and prev - hp > _DROP_GUARD:
            self._prev = hp
            return []
        self._prev = hp
        out: list[PatternAlert] = []
        for i, (lo, hi, t, stage) in enumerate(self._bands):
            if hp > hi:  # 구간 위로 오름 → 재무장(페이즈 리셋 등)
                self._armed[i] = True
            if self._armed[i] and lo <= hp <= hi:  # 구간 안 + 아직 안 울림 → 1회
                self._armed[i] = False
                label = "준비" if stage == "pre" else "임박"
                out.append(
                    PatternAlert(
                        threshold=t,
                        stage=stage,
                        text=f"{self.boss_name} {t}% 패턴 {label}",
                        sound=stage,
                    )
                )
        return out

    def upcoming(self, hp: int | None) -> list[int]:
        """지금 HP보다 아래에 있고 아직 '준비'(pre) 알림이 안 뜬 임계 목록(내림차순).

        '다음에 올 패턴'을 왼쪽에 미리 나열하는 용도. 각 임계의 준비 알림이 발동하면 그
        임계는 목록에서 빠지고, 페이즈 리셋(HP가 위로 다시 오름)으로 재무장되면 다시 들어온다.
        판독 실패(None) 프레임은 직전 목록을 그대로 유지한다. observe() 뒤에 호출.
        """
        if hp is None:
            return list(self._last_upcoming)
        out = sorted(
            {
                t
                for (_lo, _hi, t, stage), armed in zip(self._bands, self._armed)
                if stage == "pre" and armed and t < hp
            },
            reverse=True,
        )
        self._last_upcoming = out
        return out
