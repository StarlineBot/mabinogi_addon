"""펫 동작 상태 머신(명세 2절 표) — Qt 없이 시각(초)·좌표만 받는다. 창(ui/pet_window.py)이 0.05초마다 tick.

좌표는 화면 논리 픽셀(Qt 좌표), pos = 발 밑 가운데. 키는 FIGURE_H(190, 화면 배율은 Qt 논리 픽셀이 이미 반영).

흐름
- 게임이 앞에 없으면(roam): 바닥(작업 표시줄 위)에서 서 있다가 가끔 걷는다.
- 게임이 앞이면(corner): 끌어서 정한 구석(없으면 바닥 오른쪽 끝)으로 걸어가 쪼그려 앉아 존다(졸림 ↔ 꾸벅 졸기(Zzz) ↔ 반쯤 뜸).
- 게임이 뒤로 가면 일어나 다시 돌아다닌다.
- 클릭: 서 있으면 놀람, 앉아 있으면 알아챔, 졸 때(Zzz)는 깜짝 깨어 일어남.
- 끌기: 끌려 다니기 → 놓으면 떨어져 착지 → 앉기 → 일어나기. 게임이 앞일 때 놓은 자리는 새 구석(저장).
- 쓰다듬기: 서 있을 때 머리 위를 좌우로 문지르면 알아챔 → 깜짝 → 부끄 → (문지르는 동안 반복) → 손 떼면 삐침.
- 알림: 앉아 있으면 알아챔, 서 있으면 알아챔(!) 한 번 + 말풍선.
- 말하기: 서 있을 때 말풍선이 뜨면 글자가 다 나올 때까지 분위기별 그림(보통=입 3단계·설명=손짓·생각=턱에 손·
  기쁨=웃음) → 말 끝 다묾 잠시 → 서 있기. 앉아 있으면 그림 그대로 말풍선만.
tick·입력은 사건 목록을 돌려준다: ("say", 상황) / ("say_text", 글) / ("click",) / ("pet_done",) /
("corner_saved", x, y) / ("corner_minute",) — 말풍선·호감도·저장은 창이 처리한다.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

FIGURE_H = 190
WALK_SPEED = 45.0          # 논리 px/초
GRAVITY = 1800.0           # 떨어질 때 px/초²
DRAG_START = 6.0           # 이만큼 움직이면 클릭이 아니라 끌기
FRONT_DELAY = 1.0          # 게임이 앞으로 온 뒤 이만큼 지나야 구석으로(잠깐 전환 무시)
BACK_DELAY = 1.5
RUB_REVERSALS = 2          # 머리 위에서 좌우로 이만큼 방향을 바꾸면 쓰다듬기
RUB_WINDOW = 1.5
RUB_STOP = 0.9             # 이만큼 안 문지르면 손 뗀 것
IDLE_LINE = (240.0, 480.0)  # 혼잣말 간격(초) — 몇 분에 한 번
LONG_HUNT = 7200.0         # 오래 사냥 중(앉아서 2시간마다)

# 동작 → (프레임, 한 장 시간(초)). loop=True면 반복
ANIMS: dict[str, tuple[tuple[str, ...], tuple[float, ...], bool]] = {
    "stand": (("stand_0",), (1.0,), True),
    "walk": (tuple(f"walk_{i}" for i in range(6)), (0.12,) * 6, True),
    "surprise": (("surprise_0", "surprise_1", "surprise_0", "surprise_1"), (0.22,) * 4, False),
    "drag": (tuple(f"drag_{i}" for i in range(4)), (0.18,) * 4, True),
    "fall": (("drag_0",), (1.0,), True),
    "land": (("land_0", "land_1", "land_2"), (0.2, 0.35, 0.6), False),
    "getup": (("getup_0", "getup_1", "getup_2"), (0.4, 0.3, 0.5), False),
    "pet_in": (("pet_0", "pet_1", "pet_2"), (0.45, 0.45, 0.5), False),
    "pet_loop": (("pet_3", "pet_4"), (0.45, 0.45), True),
    "pet_out": (("pet_5",), (1.6,), False),
    "alert": (("pet_0",), (1.5,), False),
    "crouch": (("crouch_0", "crouch_1", "crouch_2"), (0.25,) * 3, False),
    "sit_drowsy": (("sit_drowsy_0",), (5.0,), False),
    "sit_doze": (("sit_doze_0",), (8.0,), False),
    "sit_half": (("sit_half_0",), (2.5,), False),
    "sit_notice": (("sit_notice_0",), (1.6,), False),
    "rise": (("rise_0", "rise_1", "rise_2"), (0.25,) * 3, False),
    "wake": (("wake_0", "wake_1", "wake_2", "wake_3"), (0.3, 0.5, 0.3, 0.6), False),
    # 말하기(사용자 11-24): 글자가 나오는 동안 분위기별 그림 → 다 나오면 말 끝 다묾 잠시 → 서 있기
    "talk_normal": (("talk_small_0", "talk_big_0", "talk_small_0", "talk_closed_0"), (0.2,) * 4, True),
    "talk_explain": (("talk_hand_up_0", "talk_hand_out_0", "talk_point_0"), (0.22,) * 3, True),
    "talk_think": (("talk_think_0",), (1.0,), True),
    "talk_happy": (("talk_smile_0",), (1.0,), True),
    "talk_end": (("talk_end_0",), (0.7,), False),
}
TYPE_SECONDS = 0.07        # 말풍선 글자 한 자가 나오는 시간(창이 같은 값으로 한 글자씩 보여 줌)
TALKING = ("talk_normal", "talk_explain", "talk_think", "talk_happy", "talk_end")
SITTING = ("crouch", "sit_drowsy", "sit_doze", "sit_half", "sit_notice")
STANDING = ("stand", "walk")
UPRIGHT = STANDING + TALKING   # 서 있는 자세(클릭 놀람·쓰다듬기·알림 알아챔이 되는 상태)
# 한 번 도는 동작이 끝나면 다음 동작
_NEXT = {"surprise": "stand", "land": "getup", "getup": "stand", "pet_in": "pet_loop", "pet_out": "stand",
         "alert": "stand", "crouch": "sit_drowsy", "sit_drowsy": "sit_doze", "sit_doze": "sit_half",
         "sit_half": "sit_drowsy", "sit_notice": "sit_drowsy", "rise": "stand", "wake": "stand",
         "talk_end": "stand"}


@dataclass
class Floor:
    left: float
    right: float
    y: float          # 바닥(작업 표시줄 위 끝) — 발 밑 y

    def clamp_x(self, x: float, half: float = 150.0) -> float:  # 창 폭(300)의 절반 — 말풍선이 화면 밖으로 안 잘리게
        return max(self.left + half, min(self.right - half, x))


@dataclass
class Brain:
    floor: Floor
    corner: tuple[float, float] | None = None
    rng: random.Random = field(default_factory=random.Random)
    state: str = "stand"
    pos: tuple[float, float] = (0.0, 0.0)
    facing_left: bool = False
    _t0: float = 0.0                 # 지금 동작 시작 시각
    _last: float | None = None
    _target: tuple[float, float] | None = None
    _next_walk: float = 0.0
    _next_idle: float = 0.0
    _goal: str = "roam"              # roam / corner
    _front: bool = False
    _front_since: float = 0.0
    _press: tuple[float, float] | None = None
    _grab: tuple[float, float] = (0.0, 0.0)
    _dragging: bool = False
    _vy: float = 0.0
    _rub_x: float | None = None
    _rub_dir: int = 0
    _rub_turns: list = field(default_factory=list)
    _last_rub: float = 0.0
    _pet_reached_loop: bool = False
    _corner_time: float = 0.0
    _hunt_time: float = 0.0
    _speed: float = WALK_SPEED
    _talk_until: float = 0.0

    def __post_init__(self) -> None:
        if self.pos == (0.0, 0.0):
            self.pos = (self.floor.clamp_x((self.floor.left + self.floor.right) / 2), self.floor.y)

    # ---- 보이는 것 ----------------------------------------------------------------------------
    def frame(self, now: float) -> str:
        frames, times, loop = ANIMS[self.state]
        t = now - self._t0
        total = sum(times)
        if loop:
            t = t % total
        for name, d in zip(frames, times):
            if t < d:
                return name
            t -= d
        return frames[-1]

    def zzz(self) -> bool:
        """꾸벅 조는 동안만 Zzz(코드로 그림)."""
        return self.state == "sit_doze"

    def home(self) -> tuple[float, float]:
        if self.corner is not None:
            return self.corner
        return (self.floor.clamp_x(self.floor.right), self.floor.y)

    # ---- 내부 -------------------------------------------------------------------------------
    def _go(self, state: str, now: float) -> None:
        self.state, self._t0 = state, now
        if state == "pet_loop":
            self._pet_reached_loop = True

    def _done(self, now: float) -> bool:
        frames, times, loop = ANIMS[self.state]
        return not loop and now - self._t0 >= sum(times)

    def _walk_to(self, target: tuple[float, float], now: float) -> None:
        self._target = target
        self._speed = max(WALK_SPEED * 2.0, math.dist(self.pos, target) / 3.0)
        self.facing_left = target[0] < self.pos[0]
        self._go("walk", now)

    def _schedule_walk(self, now: float) -> None:
        self._next_walk = now + self.rng.uniform(3.0, 9.0)

    # ---- 시간 --------------------------------------------------------------------------------
    def tick(self, now: float, game_front: bool) -> list[tuple]:
        events: list[tuple] = []
        dt = 0.0 if self._last is None else max(0.0, min(0.5, now - self._last))
        self._last = now
        if self._next_idle == 0.0:
            self._next_idle = now + self.rng.uniform(*IDLE_LINE)
        if game_front != self._front:
            self._front, self._front_since = game_front, now
        if self._front and now - self._front_since >= FRONT_DELAY and self._goal != "corner":
            self._goal = "corner"
            self._hunt_time = 0.0
            if not self._dragging and self.state in STANDING:
                events.append(("say", "game_enter"))
                if self.state == "walk":  # 돌아다니던 걸음을 구석 쪽으로 바꿈(빠르기도 다시 정함)
                    self._walk_to(self.home(), now)
        elif not self._front and now - self._front_since >= BACK_DELAY and self._goal != "roam":
            self._goal = "roam"
            if self.state in SITTING:
                self._go("rise", now)
                events.append(("say", "game_exit"))
            self._schedule_walk(now)

        if self._dragging:
            return events
        if self.state == "fall":
            self._vy += GRAVITY * dt
            y = min(self.floor.y, self.pos[1] + self._vy * dt)
            self.pos = (self.pos[0], y)
            if y >= self.floor.y:
                self._go("land", now)
                events.append(("say", "dropped"))
            return events
        if self.state in TALKING and self.state != "talk_end" and now >= self._talk_until:
            self._go("talk_end", now)  # 글자가 다 나옴 → 입 다묾 잠시
        if self.state == "pet_loop" and now - self._last_rub > RUB_STOP:
            self._go("pet_out", now)
            events.append(("say", "pet_end"))
            events.append(("pet_done",))
            return events
        if self._done(now):
            nxt = _NEXT[self.state]
            if self.state == "getup" and self._goal == "corner" and self._near(self.home()):
                nxt = "crouch"  # 게임 중 구석에 놓였으면 그 자리에서 다시 앉는다
            self._go(nxt, now)
            if nxt == "stand":
                self._schedule_walk(now)
            elif nxt == "pet_loop":
                events.append(("say", "pet_during"))

        if self.state in SITTING and self._front:
            self._corner_time += dt
            self._hunt_time += dt
            if self._corner_time >= 60.0:  # 1분마다 — 호감도(30분마다 +1·퀘스트 누적 분)는 창 쪽에서
                self._corner_time -= 60.0
                events.append(("corner_minute",))
            if self._hunt_time >= LONG_HUNT and self.state != "sit_doze":
                self._hunt_time = 0.0
                events.append(("say", "long_hunt"))

        if self.state == "walk":
            self._step(dt, now)
        elif self.state == "stand":
            if self._goal == "corner":
                if self._near(self.home()):
                    self._go("crouch", now)
                else:
                    self._walk_to(self.home(), now)
            elif now >= self._next_walk:
                x = self.floor.clamp_x(self.rng.uniform(self.floor.left, self.floor.right))
                self._walk_to((x, self.floor.y), now)

        if now >= self._next_idle:
            self._next_idle = now + self.rng.uniform(*IDLE_LINE)
            if self.state in ("stand", "walk", "sit_drowsy", "sit_half"):
                events.append(("say", "idle"))
        return events

    def _near(self, point: tuple[float, float]) -> bool:
        return math.dist(self.pos, point) < 2.0

    def _step(self, dt: float, now: float) -> None:
        if self._goal == "corner":
            self._target = self.home()
        target = self._target or self.pos
        dx, dy = target[0] - self.pos[0], target[1] - self.pos[1]
        dist = math.hypot(dx, dy)
        # 게임에 들어가면 서둘러 구석으로 — 멀어도 약 3초 안에 닿게(출발할 때 정한 빠르기)
        speed = self._speed if self._goal == "corner" else WALK_SPEED
        if dist <= speed * dt or dist < 1.0:
            self.pos = target
            self._target = None
            if self._goal == "corner" and self._near(self.home()):
                self._go("crouch", now)
            else:
                self._go("stand", now)
                self._schedule_walk(now)
            return
        if abs(dx) > 0.5:
            self.facing_left = dx < 0
        self.pos = (self.pos[0] + dx / dist * speed * dt, self.pos[1] + dy / dist * speed * dt)

    # ---- 마우스 ------------------------------------------------------------------------------
    def press(self, now: float, x: float, y: float) -> None:
        """캐릭터 위에서 눌렀다(화면 좌표)."""
        self._press = (x, y)
        self._grab = (x - self.pos[0], y - self.pos[1])

    def move(self, now: float, x: float, y: float) -> list[tuple]:
        if self._press is None:
            return []
        events: list[tuple] = []
        if not self._dragging and math.dist(self._press, (x, y)) >= DRAG_START:
            self._dragging = True
            self._go("drag", now)
            if self.rng.random() < 0.5:
                events.append(("say", "drag"))
        if self._dragging:
            self.pos = (x - self._grab[0], y - self._grab[1])
        return events

    def release(self, now: float) -> list[tuple]:
        if self._press is None:
            return []
        self._press = None
        events: list[tuple] = []
        if self._dragging:
            self._dragging = False
            self._target = None
            if self._front:  # 게임 중 놓은 자리 = 새 구석(저장)
                self.corner = self.pos
                events.append(("corner_saved", *self.pos))
                self._goal = "corner"
                self._go("land", now)
            elif self.pos[1] < self.floor.y - 1:
                self._vy = 0.0
                self._go("fall", now)
            else:
                self.pos = (self.pos[0], self.floor.y)
                self._go("land", now)
                events.append(("say", "dropped"))
            return events
        events.append(("click",))
        if self.state in UPRIGHT:
            self._target = None
            self._go("surprise", now)
            events.append(("say", "click_stand"))
        elif self.state == "sit_doze":
            self._go("wake", now)
            events.append(("say", "click_sleep"))
        elif self.state in SITTING:
            self._go("sit_notice", now)
            events.append(("say", "click_sit"))
        return events

    def hover(self, now: float, x: float, on_head: bool) -> list[tuple]:
        """누르지 않은 채 캐릭터 위를 움직임. 머리 위를 좌우로 문지르면 쓰다듬기."""
        if self._press is not None or not on_head:
            self._rub_x = None
            return []
        if self.state in ("pet_in", "pet_loop"):
            self._last_rub = now
            return []
        if self.state not in UPRIGHT:
            return []
        if self._rub_x is not None:
            d = x - self._rub_x
            if abs(d) >= 3:
                direction = 1 if d > 0 else -1
                if self._rub_dir and direction != self._rub_dir:
                    self._rub_turns = [t for t in self._rub_turns if now - t <= RUB_WINDOW] + [now]
                self._rub_dir = direction
                self._rub_x = x
        else:
            self._rub_x, self._rub_dir = x, 0
        if len(self._rub_turns) >= RUB_REVERSALS:
            self._rub_turns = []
            self._target = None
            self._pet_reached_loop = False
            self._last_rub = now
            self._go("pet_in", now)
            return [("say", "pet_start")]
        return []

    def notify(self, now: float) -> None:
        """목소리 알림 — 앉아 있으면 알아챔, 서 있으면 알아챔(!) 한 번(말풍선은 창이 띄움)."""
        if self.state in SITTING:
            self._go("sit_notice", now)
        elif self.state in UPRIGHT:
            self._target = None
            self._go("alert", now)

    def talk(self, now: float, chars: int, mood: str = "normal") -> bool:
        """말풍선이 뜸 — 서 있으면(걷던 중이면 멈추고) 말하기: 글자가 다 나올 때까지 분위기별 그림.
        앉아 있거나 다른 동작 중이면 그림은 그대로(말풍선만). 말하기로 바꿨으면 True."""
        if self.state not in UPRIGHT or self._dragging:
            return False
        self._target = None
        self._talk_until = now + max(0.6, chars * TYPE_SECONDS)
        self._go(f"talk_{mood}" if f"talk_{mood}" in ANIMS else "talk_normal", now)
        return True

    def dragging(self) -> bool:
        return self._dragging
