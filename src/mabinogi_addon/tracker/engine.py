"""버프 탐지 파이프라인 결합 (기획서 4.1).

캡처한 버프 패널 영역 하나를 받아 매 틱:
  detect_buffs(아이콘 열) → 각 버프 행 시간 판독 → BuffStateMachine.observe
앵커가 보이면 '정상 프레임', 아니면 '판정 불가'(상태 동결). 결과로 오버레이에 그릴
항목 목록과 이번 틱에 울린 알림을 돌려준다. UI·캡처 방식과 무관(테스트 가능).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..detect import detect_buffs, read_time, score_sets, set_names
from ..detect.buff_detector import Detection
from ..detect.favorites import FavoritesReader
from ..detect.icon_matcher import DEFAULT_THRESHOLD
from .buff_state import BuffStateMachine, Event, State


@dataclass
class OverlayEntry:
    buff_id: str
    remaining: float | None  # 내부 시계 남은 초(판독값 없으면 None)
    alerting: bool  # 만료임박(과거: 점멸 / 현재 미사용)
    gone: bool = False  # 사라짐 경고(디버프: 보스에서 떨어짐) → 빨간 테두리+X


@dataclass
class TickResult:
    entries: list[OverlayEntry]  # 표시 순서대로, 활성/임박 버프만
    alerts: list[str]  # 이번 틱에 만료임박(1차) 알림이 발생한 buff_id
    frame_valid: bool  # 정상 프레임 여부(앵커 보임)
    alerts2: list[str] = field(default_factory=list)  # 2차(막차) 알림이 발생한 buff_id


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
        favorites: bool = False,
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
        # 즐겨찾기 칸 읽기(기획서 3.1.1, 0.26.0 제작자 알파): 구분선 위 = 즐겨찾기(켜짐/꺼짐), 아래 = 기존 목록.
        # 끄면(기본) 지금 목록 방식 그대로다.
        self.favorites = FavoritesReader(templates, icon_column) if favorites else None

        self._anchor_seen = False  # 앵커를 한 번이라도 봤는지(게이팅 안전장치)
        # 시간 템플릿 세트 자동선택: 모니터·스케일링마다 글자 렌더링이 달라 세트가 여럿.
        # 워밍업 동안 세트별 신뢰도를 누적해, 리더가 충분히 앞서면 그 세트로 고정한다.
        self._time_set: str | None = None  # 고정된 세트(None=아직 워밍업)
        self._set_conf: dict[str, float] = {}
        self._locked_misses = 0  # 고정 세트로 연속 못 읽은 횟수(화면 크기가 중간에 바뀌면 다시 고르기)
        if len(set_names()) <= 1:  # 세트가 하나뿐이면 바로 고정(기본)
            only = set_names()
            self._time_set = only[0] if only else None
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
        # 시간 판독 throttle: 아이콘 존재는 매 틱 빠르게 보되, 시간(초단위)은 자주 안
        # 읽어도 내부 시계가 카운트다운·알림을 유지한다. 등장 직후 1회 + 이후 _TIME_READ_GAP
        # 마다 + '임박 근처'엔 매 틱(연장을 놓쳐 거짓 알림 나는 걸 막음).
        self._present_prev: set[str] = set()
        self._last_read_at: dict[str, float] = {}
        self._last_y: dict[str, int] = {}  # 마지막으로 아이콘을 본 행(미검출 시 시간-확정용)

    # 초. 임박 근처가 아니면 이 간격으로만 시간 판독(OCR 비용 절약). 단 이 값이 크면
    # 임박 전에 '재버프(연장)'한 경우 반영이 이만큼 늦어 보인다(옛 클럭이 계속 내려가다
    # 뒤늦게 점프). 1.0초면 재버프가 ~1~2초 안에 반영되고 비용도 미미하다.
    _TIME_READ_GAP = 1.0
    _NEAR_MARGIN = 8.0  # 알림 기준 + 이 값 이내면 매 틱 판독(연장 즉시 반영)
    _TIME_CONFIRM_TOL = 3.0  # 미검출 시 읽은 시간이 내부 시계와 이 오차 이내면 '살아있음'

    @property
    def anchor_seen(self) -> bool:
        """기준(앵커) 버프를 한 번이라도 검출했는지(진단 상태 표시용)."""
        return self._anchor_seen

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

    def tick(
        self, region: np.ndarray, now: float, foreground: bool = True
    ) -> TickResult:
        # foreground: 게임이 포그라운드일 때만 '소리 알림(만료 임박)'을 낸다. 탐지·시간
        # 읽기는 포커스와 무관하게 계속해 시간을 동기화하되, 알림만 포커스+화면 확정 시로
        # 제한한다(비포커스 중의 거짓/추정 알림 방지). 복귀하면 아직 임박인 버프는 그때 운다.
        detections = detect_buffs(
            region, self._templates, self._icon_column, self._threshold
        )
        if self.favorites is not None:
            detections = self._split_favorites(region, detections)
        present = {d.buff_id: d for d in detections}
        # 앵커 게이팅: 앵커가 한 번도 안 보였으면(영역에 앵커가 없는 설정 등)
        # 게이팅하지 않는다 — 즉 기존처럼 항상 정상 프레임으로 본다.
        # 앵커를 한 번이라도 본 뒤부터는, 앵커가 사라진 프레임은 '판정 불가'로
        # 간주해 상태를 동결(내부 시계로 버팀)하고, 다시 보이면 실제 시간으로 동기화.
        anchor_present = self._anchor is not None and self._anchor in present
        if anchor_present:
            self._anchor_seen = True
        frame_valid = (
            self._anchor is None or anchor_present or not self._anchor_seen
        )

        alerts: list[str] = []
        alerts2: list[str] = []
        for bid, machine in self._machines.items():
            det = present.get(bid)
            detected = det is not None
            reading: float | None = None
            if detected:
                self._last_y[bid] = det.y  # 미검출 시 시간-확정에 쓸 마지막 행
                if self._show_duration.get(bid, True):
                    just_appeared = bid not in self._present_prev
                    rem = machine.remaining(now)
                    near = (
                        rem is not None and rem <= machine.alert_before + self._NEAR_MARGIN
                    )
                    last = self._last_read_at.get(bid, float("-inf"))
                    if just_appeared or near or (now - last) >= self._TIME_READ_GAP:
                        reading = self._read_row_time(region, det.y)
                        self._last_read_at[bid] = now
            elif (
                frame_valid
                and self._show_duration.get(bid, True)
                and machine.state in (State.ACTIVE, State.EXPIRING)
            ):
                # 아이콘이 잠깐 안 잡힘(가림·점멸 등): 그 행의 시간을 읽어 내부 시계와
                # 일치하면 '아직 살아있음'으로 인정(= 종료임박인데 깜빡인 것). 진짜 종료면
                # 아래 줄이 올라와 그 자리 시간이 시계와 안 맞아 인정되지 않고, 곧 해제된다.
                rem = machine.remaining(now)
                y = self._last_y.get(bid)
                if rem is not None and rem > 0 and y is not None:
                    t = self._read_row_time(region, y)
                    if t is not None and abs(t - rem) <= self._TIME_CONFIRM_TOL:
                        detected = True
                        reading = float(t)
                        self._last_read_at[bid] = now
            event = machine.observe(
                detected=detected,
                reading=reading,
                now=now,
                frame_valid=frame_valid,
                foreground=foreground,
            )
            if event is Event.ALERT:
                alerts.append(bid)
            # 2차 알림: 더 가까운 기준 교차 시 1회 더(놓침·오독 대비). 포그라운드일 때만.
            # 1차와 분리해 alerts2로 — 앱이 '막차' 전용 소리(연장2.mp3)를 재생한다.
            if foreground and frame_valid and machine.check_second_alert(now):
                alerts2.append(bid)

        self._present_prev = set(present)  # 다음 틱의 '방금 등장' 판정용

        entries = []
        for bid in self._order:
            machine = self._machines.get(bid)
            if machine is not None and machine.state is not State.ABSENT:
                entries.append(
                    OverlayEntry(bid, machine.remaining(now), machine.alerting)
                )
        return TickResult(
            entries=entries, alerts=alerts, frame_valid=frame_valid, alerts2=alerts2
        )

    def _split_favorites(self, region: np.ndarray, detections: list[Detection]) -> list[Detection]:
        """구분선 위 아이콘은 목록 검출에서 빼고, 기억한 즐겨찾기 줄 중 켜진 것만 그 줄 위치로 넣는다.
        기준 버프가 즐겨찾기에 있어도 켜져 있으면 정상 프레임으로 본다(기준 버프 미검출 경고 없음)."""
        reader = self.favorites
        reader.update(region, [d.y for d in detections])
        boundary = reader.boundary
        if boundary is None:
            return detections  # 구분선 없음: 전체를 목록으로(즐겨찾기를 안 쓰는 사람·예전 영역 호환)
        listed = [d for d in detections if d.y > boundary and d.buff_id not in reader.rows]
        for bid, row in reader.rows.items():
            if reader.on.get(bid):
                listed.append(Detection(bid, 1.0, row.y))
        listed.sort(key=lambda d: d.y)
        return listed

    # 세트 고정 기준: 누적 신뢰도(≈ 좋은 판독 몇 회분)가 이만큼 앞서면 고정.
    _SET_LOCK_CONF = 3.0
    # 고정 세트로 연속 이만큼 못 읽으면 모든 세트로 한 번 확인(다른 세트가 읽으면 고정을 풀고 다시 고른다).
    _RESELECT_AFTER = 8

    def _read_row_time(self, region: np.ndarray, icon_y: int) -> float | None:
        top = max(0, icon_y - self._row_pad_top)
        strip = region[top : icon_y + self._row_height, self._time_x0 :]
        if strip.size == 0:
            return None
        if self._time_set is not None:  # 이미 고정됨 → 그 세트만(빠름)
            value = read_time(strip, set_name=self._time_set)
            if value is not None or len(set_names()) <= 1:
                self._locked_misses = 0
                return value
            # Alt+Tab 등으로 글자 크기가 바뀌면 고정 세트로는 계속 못 읽는다(0.30.1 4K 조사).
            # 시간 없는 버프 줄도 못 읽으므로, 여러 번 연속일 때만 모든 세트로 확인하고 다른 세트가 읽으면 다시 고른다.
            self._locked_misses += 1
            if self._locked_misses < self._RESELECT_AFTER:
                return None
            self._locked_misses = 0
            if not any(val is not None for val, _conf in score_sets(strip).values()):
                return None
            self._time_set, self._set_conf = None, {}  # 고정 해제 → 아래 워밍업으로 다시 고름
        # 워밍업: 모든 세트로 읽어 신뢰도 누적, 이번 프레임은 최고 신뢰도 값 사용.
        best_val: float | None = None
        best_conf = -1.0
        for name, (val, conf) in score_sets(strip).items():
            if val is None:
                continue
            self._set_conf[name] = self._set_conf.get(name, 0.0) + conf
            if conf > best_conf:
                best_conf, best_val = conf, val
        if self._set_conf:
            lead = max(self._set_conf, key=self._set_conf.get)
            if self._set_conf[lead] >= self._SET_LOCK_CONF:
                self._time_set = lead  # 리더가 충분히 쌓임 → 고정
        return best_val
