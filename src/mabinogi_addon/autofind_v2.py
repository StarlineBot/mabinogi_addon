"""자동 찾기 v2 — 찾기 엔진의 순수 로직(제작자 테스트판, docs/autofind-v2-creator-spec.md 1~3절).

Qt·캡처와 분리된 상태 기계다. 시계·프레임·탐지기를 밖에서 넣어 맥에서 가짜로 시험한다.
- 처음 찾기(3.1): 한 번 찍은 화면 하나로 정해진 순서(지난 자리 → 단축바 → 체력바 → 버프 → 도르카·투아림 묶음)를 차례로,
  항목 사이 짧게 쉬고, CPU 상한을 넘으면 남은 항목은 '못 찾음'. 보스바·전투 시간은 보이면 찾고 아니면 '대기'.
- 안정(3.2): 찾기 0. 각 기능이 자기 판독 결과만 알려 준다(note_read) — 엔진이 따로 캡처해 확인하지 않는다
  (0.39.0 CPU 상승 원인: 안정 뒤에도 0.5초마다 움직이는 항목을 직접 찍어 판독하고, 대기 항목 전체 탐색을 돌렸다).
- 다시 찾기(3.3): 10초 넘게 못 읽은 켜진 항목만, 3번 연속 실패하면 1분 간격, 다시 읽히면 초기화. 게임이 앞에 없는 동안은 시간을 세지 않는다.
- 새 자리 확정: 새 자리에서 새 판독이 약 3초 연속 성공해야 확정(실패 한 번이면 처음부터, 10초 안에 못 하면 실패 1회).
- 나타나면 찾기(3.4): 대기 항목은 예상 자리만 1초에 1번, 화면 전체는 60초에 1번.
- 게임 창 크기·재시작: 세대 번호를 올리고 진행 결과를 버린 뒤 처음 찾기부터.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

FIRST_ORDER = ("skillbar", "stat_bars", "buff", "resources")  # resources = 도르카·투아림 묶음(탐지기 하나)
RESOURCE_KEYS = ("dorcha", "tuarim")
APPEAR_KEYS = ("boss", "halo_timer")
KEYS = ("skillbar", "stat_bars", "buff", "dorcha", "tuarim", "boss", "halo_timer")
NAMES = {"skillbar": "단축바", "stat_bars": "체력바", "buff": "버프", "dorcha": "도르카", "tuarim": "투아림",
         "boss": "보스바", "halo_timer": "전투 시간"}

CPU_LIMIT = 20.0        # 처음 찾기 CPU 상한(초)
REST = 0.05             # 항목 사이 쉬기(초)
LOST_SECONDS = 10.0     # 이만큼 못 읽으면 다시 찾기
RETRY_SECONDS = 10.0
SLOW_RETRY_SECONDS = 60.0
SLOW_AFTER = 3          # 연속 실패 횟수 → 1분 간격
CONFIRM_SECONDS = 3.0
TRIAL_LIMIT = 10.0      # 새 자리 시험 상한
APPEAR_SMALL_EVERY = 1.0
APPEAR_FULL_EVERY = 60.0
UI_RETRY_SECONDS = 10.0

FOUND, MISSING, WAITING, PENDING, SEARCHING = "found", "missing", "waiting", "pending", "searching"


@dataclass
class Item:
    key: str
    status: str = PENDING
    box: tuple | None = None
    source: str = ""          # "last" | "search" | "appear" | "research" | "user"
    seconds: float = 0.0
    reason: str = ""
    lost: float = 0.0
    unhealthy: bool = False
    failures: int = 0
    next_try: float = 0.0
    candidate: "Trial | None" = None
    user: bool = False        # 이 실행 동안 사용자 지정이 이김

    def label(self, now: float | None = None) -> str:
        if self.user:
            return "직접 지정 · 이번 실행 동안 사용"
        if self.candidate is not None:
            return "새 자리 확인 중"
        if self.status == FOUND:
            return "찾음 · 지난 자리 그대로" if self.source == "last" else f"찾음 · {self.seconds:.1f}초"
        if self.status == WAITING:
            return "나타나면 찾기 (대기)"
        if self.status == SEARCHING:
            return "찾는 중…"
        if self.status == MISSING:
            wait = "" if now is None or self.next_try <= now else f" · 다음 시도 {round(self.next_try - now)}초 뒤"
            return f"못 찾음 · {self.reason or '화면에 없음'}{wait}"
        return "대기"


@dataclass
class Trial:
    """새 자리 확정 — 새 판독(같은 판독 번호 중복 제외)이 CONFIRM_SECONDS 연속 성공. 실패 한 번이면 처음부터."""
    box: tuple
    generation: int
    started: float
    elapsed: float = 0.0
    last_time: float | None = None
    last_frame: object = None

    def observe(self, *, frame_id, now: float, ok: bool) -> bool:
        if frame_id == self.last_frame:
            return False
        self.last_frame = frame_id
        if not ok:
            self.elapsed, self.last_time = 0.0, None
            return False
        if self.last_time is not None:
            self.elapsed += max(0.0, now - self.last_time)
        self.last_time = now
        return self.elapsed >= CONFIRM_SECONDS

    def pause(self) -> None:
        self.last_time = None  # 쉬는 동안의 시간은 세지 않는다


@dataclass
class InitialResult:
    boxes: dict = field(default_factory=dict)       # key → box(프레임 좌표)
    status: dict = field(default_factory=dict)      # key → FOUND/MISSING/WAITING
    seconds: dict = field(default_factory=dict)     # key → 걸린 시간
    source: dict = field(default_factory=dict)      # key → "last"/"search"
    wall: float = 0.0
    cpu: float = 0.0
    stopped_by_cap: bool = False


def run_initial(frame, finders: dict, *, last: dict | None = None, readers: dict | None = None,
                cpu_clock=time.thread_time, clock=time.perf_counter, sleep=time.sleep,
                cpu_limit: float = CPU_LIMIT, rest: float = REST) -> InitialResult:
    """작업 스레드: 한 번 찍은 화면(frame) 하나로 처음 찾기. finders[key](frame) → box|None
    (resources는 {'dorcha': box, 'tuarim': box}), readers[key](crop) → bool(지난 자리 확인용)."""
    last, readers = last or {}, readers or {}
    out = InitialResult()
    wall0, cpu0 = clock(), cpu_clock()

    def over() -> bool:
        return cpu_clock() - cpu0 > cpu_limit

    # ① 지난 자리 확인 — 그 자리만 잘라 판독(수 ms)
    for key, box in last.items():
        reader = readers.get(key)
        if reader is None or box is None:
            continue
        x, y, w, h = box
        crop = frame[y:y + h, x:x + w]
        if crop.shape[:2] == (h, w) and x >= 0 and y >= 0:
            t0 = clock()
            ok = False
            try:
                ok = bool(reader(crop))
            except Exception:  # noqa: BLE001 — 지난 자리 확인 실패는 찾기로 넘김
                ok = False
            if ok:
                out.boxes[key], out.status[key], out.source[key] = tuple(box), FOUND, "last"
                out.seconds[key] = clock() - t0
    # ② 순서대로 찾기
    for group in FIRST_ORDER + APPEAR_KEYS:
        keys = RESOURCE_KEYS if group == "resources" else (group,)
        if all(out.status.get(k) == FOUND for k in keys):
            continue
        if over():
            out.stopped_by_cap = True
            for k in keys:
                out.status.setdefault(k, WAITING if k in APPEAR_KEYS else MISSING)
            continue
        finder = finders.get(group)
        if finder is None:
            continue
        t0 = clock()
        try:
            found = finder(frame)
        except Exception:  # noqa: BLE001 — 한 탐지기 실패가 나머지를 막지 않게
            found = None
        took = clock() - t0
        if group == "resources":
            found = found or {}
            for k in keys:
                if out.status.get(k) == FOUND:
                    continue
                box = found.get(k)
                out.status[k] = FOUND if box is not None else MISSING
                out.seconds[k] = took
                if box is not None:
                    out.boxes[k], out.source[k] = tuple(box), "search"
        else:
            key = group
            if found is not None:
                out.boxes[key], out.status[key], out.source[key] = tuple(found), FOUND, "search"
            else:
                out.status[key] = WAITING if key in APPEAR_KEYS else MISSING  # 보스바·전투 시간은 없을 수 있다
            out.seconds[key] = took
        sleep(rest)
    out.wall, out.cpu = clock() - wall0, cpu_clock() - cpu0
    return out


class Engine:
    """화면 스레드에서 상태만 다룬다(무거운 일은 밖의 작업 스레드). 모든 시각은 단조 시계(초)."""

    def __init__(self) -> None:
        self.generation = 0
        self.phase = "off"  # off | waiting_ui | initial | stable
        self.items = {k: Item(k) for k in KEYS}
        self.ui_retry_at = 0.0
        self.next_small = 0.0
        self.next_full = 0.0
        self.last_tick: float | None = None
        self.initial_summary = ""
        self.search_calls = 0  # 테스트·기록용(안정 상태에서 늘지 않아야 한다)

    # ---- 단계 -------------------------------------------------------------------------------
    def reset(self, now: float, phase: str = "waiting_ui") -> None:
        """게임 창 크기·재시작·지금 다시 찾기: 세대를 올리고 결과를 버린 뒤 처음 찾기부터(사용자 지정은 유지)."""
        self.generation += 1
        users = {k: it for k, it in self.items.items() if it.user}
        self.items = {k: users.get(k) or Item(k) for k in KEYS}
        self.phase = phase
        self.ui_retry_at = now
        self.next_small, self.next_full = now, now + APPEAR_FULL_EVERY
        self.last_tick = None

    def ui_not_ready(self, now: float) -> None:
        """로딩·로그인 화면: 처음 찾기를 미루고 10초 뒤 가벼운 확인만."""
        self.phase = "waiting_ui"
        self.ui_retry_at = now + UI_RETRY_SECONDS

    def ready_for_initial(self, now: float) -> bool:
        return self.phase == "waiting_ui" and now >= self.ui_retry_at

    def begin_initial(self) -> int:
        self.phase = "initial"
        self.search_calls += 1
        for it in self.items.values():
            if not it.user:
                it.status = SEARCHING
        return self.generation

    def finish_initial(self, generation: int, result: InitialResult, now: float) -> bool:
        """처음 찾기 결과 반영. 세대가 바뀌었으면(창 크기 변경 등) 버린다."""
        if generation != self.generation:
            return False
        for key in KEYS:
            it = self.items[key]
            if it.user:
                continue
            it.status = result.status.get(key, WAITING if key in APPEAR_KEYS else MISSING)
            it.box = result.boxes.get(key)
            it.source = result.source.get(key, "")
            it.seconds = result.seconds.get(key, 0.0)
            it.reason = "CPU 상한" if result.stopped_by_cap and it.status == MISSING and key not in result.seconds else ""
            it.lost, it.unhealthy, it.failures = 0.0, False, 0
            it.next_try = now + RETRY_SECONDS if it.status == MISSING else 0.0
        self.phase = "stable"
        self.next_small, self.next_full = now, now + APPEAR_FULL_EVERY
        counts = {s: sum(1 for it in self.items.values() if it.status == s) for s in (FOUND, WAITING, MISSING)}
        self.initial_summary = (f"처음 찾기 {result.wall:.1f}초(CPU {result.cpu:.1f}초) · 찾음 {counts[FOUND]} · "
                                f"대기 {counts[WAITING]} · 못 찾음 {counts[MISSING]}")
        return True

    # ---- 기능이 알려 주는 판독 결과 --------------------------------------------------------------
    def tick(self, now: float, running: bool) -> None:
        """0.5초쯤마다. 게임이 앞에 없으면 시간을 세지 않는다(못 읽은 시간·시험 시간 모두)."""
        dt = 0.0 if self.last_tick is None else min(1.0, max(0.0, now - self.last_tick))
        self.last_tick = now if running else None
        if not running:
            for it in self.items.values():
                if it.candidate is not None:
                    it.candidate.pause()
            return
        for it in self.items.values():
            if it.unhealthy and it.candidate is None:
                it.lost += dt

    def note_read(self, key: str, ok: bool, now: float, frame_id=None) -> str | None:
        """기능의 판독 한 번. 시험 중이면 확정 판단 — 'confirmed'/'failed'/None."""
        it = self.items.get(key)
        if it is None or self.phase == "off":
            return None
        if it.candidate is not None:
            if it.candidate.generation != self.generation:
                it.candidate = None
                return None
            if it.candidate.observe(frame_id=now if frame_id is None else frame_id, now=now, ok=ok):
                it.box, it.status, it.source = it.candidate.box, FOUND, "research"
                it.candidate = None
                it.lost, it.unhealthy, it.failures = 0.0, False, 0
                return "confirmed"
            if now - it.candidate.started > TRIAL_LIMIT:
                it.candidate = None
                self._failed(it, now, "새 자리에서 읽히지 않음")
                return "failed"
            return None
        if ok:
            it.lost, it.unhealthy, it.failures = 0.0, False, 0
            if it.status in (MISSING, WAITING) and it.box is not None:
                it.status = FOUND
        else:
            it.unhealthy = True
        return None

    def _failed(self, it: Item, now: float, reason: str) -> None:
        it.failures += 1
        it.reason = reason
        it.next_try = now + (SLOW_RETRY_SECONDS if it.failures >= SLOW_AFTER else RETRY_SECONDS)
        if it.status != FOUND or it.box is None:
            it.status = MISSING

    # ---- 다시 찾기 ---------------------------------------------------------------------------
    def due(self, now: float, wanted) -> list[str]:
        """다시 찾을 항목(켜진 기능만): 10초 넘게 못 읽음, 또는 처음에 못 찾음 — 다음 시도 시각이 됐을 때."""
        if self.phase != "stable":
            return []
        out = []
        for key, it in self.items.items():
            if key in APPEAR_KEYS or it.user or it.candidate is not None or not wanted(key) or now < it.next_try:
                continue
            if it.status == MISSING or (it.unhealthy and it.lost > LOST_SECONDS):
                out.append(key)
        return out

    def start_search(self, keys) -> int:
        self.search_calls += 1
        for k in keys:
            self.items[k].reason = ""
        return self.generation

    def search_result(self, generation: int, key: str, box, now: float) -> bool:
        """다시 찾기 결과. 찾으면 바로 쓰지 않고 시험(3초 연속 확정), 못 찾으면 실패 1회."""
        if generation != self.generation:
            return False
        it = self.items[key]
        if it.user:
            return False
        if box is None:
            self._failed(it, now, "화면에서 못 찾음")
            return True
        if it.box is not None and tuple(box) == tuple(it.box):
            # 같은 자리 — 위치는 그대로(잠깐 가려졌던 것). 시험 없이 기다린다.
            it.lost, it.unhealthy = 0.0, False
            self._failed(it, now, "같은 자리에서 읽히지 않음")
            return True
        it.candidate = Trial(tuple(box), generation, now)
        return True

    # ---- 나타나면 찾기 ------------------------------------------------------------------------
    def appear_due(self, now: float, wanted) -> tuple[list[str], str] | None:
        """대기 중인 켜진 보스바·전투 시간: 예상 자리 작게(1초 1번) 또는 화면 전체(60초 1번)."""
        if self.phase != "stable":
            return None
        keys = [k for k in APPEAR_KEYS if self.items[k].status in (WAITING, MISSING)
                and not self.items[k].user and wanted(k)]
        if not keys:
            return None
        if now >= self.next_full:
            self.next_full = now + APPEAR_FULL_EVERY
            self.next_small = now + APPEAR_SMALL_EVERY
            self.search_calls += 1
            return keys, "full"
        if now >= self.next_small:
            self.next_small = now + APPEAR_SMALL_EVERY
            return keys, "small"  # 작게 자른 확인은 '찾기 호출'로 세지 않는다(수 ms)
        return None

    def appear_result(self, generation: int, key: str, box) -> bool:
        if generation != self.generation or box is None:
            return False
        it = self.items[key]
        if it.user:
            return False
        it.box, it.status, it.source = tuple(box), FOUND, "appear"
        it.lost, it.unhealthy, it.failures = 0.0, False, 0
        return True

    # ---- 사용자 지정 ------------------------------------------------------------------------
    def user_override(self, key: str) -> None:
        """탭에서 직접 지정·자동 찾기 → 이번 실행 동안 v2가 그 항목을 덮지 않는다."""
        it = self.items.get(key)
        if it is not None:
            it.user, it.candidate = True, None

    # ---- 표시 ---------------------------------------------------------------------------------
    def region(self, key: str):
        it = self.items.get(key)
        if it is None or it.user:
            return None
        if it.candidate is not None:
            return it.candidate.box  # 확정 전엔 새 자리로 읽어 보기만
        return it.box if it.status == FOUND or (it.box is not None and it.unhealthy) else None

    def summary(self, now: float, wanted=lambda k: True) -> str:
        if self.phase == "off":
            return "꺼짐"
        if self.phase == "waiting_ui":
            return "게임 화면을 기다리는 중(로딩·로그인 화면이면 10초 뒤 다시 확인)"
        if self.phase == "initial":
            done = sum(1 for it in self.items.values() if it.status not in (SEARCHING, PENDING))
            return f"처음 찾는 중 · {done}/{len(KEYS)}"
        busy = [NAMES[k] for k, it in self.items.items() if it.candidate is not None]
        if busy:
            return f"다시 찾는 중({'·'.join(busy)})"
        return f"안정 · 찾기 끝 ({self.initial_summary.split(' · ')[0] if self.initial_summary else ''})"
