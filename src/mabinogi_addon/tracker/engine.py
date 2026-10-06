"""버프 탐지 파이프라인 결합 (기획서 4.1).

캡처한 버프 패널 영역 하나를 받아 매 틱:
  detect_buffs(아이콘 열) → 각 버프 행 시간 판독 → BuffStateMachine.observe
앵커가 보이면 '정상 프레임', 아니면 '판정 불가'(상태 동결). 결과로 오버레이에 그릴
항목 목록과 이번 틱에 울린 알림을 돌려준다. UI·캡처 방식과 무관(테스트 가능).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..detect import detect_buffs, read_time
from ..detect.icon_matcher import DEFAULT_THRESHOLD
from .buff_state import BuffStateMachine, Event, State


@dataclass
class OverlayEntry:
    buff_id: str
    remaining: float | None  # 내부 시계 남은 초(판독값 없으면 None)
    alerting: bool  # 만료임박(점멸)


@dataclass
class TickResult:
    entries: list[OverlayEntry]  # 표시 순서대로, 활성/임박 버프만
    alerts: list[str]  # 이번 틱에 만료임박 알림이 발생한 buff_id
    frame_valid: bool  # 정상 프레임 여부(앵커 보임)


class BuffEngine:
    def __init__(
        self,
        templates: dict[str, np.ndarray],
        order: list[str],
        *,
        anchor_id: str | None = None,
        show_duration: dict[str, bool] | None = None,
        alert_before: dict[str, int] | None = None,
        alert_before2: dict[str, int | None] | None = None,
        icon_column: tuple[int, int] = (0, 50),
        time_x0: int = 150,
        row_pad_top: int = 4,
        row_height: int = 24,
        appear_frames: int = 3,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self._templates = templates
        self._order = list(order)
        self._anchor = anchor_id
        self._show_duration = show_duration or {}
        self._icon_column = icon_column
        self._time_x0 = time_x0
        self._row_pad_top = row_pad_top
        self._row_height = row_height
        self._threshold = threshold

        before = alert_before or {}
        before2 = alert_before2 or {}
        self._machines = {
            bid: BuffStateMachine(
                alert_before=before.get(bid, 30),
                alert_before2=before2.get(bid),
                appear_frames=appear_frames,
            )
            for bid in templates
        }

    def set_order(self, order: list[str]) -> None:
        """표시 순서 갱신(실행 중 버프 목록 재정렬·숨김 반영). 상태는 유지."""
        self._order = list(order)

    def set_show_duration(self, show_duration: dict[str, bool]) -> None:
        self._show_duration = dict(show_duration)

    def set_alert_before(self, alert_before: dict[str, int]) -> None:
        for bid, machine in self._machines.items():
            machine.alert_before = alert_before.get(bid, 30)

    def set_alert_before2(self, alert_before2: dict[str, int | None]) -> None:
        for bid, machine in self._machines.items():
            machine.alert_before2 = alert_before2.get(bid)

    def tick(self, region: np.ndarray, now: float) -> TickResult:
        detections = detect_buffs(
            region, self._templates, self._icon_column, self._threshold
        )
        present = {d.buff_id: d for d in detections}
        frame_valid = self._anchor is None or self._anchor in present

        alerts: list[str] = []
        for bid, machine in self._machines.items():
            det = present.get(bid)
            detected = det is not None
            reading: float | None = None
            if detected and self._show_duration.get(bid, True):
                reading = self._read_row_time(region, det.y)
            event = machine.observe(
                detected=detected, reading=reading, now=now, frame_valid=frame_valid
            )
            if event is Event.ALERT:
                alerts.append(bid)
            # 2차 알림: 더 가까운 기준 교차 시 1회 더(놓침·오독 대비).
            if frame_valid and machine.check_second_alert(now):
                alerts.append(bid)

        entries = []
        for bid in self._order:
            machine = self._machines.get(bid)
            if machine is not None and machine.state is not State.ABSENT:
                entries.append(
                    OverlayEntry(bid, machine.remaining(now), machine.alerting)
                )
        return TickResult(entries=entries, alerts=alerts, frame_valid=frame_valid)

    def _read_row_time(self, region: np.ndarray, icon_y: int) -> float | None:
        top = max(0, icon_y - self._row_pad_top)
        strip = region[top : icon_y + self._row_height, self._time_x0 :]
        if strip.size == 0:
            return None
        return read_time(strip)
