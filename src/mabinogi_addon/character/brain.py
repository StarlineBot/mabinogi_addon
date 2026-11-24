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
WALK_SPEED = 45.0          # 논리 px/초(캐릭터 값이 없을 때)
# 캐릭터별 걷기(사용자 11-24 '걷기가 미끄러짐'): 속도 = 걷기 그림 한 바퀴 이동 거리 / 한 바퀴 시간이 되게.
# 한 바퀴 거리는 걷기 6장의 발 간격(접지 때 가장 넓은 폭 − 가장 좁은 폭, 190px 기준) × 2로 잼(11-24):
#   다래 48.7 → 97px, 아리아 60.0 → 120px, 이안 39.3 → 79px(기획 시안 약 90px).
DARE_WALK_FRAME, DARE_WALK_SPEED = 0.20, 80.0    # 한 바퀴 1.2초 × 80 = 96px
ARIA_WALK_FRAME, ARIA_WALK_SPEED = 0.22, 90.0    # 1.32초 × 90 = 119px
IAN_WALK_FRAME, IAN_WALK_SPEED = 0.20, 75.0      # 기획 지정(시안) 1.2초 × 75 = 90px
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
    "walk": (tuple(f"walk_{i}" for i in range(6)), (DARE_WALK_FRAME,) * 6, True),
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
STANDING = ("stand", "walk", "hairstroke", "watch")   # 서서 대기 동작(아리아 머리 쓰다듬기·이안 시계 보기)도 서 있는 것
UPRIGHT = STANDING + TALKING   # 서 있는 자세(클릭 놀람·쓰다듬기·알림 알아챔이 되는 상태)
# 한 번 도는 동작이 끝나면 다음 동작
_NEXT = {"surprise": "stand", "land": "getup", "getup": "stand", "pet_in": "pet_loop", "pet_out": "stand",
         "alert": "stand", "crouch": "sit_drowsy", "sit_drowsy": "sit_doze", "sit_doze": "sit_half",
         "sit_half": "sit_drowsy", "sit_notice": "sit_drowsy", "rise": "stand", "wake": "stand",
         "talk_end": "stand"}


@dataclass(frozen=True)
class Profile:
    """캐릭터마다 다른 것 — 그림(동작 → 프레임), 다음 동작, 앉은 상태들, 졸기 유무, 서서 대기 동작(아리아 머리 쓰다듬기)."""
    anims: dict
    next_map: dict
    sitting: tuple[str, ...]
    sit_state: str                        # 쪼그려 앉은 뒤 들어가는 앉아 있기 상태
    doze_state: str | None = None         # Zzz를 그리고 클릭하면 깜짝 깨는 상태(없으면 졸지 않음)
    idle_extra: str | None = None         # 가만히 서 있는 동안 가끔 하는 동작(서 있기와 번갈아)
    idle_gap: tuple[float, float] = (8.0, 15.0)   # 그 동작 사이 간격(초, 무작위)
    idle_laps: tuple[int, int] = (1, 2)            # 한 번에 몇 바퀴
    talk_after_surprise: bool = False     # 클릭 반응(짧은 그림) 뒤 말풍선이 아직 나오는 중이면 말하기로 이어감(이안)
    walk_speed: float = WALK_SPEED        # 걷는 빠르기(논리 px/초) — 걷기 그림 한 바퀴 거리에 맞춤

    def with_timing(self, raw) -> Profile:
        """설정 값(config character.idle {gap: [최소, 최대], laps: [최소, 최대]})으로 대기 동작 시간 덮어쓰기."""
        from dataclasses import replace

        def pair(value, kind, low):
            if (isinstance(value, list) and len(value) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= low for v in value)
                    and value[0] <= value[1]):
                return (kind(value[0]), kind(value[1]))
            return None
        if not isinstance(raw, dict):
            return self
        gap, laps = pair(raw.get("gap"), float, 1.0), pair(raw.get("laps"), int, 1)
        return replace(self, idle_gap=gap or self.idle_gap, idle_laps=laps or self.idle_laps)


DARE = Profile(ANIMS, _NEXT, SITTING, "sit_drowsy", doze_state="sit_doze", walk_speed=DARE_WALK_SPEED)

# 아리아(docs/characters/아리아.md): 졸기·자다 깨기 없음 — 구석에서 머리를 안고 앉아 웃음(0 길게 → 3 → 0 → 1 → 2 → 0),
# 앉아서 클릭 = 웃음 프레임. 서 있기 두 자세 번갈아 + 가만히 서 있는 동안 가끔 머리 쓰다듬기(사용자 11-24).
ARIA_ANIMS = {
    "stand": (("stand_0", "stand_1"), (2.2, 2.2), True),
    "walk": (tuple(f"walk_{i}" for i in range(6)), (ARIA_WALK_FRAME,) * 6, True),
    "surprise": (tuple(f"surprise_{i}" for i in range(4)), (0.22,) * 4, False),
    "drag": (("drag_0", "drag_1"), (0.25, 0.25), True),
    "fall": (("drag_1",), (1.0,), True),
    "land": (("land_0", "land_1", "land_2"), (0.2, 0.35, 0.6), False),
    "getup": (("getup_0", "getup_1", "getup_2"), (0.4, 0.3, 0.5), False),
    "pet_in": (("pet_0", "pet_1"), (0.45, 0.45), False),
    "pet_loop": (("pet_2", "pet_3", "pet_4"), (0.45,) * 3, True),
    "pet_out": (("pet_5",), (1.6,), False),
    "alert": (("pet_0",), (1.5,), False),
    "crouch": (("crouch_0", "crouch_1", "crouch_2"), (0.25,) * 3, False),
    "sit_loop": (("sit_0", "sit_3", "sit_0", "sit_1", "sit_2", "sit_0"), (3.0, 0.6, 1.5, 0.8, 0.8, 1.5), True),
    "sit_notice": (("sit_1",), (1.6,), False),
    "rise": (("rise_0", "rise_1", "rise_2"), (0.25,) * 3, False),
    "hairstroke": (("hair_0", "hair_1", "hair_2", "hair_3"), (0.9, 0.33, 0.33, 0.34), True),
    "talk_normal": (("talk_small_0", "talk_big_0", "talk_small_0", "talk_closed_0"), (0.2,) * 4, True),
    "talk_explain": (tuple(f"talk_hand_{i}" for i in range(6)) + ("talk_point_0", "talk_point_1"),
                     (0.2,) * 6 + (0.4, 0.4), True),
    "talk_happy": (("talk_happy_0", "talk_happy_1", "talk_laugh_0"), (0.3,) * 3, True),
    "talk_end": (("talk_end_0",), (0.7,), False),
}
ARIA = Profile(ARIA_ANIMS,
               {"surprise": "stand", "land": "getup", "getup": "stand", "pet_in": "pet_loop", "pet_out": "stand",
                "alert": "stand", "crouch": "sit_loop", "sit_notice": "sit_loop", "rise": "stand", "talk_end": "stand"},
               ("crouch", "sit_loop", "sit_notice"), "sit_loop", idle_extra="hairstroke",
               walk_speed=ARIA_WALK_SPEED)
# 이안(docs/characters/이안.md): 졸기 없음·놀람 그림 없음(서서 클릭 = 쓰다듬기 첫 장 0.5초 → 말하기),
# 서 있기 ↔ 시계 보기 번갈아, 떨어지면 두 발 착지 → 바로 서기(엉덩방아·일어나기 없음), 알림 = 시계 가리키며 말함.
IAN_ANIMS = {
    "stand": (("stand_1",), (1.0,), True),
    "walk": (tuple(f"walk_{i}" for i in range(6)), (IAN_WALK_FRAME,) * 6, True),
    "surprise": (("pet_0",), (0.5,), False),
    "drag": (tuple(f"drag_{i}" for i in range(4)), (0.18,) * 4, True),
    "fall": (("fall_0",), (1.0,), True),  # 사용자 11-24: 두 장을 번갈면 두근거려 보여 한 장만
    "land": (("land_0", "land_1", "land_2"), (0.2, 0.3, 0.4), False),
    "pet_in": (("pet_0", "pet_1"), (0.45, 0.45), False),
    "pet_loop": (("pet_2", "pet_3", "pet_4"), (0.45,) * 3, True),
    "pet_out": (("pet_5",), (1.6,), False),
    "alert": (tuple(f"talk_alert_{i}" for i in range(6)), (0.3,) * 6, False),
    "crouch": (("crouch_0", "crouch_1", "crouch_2"), (0.25,) * 3, False),
    "sit_loop": (("sit_0", "sit_1", "sit_2", "sit_3"), (3.0, 0.8, 0.8, 0.8), True),
    "sit_notice": (("sit_0",), (1.2,), False),
    "rise": (("rise_0", "rise_1", "rise_2"), (0.25,) * 3, False),
    "watch": (("watch_0", "watch_1", "watch_2", "watch_3"), (0.25, 0.25, 1.0, 0.25), True),
    "talk_normal": (("stand_0", "stand_1"), (0.2, 0.2), True),
    "talk_explain": (("talk_point_0", "talk_point_1"), (0.4, 0.4), True),
    "talk_end": (("stand_1",), (0.5,), False),
}
IAN = Profile(IAN_ANIMS,
              {"surprise": "stand", "land": "stand", "pet_in": "pet_loop", "pet_out": "stand", "alert": "stand",
               "crouch": "sit_loop", "sit_notice": "sit_loop", "rise": "stand", "talk_end": "stand"},
              ("crouch", "sit_loop", "sit_notice"), "sit_loop", idle_extra="watch", idle_laps=(1, 1),
              talk_after_surprise=True, walk_speed=IAN_WALK_SPEED)
PROFILES = {"다래": DARE, "아리아": ARIA, "이안": IAN}


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
    profile: Profile = DARE
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
    _walk_rate: float = 1.0
    _talk_until: float = 0.0
    _next_extra: float = 0.0
    _extra_until: float = 0.0
    _queued_talk: tuple | None = None

    def __post_init__(self) -> None:
        if self.pos == (0.0, 0.0):
            self.pos = (self.floor.clamp_x((self.floor.left + self.floor.right) / 2), self.floor.y)

    # ---- 보이는 것 ----------------------------------------------------------------------------
    def frame(self, now: float) -> str:
        frames, times, loop = self.profile.anims[self.state]
        t = now - self._t0
        if self.state == "walk":
            t *= self._walk_rate
        total = sum(times)
        if loop:
            t = t % total
        for name, d in zip(frames, times):
            if t < d:
                return name
            t -= d
        return frames[-1]

    def zzz(self) -> bool:
        """꾸벅 조는 동안만 Zzz(코드로 그림). 졸지 않는 캐릭터는 없음."""
        return self.profile.doze_state is not None and self.state == self.profile.doze_state

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
        frames, times, loop = self.profile.anims[self.state]
        return not loop and now - self._t0 >= sum(times)

    def _walk_to(self, target: tuple[float, float], now: float) -> None:
        self._target = target
        self._speed = max(self.profile.walk_speed * 2.0, math.dist(self.pos, target) / 3.0)
        self.facing_left = target[0] < self.pos[0]
        self._go("walk", now)

    def _schedule_walk(self, now: float) -> None:
        self._next_walk = now + self.rng.uniform(3.0, 9.0)

    def _schedule_extra(self, now: float) -> None:
        """서서 대기 동작(아리아 머리 쓰다듬기) 다음 차례 — 8~15초 뒤 무작위(설정 값)."""
        if self.profile.idle_extra:
            self._next_extra = now + self.rng.uniform(*self.profile.idle_gap)

    # ---- 시간 --------------------------------------------------------------------------------
    def tick(self, now: float, game_front: bool) -> list[tuple]:
        events: list[tuple] = []
        dt = 0.0 if self._last is None else max(0.0, min(0.5, now - self._last))
        self._last = now
        if self._next_idle == 0.0:
            self._next_idle = now + self.rng.uniform(*IDLE_LINE)
            self._schedule_extra(now)
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
            if self.state in self.profile.sitting:
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
        if self.profile.idle_extra and self.state == self.profile.idle_extra and now >= self._extra_until:
            self._go("stand", now)  # 대기 동작(머리 쓰다듬기·시계 보기) 끝 → 서 있기
            self._schedule_extra(now)
        if self.state == "pet_loop" and now - self._last_rub > RUB_STOP:
            self._go("pet_out", now)
            events.append(("say", "pet_end"))
            events.append(("pet_done",))
            return events
        if self._done(now):
            nxt = self.profile.next_map[self.state]
            queued, self._queued_talk = self._queued_talk, None
            if self.state == "surprise" and queued is not None and now < queued[0]:
                mood = queued[1]
                nxt = f"talk_{mood}" if f"talk_{mood}" in self.profile.anims else "talk_normal"
                self._talk_until = queued[0]
            if self.state == "getup" and self._goal == "corner" and self._near(self.home()):
                nxt = "crouch"  # 게임 중 구석에 놓였으면 그 자리에서 다시 앉는다
            self._go(nxt, now)
            if nxt == "stand":
                self._schedule_walk(now)
                self._schedule_extra(now)
            elif nxt == "pet_loop":
                events.append(("say", "pet_during"))

        if self.state in self.profile.sitting and self._front:
            self._corner_time += dt
            self._hunt_time += dt
            if self._corner_time >= 60.0:  # 1분마다 — 호감도(30분마다 +1·퀘스트 누적 분)는 창 쪽에서
                self._corner_time -= 60.0
                events.append(("corner_minute",))
            if self._hunt_time >= LONG_HUNT and self.state != self.profile.doze_state:
                self._hunt_time = 0.0
                events.append(("say", "long_hunt"))

        if self.state == "walk":
            self._step(dt, now)
        elif self.state == "stand" or self.state == self.profile.idle_extra:  # 대기 동작 중이어도 걸을 차례·게임이 오면 바로 끊음
            if self._goal == "corner":
                if self._near(self.home()):
                    self._go("crouch", now)
                else:
                    self._walk_to(self.home(), now)
            elif now >= self._next_walk:
                x = self.floor.clamp_x(self.rng.uniform(self.floor.left, self.floor.right))
                self._walk_to((x, self.floor.y), now)
            elif self.state == "stand" and self.profile.idle_extra and now >= self._next_extra > 0:
                laps = self.rng.randint(*self.profile.idle_laps)
                _frames, times, _loop = self.profile.anims[self.profile.idle_extra]
                self._extra_until = now + laps * sum(times)
                self._go(self.profile.idle_extra, now)

        if now >= self._next_idle:
            self._next_idle = now + self.rng.uniform(*IDLE_LINE)
            quiet = self.state in self.profile.sitting and self.state not in (
                "crouch", "sit_notice", self.profile.doze_state)
            if self.state in STANDING or quiet:
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
        speed = self._speed if self._goal == "corner" else self.profile.walk_speed
        self._walk_rate = speed / self.profile.walk_speed  # 빨리 걸을 땐 걸음 그림도 그만큼 빨리(미끄러짐 줄임)
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
            stroking = self.profile.idle_extra is not None and self.state == self.profile.idle_extra
            self._target = None
            self._go("surprise", now)
            self._schedule_extra(now)
            events.append(("say", "idle_extra_click" if stroking else "click_stand"))
        elif self.profile.doze_state is not None and self.state == self.profile.doze_state:
            self._go("wake", now)
            events.append(("say", "click_sleep"))
        elif self.state in self.profile.sitting:
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
        if self.state in self.profile.sitting:
            self._go("sit_notice", now)
        elif self.state in UPRIGHT:
            self._target = None
            self._go("alert", now)

    def talk(self, now: float, chars: int, mood: str = "normal") -> bool:
        """말풍선이 뜸 — 서 있으면(걷던 중이면 멈추고) 말하기: 글자가 다 나올 때까지 분위기별 그림.
        앉아 있거나 다른 동작 중이면 그림은 그대로(말풍선만). 말하기로 바꿨으면 True."""
        if self.state == "surprise" and self.profile.talk_after_surprise and not self._dragging:
            self._queued_talk = (now + max(0.6, chars * TYPE_SECONDS), mood)  # 클릭 반응이 끝나면 이어서 말함
            return False
        if self.state not in UPRIGHT or self._dragging:
            return False
        self._target = None
        self._talk_until = now + max(0.6, chars * TYPE_SECONDS)
        # 그 분위기 그림이 없는 캐릭터(아리아 '생각')는 보통으로
        self._go(f"talk_{mood}" if f"talk_{mood}" in self.profile.anims else "talk_normal", now)
        return True

    def hold_talk(self, until: float) -> None:
        """대사 목소리가 글자보다 길면 말하기 그림을 소리 끝까지 유지(입 움직임). 짧으면 글자 기준 그대로."""
        if self.state in TALKING and self.state != "talk_end":
            self._talk_until = max(self._talk_until, until)

    def dragging(self) -> bool:
        return self._dragging
