"""보스 패턴 경고 트래커 (기획서 12).

보스 이름 + 임계% 목록을 받아, HP%가 하강하며 각 임계 T의 두 지점을 교차할 때 경고를
낸다: T+pre_offset(1차, 예고) / T+near_offset(2차). 각 1회 발동하고, HP가 그 지점 위로
다시 오르면(페이즈 리셋 등) 재무장한다.

순수 로직(화면·Qt 비의존) — 판독기(boss_hp_reader)가 준 정수 HP%를 observe()에 넣는다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PatternAlert:
    threshold: int  # 패턴 임계 %
    stage: str  # "pre"(1차 예고) / "near"(2차)
    text: str  # 화면에 띄울 문구
    sound: str  # "pre"/"near" — 호출 측이 010/026 파일로 매핑


class BossPatternTracker:
    def __init__(
        self,
        boss_name: str,
        thresholds: list[int],
        *,
        pre_offset: int = 5,
        near_offset: int = 1,
    ) -> None:
        self.boss_name = boss_name
        # 각 임계 T → (발동 HP 지점, T, stage). pre가 near보다 높다(먼저 교차).
        self._points: list[tuple[int, int, str]] = []
        for t in thresholds:
            self._points.append((t + pre_offset, t, "pre"))
            self._points.append((t + near_offset, t, "near"))
        self._armed = [True] * len(self._points)
        self._prev: int | None = None

    def observe(self, hp: int | None) -> list[PatternAlert]:
        """현재 HP%를 넣어, 이번에 발동한 경고 목록을 돌려준다(없으면 빈 리스트)."""
        if hp is None:
            return []  # 판독 실패 프레임은 무시(직전 상태 유지)
        prev = self._prev
        out: list[PatternAlert] = []
        for i, (point, t, stage) in enumerate(self._points):
            if hp > point:  # 지점 위로 오름 → 재무장(페이즈 리셋 등)
                self._armed[i] = True
            if (
                self._armed[i]
                and prev is not None
                and prev >= point > hp  # 하강하며 지점 통과
            ):
                self._armed[i] = False
                out.append(
                    PatternAlert(
                        threshold=t,
                        stage=stage,
                        text=f"{self.boss_name} {t}% 진입 준비",
                        sound=stage,
                    )
                )
        self._prev = hp
        return out
