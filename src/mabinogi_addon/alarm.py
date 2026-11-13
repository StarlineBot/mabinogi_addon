"""알람(편의기능 › 알람, docs/alarm-spec.md) — 화면과 무관한 순수 로직.

- 시각 알람: HH:mm · 반복(한 번 / 매일 / 요일) · 이름 · 미리 알림(0/5/10분 전). 한 번짜리는 울린 뒤 꺼짐(지우지 않음).
- 타이머(몇 분 뒤): 끝나는 시각(벽시계 초). 울리면 목록에서 빠짐.
- 판정은 기존 0.25초 주기에서 `AlarmClock.check(now)`로 시각 비교만 한다(새 타이머 없음).
  지난번 확인 ~ 지금 사이에 지난 것만 울린다. 앱을 막 켰을 때는 '지금'부터라 꺼져 있던 동안의 알람은 울리지 않는다.
  절전 복귀 등으로 시각이 크게 건너뛰면 그사이 것 중 1분 안의 것만 울리고 나머지는 지난 것으로 둔다.
- 시각은 PC 시계(지역 시간) 기준.
"""
from __future__ import annotations

import datetime as _dt
import time as _time
import uuid
from dataclasses import dataclass, field

CATCH_UP_SEC = 60.0  # 시각이 건너뛰었을 때 바로 울릴 범위(1분 안)
REPEATS = ("once", "daily", "days")
PRE_CHOICES = (0, 5, 10)
TIMER_MAX_MIN = 600
DAY_NAMES = "월화수목금토일"
DEFAULT_TIME_NAME = "알람"
DEFAULT_TIMER_NAME = "타이머"


@dataclass
class Alarm:
    id: str
    kind: str  # "time" | "timer"
    name: str = ""
    enabled: bool = True
    hour: int = 0
    minute: int = 0
    repeat: str = "once"
    days: list[int] = field(default_factory=list)  # 0=월 … 6=일
    pre: int = 0  # 미리 알림(분)
    due: float | None = None  # 타이머 끝나는 시각(벽시계 초)
    minutes: int = 0  # 타이머 길이(분)

    @property
    def label(self) -> str:
        return self.name.strip() or (DEFAULT_TIMER_NAME if self.kind == "timer" else DEFAULT_TIME_NAME)

    def to_dict(self) -> dict:
        d = {"id": self.id, "kind": self.kind, "name": self.name, "enabled": self.enabled}
        if self.kind == "timer":
            d.update(due=self.due, minutes=self.minutes)
        else:
            d.update(hour=self.hour, minute=self.minute, repeat=self.repeat, days=list(self.days), pre=self.pre)
        return d

    @classmethod
    def from_dict(cls, d) -> "Alarm | None":
        if not isinstance(d, dict) or d.get("kind") not in ("time", "timer"):
            return None
        try:
            ident = str(d.get("id") or uuid.uuid4().hex[:12])
            name = str(d.get("name") or "")[:40]
            enabled = bool(d.get("enabled", True))
            if d["kind"] == "timer":
                due = float(d["due"])
                return cls(ident, "timer", name, enabled, due=due, minutes=int(d.get("minutes") or 0))
            hour, minute = int(d.get("hour")), int(d.get("minute"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            repeat = d.get("repeat") if d.get("repeat") in REPEATS else "once"
            days = sorted({int(x) for x in d.get("days") or [] if 0 <= int(x) <= 6})
            if repeat == "days" and not days:
                repeat = "daily"
            pre = int(d.get("pre") or 0)
            return cls(ident, "time", name, enabled, hour, minute, repeat, days, pre if pre in PRE_CHOICES else 0)
        except (KeyError, TypeError, ValueError):
            return None

    def repeat_text(self) -> str:
        if self.repeat == "daily":
            return "매일"
        if self.repeat == "days":
            return "매주 " + "·".join(DAY_NAMES[d] for d in self.days)
        return "한 번"

    def matches_day(self, date: _dt.date) -> bool:
        return self.repeat != "days" or date.weekday() in self.days


def new_time_alarm(hour: int, minute: int, *, name="", repeat="once", days=(), pre=0) -> Alarm:
    days = sorted(set(days))
    if repeat == "days" and not days:
        repeat = "daily"
    return Alarm(uuid.uuid4().hex[:12], "time", name.strip(), True, hour, minute, repeat, days,
                 pre if pre in PRE_CHOICES else 0)


def new_timer(minutes: int, now: float, *, name="") -> Alarm:
    minutes = max(1, min(TIMER_MAX_MIN, int(minutes)))
    return Alarm(uuid.uuid4().hex[:12], "timer", name.strip(), True, due=now + minutes * 60, minutes=minutes)


def _at(date: _dt.date, hour: int, minute: int) -> float:
    return _time.mktime(_dt.datetime(date.year, date.month, date.day, hour, minute).timetuple())


def _occurrences(alarm: Alarm, start: float, end: float, offset_min: int = 0):
    """(start, end] 안에 드는 울릴 시각(초). offset_min = 미리 알림 분(그만큼 앞)."""
    out = []
    first = _dt.date.fromtimestamp(start + offset_min * 60) - _dt.timedelta(days=1)
    last = _dt.date.fromtimestamp(end + offset_min * 60) + _dt.timedelta(days=1)
    day = first
    while day <= last:
        if alarm.matches_day(day):
            t = _at(day, alarm.hour, alarm.minute) - offset_min * 60
            if start < t <= end:
                out.append(t)
        day += _dt.timedelta(days=1)
    return out


def next_time(alarm: Alarm, now: float) -> float | None:
    """다음에 울릴 시각(초). 꺼졌으면 None."""
    if not alarm.enabled:
        return None
    if alarm.kind == "timer":
        return alarm.due
    today = _dt.date.fromtimestamp(now)
    for i in range(8):
        day = today + _dt.timedelta(days=i)
        if alarm.matches_day(day):
            t = _at(day, alarm.hour, alarm.minute)
            if t > now:
                return t
    return None


@dataclass(frozen=True)
class Fire:
    kind: str  # "time" | "pre" | "timer"
    alarm: Alarm
    at: float  # 울릴 예정이던 시각(초)
    target: float  # 알람 본 시각(미리 알림이면 본 시각, 아니면 at)


class AlarmClock:
    def __init__(self, alarms=()) -> None:
        self.alarms: list[Alarm] = list(alarms)
        self._last: float | None = None

    def start(self, now: float) -> None:
        """앱 시작: 지금부터 본다(꺼져 있던 동안의 것은 울리지 않음). 이미 지난 타이머는 지운다."""
        self._last = now
        self.alarms = [a for a in self.alarms if not (a.kind == "timer" and (a.due is None or a.due <= now))]

    def check(self, now: float) -> tuple[list[Fire], bool]:
        """(울릴 것, 목록이 바뀌었나). 지난번 확인~지금 사이, 단 1분 안의 것만."""
        if self._last is None:
            self.start(now)
            return [], False
        start = max(self._last, now - CATCH_UP_SEC)
        if now < self._last:  # 시계를 뒤로 돌림 → 기준만 옮긴다
            self._last = now
            return [], False
        self._last = now
        fires: list[Fire] = []
        changed = False
        for alarm in list(self.alarms):
            if alarm.kind == "timer":
                if alarm.due is not None and alarm.due <= now:
                    if alarm.enabled and alarm.due > start:
                        fires.append(Fire("timer", alarm, alarm.due, alarm.due))
                    self.alarms.remove(alarm)  # 울렸거나 건너뛴 타이머는 빠짐
                    changed = True
                continue
            if not alarm.enabled:
                continue
            if alarm.pre:
                for t in _occurrences(alarm, start, now, alarm.pre):
                    fires.append(Fire("pre", alarm, t, t + alarm.pre * 60))
            for t in _occurrences(alarm, start, now):
                fires.append(Fire("time", alarm, t, t))
                if alarm.repeat == "once":
                    alarm.enabled = False  # 한 번짜리: 울린 뒤 꺼짐(지우지 않음)
                    changed = True
        fires.sort(key=lambda f: f.at)
        return fires, changed

    def upcoming(self, now: float, limit: int = 3) -> list[tuple[float, Alarm]]:
        """가장 먼저 울릴 것부터(시각 알람은 본 시각, 미리 알림 제외)."""
        items = [(t, a) for a in self.alarms if (t := next_time(a, now)) is not None and t > now]
        items.sort(key=lambda x: x[0])
        return items[:limit]


# ---- 글자 ----
def clock_text(t: float) -> str:
    return _time.strftime("%H:%M", _time.localtime(t))


def remaining_text(seconds: float) -> str:
    """타이머 남은 시간 'M:SS' 또는 'H:MM:SS'."""
    s = max(0, int(seconds + 0.999))
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def status_text(clock: AlarmClock, now: float) -> str:
    """'다음 알람 20:30 길드전 · 타이머 12:34 남음'."""
    times = [(t, a) for t, a in clock.upcoming(now, 100) if a.kind == "time"]
    timers = [(t, a) for t, a in clock.upcoming(now, 100) if a.kind == "timer"]
    parts = []
    if times:
        t, a = times[0]
        parts.append(f"다음 알람 {clock_text(t)} {a.label}")
    if timers:
        t, a = timers[0]
        parts.append(f"타이머 {remaining_text(t - now)} 남음")
    return " · ".join(parts) if parts else "다가오는 알람 없음"


def notice_text(fire: Fire) -> str:
    """② 게임 위 알림·③ 토스트 문구."""
    a = fire.alarm
    if fire.kind == "timer":
        return f"{a.minutes}분 타이머 끝 · {a.label}"
    if fire.kind == "pre":
        return f"{a.pre}분 뒤 · {a.label}  {clock_text(fire.target)}"
    return f"{clock_text(fire.target)}  {a.label}"


def list_line(t: float, alarm: Alarm, now: float) -> tuple[str, str, str]:
    """게임 위 알람 목록 줄: (시각 글자, 이름, 색 종류 'time'|'timer'|'soon'). 1분 안은 빨강·초 단위."""
    left = t - now
    if left < 60:
        return f"{max(1, int(left + 0.999))}초 뒤", alarm.label, "soon"
    if alarm.kind == "timer":
        return f"{int(left // 60)}분 뒤", alarm.label, "timer"
    return clock_text(t), alarm.label, "time"


# ---- 시각 칸(0.48.0, 사용자 요청 11-14) ----
def parse_hhmm(text: str) -> tuple[int, int] | None:
    """'0745'·'745'·'7:45'·'07:45'(또는 '7'·'21' = 정각) → (7, 45). 잘못되면 None(2460·99 등)."""
    text = (text or "").strip().replace("：", ":")
    if ":" in text:
        head, _, tail = text.partition(":")
        if not (head.isdigit() and tail.isdigit()) or not 1 <= len(head) <= 2 or len(tail) != 2:
            return None
        hour, minute = int(head), int(tail)
    elif text.isdigit() and 1 <= len(text) <= 4:
        if len(text) <= 2:
            hour, minute = int(text), 0
        else:
            hour, minute = int(text[:-2]), int(text[-2:])
    else:
        return None
    return (hour, minute) if 0 <= hour <= 23 and 0 <= minute <= 59 else None


def default_time(now: float) -> tuple[int, int]:
    """지금 시각을 5분 단위로 올린 다음 시각(07:42 → 07:45, 07:45 → 07:50, 23:58 → 00:00)."""
    local = _time.localtime(now)
    total = (local.tm_hour * 60 + local.tm_min) // 5 * 5 + 5
    total %= 24 * 60
    return total // 60, total % 60
