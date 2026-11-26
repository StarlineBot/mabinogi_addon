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

from . import floor_space

FIGURE_H = 190
WALK_SPEED = 45.0          # 논리 px/초(캐릭터 값이 없을 때)
# 캐릭터별 걷기(사용자 11-24 '걷기가 미끄러짐'): 속도 = 걷기 그림 한 바퀴 이동 거리 / 한 바퀴 시간이 되게.
# 한 바퀴 거리는 걷기 6장의 발 간격(접지 때 가장 넓은 폭 − 가장 좁은 폭, 190px 기준) × 2로 잼(11-24):
#   다래 48.7 → 97px, 아리아 60.0 → 120px, 이안 v2(11-24 다시 그림) 33.3 → 67px, 레나 60.0 → 120px.
# 걷기 8장(11-26): 한 바퀴 시간(다래 1.2초·나머지 1.32초)과 빠르기는 그대로, 장 수만 6 → 8
DARE_WALK_FRAME, DARE_WALK_SPEED = 0.15, 100.0   # 새 걷기 시트(11-25) 디딘 발이 장마다 약 31px(예전 25px — 80) → 100
ARIA_WALK_FRAME, ARIA_WALK_SPEED = 0.165, 90.0    # 1.32초 × 90 = 119px
IAN_WALK_FRAME, IAN_WALK_SPEED = 0.15, 66.0      # v3 걷기 8장(11-25) 1.2초 × 66 = 79px — 디딘 발이 한 바퀴에 원본 약 120px(그리기 80px)
# 캐릭터별 그리기 배율(사용자 11-24 B안 — 눈 사이 간격 Starline 45·이안 47·다래·아리아 53·레나 57로 얼굴이 달라 보임).
# 그림이 커지면 보폭도 커져 걷기 속도도 같은 배율(발 미끄러짐 방지).
STARLINE_SCALE, LENA_SCALE = 1.15, 0.95
LENA_WALK_FRAME, LENA_WALK_SPEED = 0.165, round(90.0 * LENA_SCALE, 1)    # 발 간격 60.0 → 120px(×0.95 = 114px), 1.32초 × 85.5
STARLINE_WALK_FRAME, STARLINE_WALK_SPEED = 0.165, round(65.0 * STARLINE_SCALE, 1)  # 발끝 간격 → 약 85px(×1.15 = 98px), 1.32초 × 74.8
GRAVITY = 1800.0           # 떨어질 때 px/초²
DRAG_START = 6.0           # 이만큼 움직이면 클릭이 아니라 끌기
FRONT_DELAY = 1.0          # 게임이 앞으로 온 뒤 이만큼 지나야 구석으로(잠깐 전환 무시)
BACK_DELAY = 1.5
# 쓰다듬기 시작(사용자 11-24 '마우스만 지나가도 쓰다듬는 모션 — 최소 2번 이상 흔들어야'): 머리 위에서 한 방향으로
# RUB_MIN 이상 움직인 뒤 돌아설 때만 전환 1번(손 떨림 무시), 전환 RUB_REVERSALS번(좌→우→좌→우 = 왕복 2번)이 RUB_WINDOW 안
RUB_MIN = 20.0             # 논리 px(펫 키 190 기준)
RUB_REVERSALS = 3
RUB_WINDOW = 2.0
RUB_STOP = 0.9             # 이만큼 안 문지르면 손 뗀 것
IDLE_LINE = (240.0, 480.0)  # 혼잣말 간격(초) — 몇 분에 한 번
# 드문 기본 동작(기획 11-25 — 아리아 기지개·레나 마법 펑·Starline 재채기): 게임 밖 서 있기에서만 3~6분에 한 번, 1바퀴.
# 혼잣말·대기 동작과 겹치면 다음 차례로 미룸. 숫자는 설정(character.idle.rareGap)으로 바꿀 수 있음
RARE_GAP = (180.0, 360.0)
RARE_DEFER = 30.0          # 혼잣말이 곧 나올 차례면 이만큼 미룸
# 다래 엎드려 자기(기획 11-25 정정 — '구석에서는 자주 보이게'): 구석에 앉아 있는 동안 3~6분에 한 번 엎드려
# 20~40초 숨쉬다 다시 앉음(설정 character.idle.sleepGap·sleepHold)
SLEEP_GAP = (180.0, 360.0)
SLEEP_HOLD = (20.0, 40.0)
SLEEPING = ("sleep_down", "sleep_loop", "sleep_up")
LONG_HUNT = 7200.0         # 오래 사냥 중(앉아서 2시간마다)

# 동작 → (프레임, 한 장 시간(초)). loop=True면 반복
ANIMS: dict[str, tuple[tuple[str, ...], tuple[float, ...], bool]] = {
    "stand": (("stand_0",), (1.0,), True),
    "walk": (tuple(f"walk_{i}" for i in range(8)), (DARE_WALK_FRAME,) * 8, True),   # GPT 워크 8장(11-26 — 양발·팔 번갈아)
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
    # 엎드려 자기(기획 11-25): 0 무릎 안고 졺 → 1 기울어짐 → 2 엎드림 → 3·4·5 숨쉬기 반복 → (게임 끝) 6 눈 비빔 → 7 하품 → 8 앉음
    "sleep_down": (("sleep_0", "sleep_1", "sleep_2"), (0.8, 0.7, 0.8), False),
    "sleep_loop": (("sleep_3", "sleep_4", "sleep_5", "sleep_4"), (1.3, 1.0, 1.3, 1.0), True),
    "sleep_up": (("sleep_6", "sleep_7", "sleep_8"), (0.8, 1.0, 0.8), False),
    "sit_half": (("sit_half_0",), (2.5,), False),
    "sit_notice": (("sit_notice_0",), (1.6,), False),
    "rise": (("rise_0", "rise_1", "rise_2"), (0.25,) * 3, False),
    "wake": (("wake_0", "wake_1", "wake_2", "wake_3"), (0.3, 0.5, 0.3, 0.6), False),
    # 말하기(사용자 11-24): 글자가 나오는 동안 분위기별 그림 → 다 나오면 말 끝 다묾 잠시 → 서 있기
    "talk_think": (("talk_think_0",), (1.0,), True),     # 생각·기쁨은 예전 그림 그대로(사용자 11-24)
    "talk_happy": (("talk_smile_0",), (1.0,), True),
}
TYPE_SECONDS = 0.07        # 말풍선 글자 한 자가 나오는 시간(창이 같은 값으로 한 글자씩 보여 줌)
TALKING = ("talk", "talk_think", "talk_happy", "talk_end")
# 새 말하기(사용자 11-24 '말할 때 모션이 어색' — docs/character-pet-spec.md '말하기 모션 어색함'):
# 서 있기 → 사이(0.2초) → 입만 바꾸기(m1·m2·m1·base 0.2초씩, m2 때 1px 끄덕임) → 강조(한 문장 최대 1번) → base → 사이 → 서 있기.
# 그림은 늘 바로 바뀜(예전 덮기 전환은 포즈가 다른 두 그림이 겹쳐 잔상 — 사용자 11-24, QA ghost_survey로 없앰).
TALK_KEYS = ("base", "m1", "m2", "emph", "emph2", "blink", "mid")
MID_SECONDS = 0.2
MOUTH_SECONDS = 0.2
MOUTH_ORDER = ("m1", "m2", "m1", "base")
EMPH_SECONDS = (0.4, 0.2)   # 강조 손짓 → 완화
EMPH_MIN_CHARS = 12
BLINK_SECONDS = 0.13
BLINK_GAP = (3.0, 5.0)
END_BASE_SECONDS = 0.3
END_STEP_SECONDS = 0.2      # 말 끝 두 장(레나 end1·end2) 한 장 시간
SHAKE_SECONDS = 0.13        # 참는 중 좌우 1px 떨림 한 칸(레나)


def talk_set(prefix: str = "talk_") -> dict[str, str]:
    """말하기 한 벌(빌드 build_talk_frames의 이름) — base·m1·m2·emph·emph2·blink·mid."""
    return {key: f"{prefix}{key}_0" for key in TALK_KEYS}


def _end_steps(s: dict) -> tuple[tuple[str, float], ...]:
    """말 끝 시간표 — base 잠시 → 사이(기본) 또는 끝 두 장(레나 end1 → end2, 서기와 같은 자세)."""
    if "end1" in s:
        return (("base", END_BASE_SECONDS), ("end1", END_STEP_SECONDS), ("end2", END_STEP_SECONDS))
    return (("base", END_BASE_SECONDS), ("mid", MID_SECONDS))


def _talk_anims(sets) -> dict:
    """load_frames가 말하기 그림을 모두 읽게 하는 자리(재생은 Brain._talk_frame이 시간표로)."""
    names = tuple(name for s in sets for name in s.values())
    steps = [(s[k], d) for s in sets for k, d in _end_steps(s)]
    return {"talk": (names, (1.0,) * len(names), True),
            "talk_end": (tuple(n for n, _ in steps), tuple(d for _, d in steps), False)}


DARE_TALK = (talk_set(),)
ANIMS.update(_talk_anims(DARE_TALK))
SITTING = ("crouch", "sit_drowsy", "sit_doze", "sit_half", "sit_notice") + SLEEPING
STANDING = ("stand", "walk", "hairstroke", "watch", "flame", "stretch", "magic", "sneeze", "motion")   # 서서 대기 동작(아리아 머리 쓰다듬기·이안 시계 보기)도 서 있는 것
UPRIGHT = STANDING + TALKING   # 서 있는 자세(클릭 놀람·쓰다듬기·알림 알아챔이 되는 상태)
# 한 번 도는 동작이 끝나면 다음 동작
_NEXT = {"surprise": "stand", "land": "getup", "getup": "stand", "pet_in": "pet_loop", "pet_out": "stand",
         "alert": "stand", "crouch": "sit_drowsy", "sit_drowsy": "sit_doze", "sit_doze": "sit_half",
         "sleep_down": "sleep_loop", "sleep_up": "rise",
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
    talk_after_surprise: bool = False     # 클릭 반응(짧은 그림) 뒤 말풍선이 아직 나오는 중이면 말하기로 이어감
    click_talks: bool = False             # 서서 클릭 = 놀람 그림 없이 바로 말하기(이안, 사용자 11-24)
    walk_speed: float = WALK_SPEED        # 걷는 빠르기(논리 px/초) — 걷기 그림 한 바퀴 거리에 맞춤
    talk_sets: tuple = ()                 # 말하기 그림 벌(아리아는 A·B — 말 한 번마다 무작위)
    pet_shake: bool = False               # 쓰다듬기 참는 중 좌우 1px 떨림(레나)
    rare_extra: str | None = None         # 드문 기본 동작(게임 밖 서 있기에서 3~6분에 한 번, 1바퀴)
    rare_gap: tuple[float, float] = RARE_GAP
    rare_say: tuple[int, str] | None = None   # 드문 동작 그 프레임에서 말풍선 상황(Starline 재채기 4번 '누가 내 욕하나?')
    sleep_gap: tuple[float, float] | None = None    # 다래: 구석에 앉아 있는 동안 엎드려 자기 간격(없으면 안 함)
    sleep_hold: tuple[float, float] = SLEEP_HOLD    # 엎드려 숨쉬는 시간
    scale: float = 1.0                    # 그리기 배율(사용자 11-24 B안 — 얼굴 크기 맞춤: Starline 1.15·레나 0.95). 그림 파일은 그대로

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
        rare, sleep = pair(raw.get("rareGap"), float, 30.0), pair(raw.get("sleepGap"), float, 30.0)
        hold = pair(raw.get("sleepHold"), float, 5.0)
        return replace(self, idle_gap=gap or self.idle_gap, idle_laps=laps or self.idle_laps,
                       rare_gap=rare or self.rare_gap,
                       sleep_gap=(sleep or self.sleep_gap) if self.sleep_gap else None,
                       sleep_hold=hold or self.sleep_hold)


DARE = Profile(ANIMS, _NEXT, SITTING, "sit_drowsy", doze_state="sit_doze", walk_speed=DARE_WALK_SPEED,
               talk_sets=DARE_TALK, sleep_gap=SLEEP_GAP)

# 아리아(docs/characters/아리아.md): 졸기·자다 깨기 없음 — 구석에서 머리를 안고 앉아 웃음(0 길게 → 3 → 0 → 1 → 2 → 0),
# 앉아서 클릭 = 웃음 프레임. 서 있기 두 자세 번갈아 + 가만히 서 있는 동안 가끔 머리 쓰다듬기(사용자 11-24).
ARIA_ANIMS = {
    "stand": (("stand_0", "stand_1"), (2.2, 2.2), True),
    "walk": (tuple(f"walk_{i}" for i in range(8)), (ARIA_WALK_FRAME,) * 8, True),   # GPT 워크 8장(11-26 — 양발·팔 번갈아)
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
    "talk_happy": (("talk_happy_0", "talk_happy_1", "talk_laugh_0"), (0.3,) * 3, True),  # 기쁨은 예전 그림
    "stretch": (tuple(f"stretch_{i}" for i in range(6)), (0.5, 0.5, 1.0, 0.7, 0.6, 0.5), False),   # 기지개(11-25)
}
ARIA_TALK = (talk_set("talk_a_"), talk_set("talk_b_"))   # 머리 다발 잡고 말하기(A)·두 손 모음(B)
ARIA_ANIMS.update(_talk_anims(ARIA_TALK))
ARIA = Profile(ARIA_ANIMS,
               {"surprise": "stand", "land": "getup", "getup": "stand", "pet_in": "pet_loop", "pet_out": "stand",
                "alert": "stand", "crouch": "sit_loop", "sit_notice": "sit_loop", "rise": "stand", "talk_end": "stand",
                "stretch": "stand"},
               ("crouch", "sit_loop", "sit_notice"), "sit_loop", idle_extra="hairstroke",
               walk_speed=ARIA_WALK_SPEED, talk_sets=ARIA_TALK, rare_extra="stretch")
# 이안(docs/characters/이안.md): 졸기 없음·놀람 그림 없음(서서 클릭 = 바로 말하기 — 사용자 11-24),
# 서 있기 ↔ 시계 보기 번갈아, 떨어지면 두 발 착지 → 바로 서기(엉덩방아·일어나기 없음), 알림 = 시계 가리키며 말함.
IAN_ANIMS = {
    "stand": (("stand_1",), (1.0,), True),
    "walk": (tuple(f"walk_{i}" for i in range(8)), (IAN_WALK_FRAME,) * 8, True),   # v3 8장(11-25 — 양발 번갈아)
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
}
IAN_TALK = ({**talk_set(), "end1": "talk_end1_0", "end2": "talk_end2_0"},)   # v2: 말 끝 두 장(레나와 같은 틀)
IAN_ANIMS.update(_talk_anims(IAN_TALK))
IAN = Profile(IAN_ANIMS,
              {"surprise": "stand", "land": "stand", "pet_in": "pet_loop", "pet_out": "stand", "alert": "stand",
               "crouch": "sit_loop", "sit_notice": "sit_loop", "rise": "stand", "talk_end": "stand"},
              ("crouch", "sit_loop", "sit_notice"), "sit_loop", idle_extra="watch", idle_laps=(1, 1),
              click_talks=True, walk_speed=IAN_WALK_SPEED, talk_sets=IAN_TALK)
# 레나(docs/characters/레나.md·기획 11-24): 졸기·대기 동작 없음, 서서 클릭 = 바로 말하기(이안과 같음),
# 떨어지기 한 장 → 착지 4장(엎어짐·일으킴·옷 털기·팔짱) → 서기, 쓰다듬기 참는 중 1px 떨림 → '흥' → 서기,
# 앉아 있기 0 길게 + 가끔 발끝 까딱·한숨·깜빡임, 말 끝은 사이 대신 끝 두 장.
LENA_ANIMS = {
    "stand": (("stand_0",), (1.0,), True),
    "magic": (tuple(f"magic_{i}" for i in range(6)), (0.5, 0.6, 0.6, 0.8, 0.7, 0.6), False),   # 마법 연습 펑(11-25)
    "walk": (tuple(f"walk_{i}" for i in range(8)), (LENA_WALK_FRAME,) * 8, True),   # GPT 워크 8장(11-26 — 양발·팔 번갈아)
    "surprise": (("stand_0",), (0.3,), False),   # click_talks라 쓰지 않음(자리만)
    "drag": (tuple(f"drag_{i}" for i in range(4)), (0.18,) * 4, True),
    "fall": (("fall_0",), (1.0,), True),
    "land": (("land_0", "land_1", "land_2", "land_3"), (0.6, 0.35, 0.5, 0.8), False),
    "pet_in": (("pet_0", "pet_1"), (0.4, 0.4), False),
    "pet_loop": (("pet_2", "pet_3", "pet_4"), (0.45,) * 3, True),
    "pet_out": (("pet_5",), (1.6,), False),
    "alert": (("talk_emph_0",), (1.5,), False),   # 손가락으로 짚으며 알림
    "crouch": (("crouch_0", "crouch_1", "crouch_2"), (0.25,) * 3, False),
    # 눈을 옆으로 흘기는 sit_2는 뺌(사용자 11-25 '눈이 움직인다' → '3프레임째만 빼면') — 그 시간은 앞뒤 sit_0에 합쳐 주기 15초 그대로
    # 윙크(sit_3)는 한 주기에 한 번 0.8초(사용자 11-26 '휙 지나간다 — 몇 프레임 보여 주면 자연스러울 것')
    "sit_loop": (("sit_0", "sit_1", "sit_0", "sit_3", "sit_0"),
                 (3.5, 0.8, 3.0, 0.8, 6.9), True),
    "sit_notice": (("sit_0",), (1.2,), False),    # 앉아서 클릭 = 그림 그대로(말풍선만)
    "rise": (("rise_0", "rise_1", "rise_2"), (0.25,) * 3, False),
}
LENA_TALK = ({**talk_set(), "end1": "talk_end1_0", "end2": "talk_end2_0"},)
LENA_ANIMS.update(_talk_anims(LENA_TALK))
LENA = Profile(LENA_ANIMS,
               {"surprise": "stand", "land": "stand", "pet_in": "pet_loop", "pet_out": "stand", "alert": "stand",
                "crouch": "sit_loop", "sit_notice": "sit_loop", "rise": "stand", "talk_end": "stand", "magic": "stand"},
               ("crouch", "sit_loop", "sit_notice"), "sit_loop", click_talks=True, walk_speed=LENA_WALK_SPEED,
               talk_sets=LENA_TALK, pet_shake=True, scale=LENA_SCALE, rare_extra="magic")
# Starline(docs/characters/Starline.md, 기획 11-24): 졸기 없음, 서 있기 한 장(B안 긴 체형), 가만히 서 있으면 가끔
# 손바닥 불꽃(아리아 머리 쓰다듬기·이안 시계와 같은 틀), 서서 클릭 = 바로 말하기, 착지 3장 → 서기,
# 쓰다듬기 귀 젖힘 → 걷어내기 반복 → 손 털고 씩, 구석은 앉기 → 마법진 돌리기 반복 → 일어나기, 말 끝 두 장.
STARLINE_ANIMS = {
    "stand": (("stand_0",), (1.0,), True),   # B안 서 있기 한 장(11-24)
    "walk": (tuple(f"walk_{i}" for i in range(8)), (STARLINE_WALK_FRAME,) * 8, True),   # GPT 워크 8장(11-26 — 양발·팔 번갈아)
    "surprise": (("stand_0",), (0.3,), False),   # click_talks라 쓰지 않음(자리만)
    "drag": (tuple(f"drag_{i}" for i in range(4)), (0.18,) * 4, True),
    "fall": (("fall_0",), (1.0,), True),
    "land": (("land_0", "land_1", "land_2"), (0.25, 0.35, 0.6), False),
    "pet_in": (("pet_0",), (0.45,), False),
    "pet_loop": (("pet_1", "pet_2", "pet_3", "pet_4"), (0.3,) * 4, True),
    "pet_out": (("pet_5",), (1.6,), False),
    "alert": (("talk_emph_0",), (1.5,), False),   # 손가락 튕기며 알림
    "crouch": (("crouch_0", "crouch_1"), (0.3, 0.3), False),   # 앉기 시트 1·2번(0번 서 있는 장은 짧은 체형이라 뺌)
    "sit_loop": (("sit_0", "sit_1", "sit_2", "sit_3"), (0.3,) * 4, True),   # 마법진 돌리기
    "sit_notice": (("sit_0",), (1.2,), False),    # 앉아서 클릭 = 그림 그대로(말풍선만)
    "rise": (("rise_0", "rise_1"), (0.3, 0.3), False),         # 끝 서 있는 장 빼고 → 바로 서기
    "flame": (("flame_0", "flame_1", "flame_2", "flame_3"), (0.35, 0.8, 0.8, 0.35), True),   # 불꽃 피웠다 쥐어 끔
    # 큰 재채기(11-25): 4번(두리번)에서 말풍선 '누가 내 욕하나?'
    "sneeze": (tuple(f"sneeze_{i}" for i in range(6)), (0.4, 0.4, 0.5, 0.6, 1.3, 0.6), False),
}
STARLINE_TALK = ({**talk_set(), "end1": "talk_end1_0", "end2": "talk_end2_0"},)
STARLINE_ANIMS.update(_talk_anims(STARLINE_TALK))
STARLINE = Profile(STARLINE_ANIMS,
                   {"surprise": "stand", "land": "stand", "pet_in": "pet_loop", "pet_out": "stand", "alert": "stand",
                    "crouch": "sit_loop", "sit_notice": "sit_loop", "rise": "stand", "talk_end": "stand",
                    "sneeze": "stand"},
                   ("crouch", "sit_loop", "sit_notice"), "sit_loop", idle_extra="flame", idle_laps=(1, 1),
                   click_talks=True, walk_speed=STARLINE_WALK_SPEED, talk_sets=STARLINE_TALK, scale=STARLINE_SCALE,
                   rare_extra="sneeze", rare_say=(4, "sneeze"))   # 0.56.2엔 꺼 뒀다가 새 시트(재채기_v2)로 다시 켬
PROFILES = {"다래": DARE, "아리아": ARIA, "이안": IAN, "레나": LENA, "Starline": STARLINE}


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
    _game_front: bool = False        # 진짜 게임 포그라운드(호감도 구석 시간은 이것만) — _front는 '빈 바닥 없음'도 포함
    _front_by_game: bool = False     # 구석으로 간 까닭이 게임이었나(빈 바닥이 없어서면 게임 대사 안 함)
    _spans: tuple | None = None      # 빈 바닥(보이는 게임 화면을 뺀 x 구간) — None이면 바닥 전체
    _press: tuple[float, float] | None = None
    _grab: tuple[float, float] = (0.0, 0.0)
    _dragging: bool = False
    _vy: float = 0.0
    _rub_x: float | None = None
    _rub_dir: int = 0
    _rub_turns: list = field(default_factory=list)
    _rub_from: float = 0.0           # 지금 방향으로 움직이기 시작한 x
    _last_rub: float = 0.0
    _pet_reached_loop: bool = False
    _corner_time: float = 0.0
    _hunt_time: float = 0.0
    _speed: float = WALK_SPEED
    _walk_rate: float = 1.0
    _talk_until: float = 0.0
    _next_extra: float = 0.0
    motions: dict = field(default_factory=dict)          # 열린 호감도 모션 key → character.motions.Motion
    motion_weights: dict = field(default_factory=dict)   # key → 고를 무게(새로 열린 것 2배)
    _motion_seq: tuple = ()                              # 지금 하는 모션 (프레임, 초) 순서
    motion_key: str | None = None
    _queued_motion: str | None = None                    # 구간 오름 대사를 말하는 중 → 끝나고 서면 바로
    _next_rare: float = 0.0
    _rare_said: bool = False
    _sleep_next: float = 0.0         # 다래: 다음 엎드려 자기 시각(구석에 앉으면 정함)
    _sleep_until: float = 0.0
    _extra_until: float = 0.0
    _queued_talk: tuple | None = None
    _talk_set: dict | None = None
    _emph_at: float | None = None
    _blinks: tuple = ()
    _edge: tuple[float, float] | None = None   # 끌어서 정한 구석이 없을 때 이번 게임에 앉을 화면 끝

    def __post_init__(self) -> None:
        if self.pos == (0.0, 0.0):
            self.pos = (self.floor.clamp_x((self.floor.left + self.floor.right) / 2), self.floor.y)

    # ---- 보이는 것 ----------------------------------------------------------------------------
    def frame(self, now: float) -> str:
        if self.state == "motion":
            t = now - self._t0
            for name, d in self._motion_seq:
                if t < d:
                    return name
                t -= d
            return self._motion_seq[-1][0] if self._motion_seq else self.profile.anims["stand"][0][0]
        if self.state == "talk" and self._talk_set is not None:
            return self._talk_frame(now)
        if self.state == "talk_end" and self._talk_set is not None:  # base 잠시 → 사이(또는 끝 두 장) → (서 있기)
            t = now - self._t0
            steps = _end_steps(self._talk_set)
            for key, d in steps:
                if t < d:
                    return self._talk_set[key]
                t -= d
            return self._talk_set[steps[-1][0]]
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

    def shake(self, now: float) -> int:
        """쓰다듬기 참는 중 좌우 떨림(논리 px) — 0.13초마다 0 → +1 → 0 → −1. 떨림 없는 캐릭터·다른 동작은 0."""
        if not self.profile.pet_shake or self.state != "pet_loop":
            return 0
        return (0, 1, 0, -1)[int((now - self._t0) / SHAKE_SECONDS) % 4]

    def zzz(self) -> bool:
        """꾸벅 조는 동안만 Zzz(코드로 그림). 졸지 않는 캐릭터는 없음."""
        return self.profile.doze_state is not None and (self.state == self.profile.doze_state
                                                         or self.state in ("sleep_down", "sleep_loop"))

    def home(self) -> tuple[float, float]:
        """게임 중 앉을 자리 — 끌어서 정한 구석이 있으면 그곳, 없으면 가까운 화면 끝(사용자 11-24 — 왼쪽일 수도)."""
        if self.corner is not None:
            return self.corner
        if self._edge is not None:
            return self._edge
        return (self.floor.clamp_x(self.floor.right), self.floor.y)

    def _pick_edge(self) -> None:
        """구석으로 출발하는 순간 한 번만 정함 — 바닥 가운데보다 왼쪽이면 왼쪽 끝, 아니면 오른쪽 끝(앉은 동안 유지)."""
        middle = (self.floor.left + self.floor.right) / 2
        x = self.floor.left if self.pos[0] < middle else self.floor.right
        self._edge = (self.floor.clamp_x(x), self.floor.y)

    # ---- 내부 -------------------------------------------------------------------------------
    def _go(self, state: str, now: float) -> None:
        self.state, self._t0 = state, now
        if state == "pet_loop":
            self._pet_reached_loop = True

    def _done(self, now: float) -> bool:
        if self.state == "motion":
            return now - self._t0 >= sum(d for _n, d in self._motion_seq)
        if self.state == "talk_end" and self._talk_set is not None:
            return now - self._t0 >= sum(d for _, d in _end_steps(self._talk_set))
        frames, times, loop = self.profile.anims[self.state]
        return not loop and now - self._t0 >= sum(times)

    def _talk_frame(self, now: float) -> str:
        """말하는 동안 시간표 — 사이 → 입만 바꾸기(m1·m2·m1·base), 강조 1번, 3~5초마다 깜빡임."""
        s = self._talk_set
        t = now - self._t0
        if t < MID_SECONDS:
            return s["mid"]
        if self._emph_at is not None:
            e = now - self._emph_at
            if 0 <= e < EMPH_SECONDS[0]:
                return s["emph"]
            if EMPH_SECONDS[0] <= e < sum(EMPH_SECONDS):
                return s["emph2"]
        if any(0 <= now - b < BLINK_SECONDS for b in self._blinks):
            return s["blink"]
        return s[MOUTH_ORDER[int((t - MID_SECONDS) / MOUTH_SECONDS) % len(MOUTH_ORDER)]]

    def _start_talk(self, now: float, until: float, mood: str, chars: int) -> None:
        sets = self.profile.talk_sets
        self._talk_set = self.rng.choice(sets) if sets else None  # 아리아 A/B 무작위(직전과 같아도 됨)
        self._talk_until = until
        mood_state = f"talk_{mood}"
        if mood in ("think", "happy") and mood_state in self.profile.anims:
            self._go(mood_state, now)  # 생각·기쁨 그림이 있는 캐릭터는 그 그림 그대로
            return
        if self._talk_set is None:
            return
        speak = now + MID_SECONDS
        self._talk_until = max(until + MID_SECONDS, speak + MOUTH_SECONDS * 2)  # 사이 프레임만큼 늦게 끝내 글자 끝까지 입이 움직임
        if mood == "explain":
            self._emph_at = speak  # 설명은 첫머리에 한 번
        elif chars >= EMPH_MIN_CHARS:
            self._emph_at = speak + max(0.0, (self._talk_until - speak) / 2 - sum(EMPH_SECONDS) / 2)
        else:
            self._emph_at = None
        blinks, t = [], speak
        while t < speak + 120:
            t += self.rng.uniform(*BLINK_GAP)
            blinks.append(t)
        self._blinks = tuple(blinks)
        self._go("talk", now)

    def _walk_to(self, target: tuple[float, float], now: float) -> None:
        self._target = target
        self._speed = max(self.profile.walk_speed * 2.0, math.dist(self.pos, target) / 3.0)
        self.facing_left = target[0] < self.pos[0]
        self._go("walk", now)

    def _schedule_walk(self, now: float) -> None:
        self._next_walk = now + self.rng.uniform(3.0, 9.0)

    def _schedule_extra(self, now: float) -> None:
        """서서 대기 동작(아리아 머리 쓰다듬기) 다음 차례 — 8~15초 뒤 무작위(설정 값)."""
        if self.profile.idle_extra or self.motion_weights:
            self._next_extra = now + self.rng.uniform(*self.profile.idle_gap)

    # ---- 호감도 모션(25·75 보상, 호감도_모션.md '앱 동작') ------------------------------------------
    def set_motions(self, specs: dict, weights: dict) -> None:
        """열린 모션(key → Motion)과 고를 무게. 서 있는 동안 대기 번갈아 후보에 더해짐."""
        self.motions = dict(specs)
        self.motion_weights = {k: w for k, w in weights.items() if k in self.motions}

    def show_motion(self, key: str, now: float) -> None:
        """구간이 오른 순간 새 모션 한 번 — 지금 말하는 중이면(구간 오름 대사) 말이 끝나고 서 있게 되면 바로."""
        if not self.play_motion(key, now) and key in self.motions and self.state in TALKING:
            self._queued_motion = key

    def play_motion(self, key: str, now: float) -> bool:
        """모션을 바로 한 번. 서 있을 때만 — 구석·걷기·끌기·말하기 중이면 안 함."""
        motion = self.motions.get(key)
        if (motion is None or self._goal != "roam" or self._dragging
                or self.state not in ("stand", self.profile.idle_extra, "motion")):
            return False
        self._motion_seq = motion.sequence(self.rng)
        self.motion_key = key
        length = sum(d for _n, d in self._motion_seq)
        self._target = None
        self._next_walk = max(self._next_walk, now + length + 1.0)   # 끝까지 하고 걷기
        self._next_extra = max(self._next_extra, now + length + 1.0)
        self._go("motion", now)
        return True

    def _pick_idle(self, now: float) -> None:
        """대기 번갈아 — 원래 대기 동작(무게 1)과 열린 모션(새 것 2배) 중 무작위."""
        options = ([(None, 1.0)] if self.profile.idle_extra else []) + list(self.motion_weights.items())
        if not options:
            return
        choice = self.rng.choices([k for k, _w in options], [w for _k, w in options])[0]
        if choice is not None and self.play_motion(choice, now):
            return
        if self.profile.idle_extra:
            laps = self.rng.randint(*self.profile.idle_laps)
            _frames, times, _loop = self.profile.anims[self.profile.idle_extra]
            self._extra_until = now + laps * sum(times)
            self._go(self.profile.idle_extra, now)
        else:
            self._schedule_extra(now)

    # ---- 시간 --------------------------------------------------------------------------------
    # ---- 빈 바닥(진짜 창모드 — 보이는 게임 화면 피하기, QA 11-26) --------------------------------------
    def _centers(self) -> list[tuple[float, float]]:
        """빈 구간마다 펫 가운데가 설 수 있는 x 범위(창 폭 절반씩 안쪽)."""
        half = floor_space.PET_WIDTH / 2
        return [(lo + half, hi - half) for lo, hi in self._spans or ()]

    def _allowed(self, x: float) -> bool:
        return self._spans is None or any(a - 1.0 <= x <= b + 1.0 for a, b in self._centers())

    def _nearest_free(self, x: float) -> float:
        """막힌 구간 안이면 가장 가까운 빈 구간 안쪽 점."""
        return min((min(b, max(a, x)) for a, b in self._centers()), key=lambda c: abs(c - x))

    def _roam_x(self) -> float:
        """돌아다닐 다음 목표 x — 빈 바닥이 정해져 있으면 지금 선 빈 구간 안에서만(막힌 구간을 건너가지 않음)."""
        if self._spans is None:
            return self.floor.clamp_x(self.rng.uniform(self.floor.left, self.floor.right))
        x = self.pos[0]
        here = [(a, b) for a, b in self._centers() if a - 1.0 <= x <= b + 1.0]
        if not here:
            return self._nearest_free(x)
        a, b = here[0]
        return self.rng.uniform(a, b)

    def tick(self, now: float, game_front: bool, blocked=()) -> list[tuple]:
        """blocked: 보이는 게임 화면이 바닥 띠와 겹치는 x 구간(논리 px, 게임이 포그라운드가 아닐 때만 의미)."""
        events: list[tuple] = []
        self._game_front = bool(game_front)
        spans = floor_space.free_spans(self.floor, blocked) if blocked and not game_front else None
        self._spans = tuple(spans) if spans else None   # 빈 바닥이 없으면 아래 '구석에서 졸기'가 맡음
        game_front = self._game_front or (spans is not None and not spans)   # 설 빈 바닥이 없으면 게임 때처럼 구석에서 졸기
        dt = 0.0 if self._last is None else max(0.0, min(0.5, now - self._last))
        self._last = now
        if self._next_idle == 0.0:
            self._next_idle = now + self.rng.uniform(*IDLE_LINE)
            self._schedule_extra(now)
        if self.profile.rare_extra and self._next_rare == 0.0:
            self._next_rare = now + self.rng.uniform(*self.profile.rare_gap)
        if game_front != self._front:
            self._front, self._front_since = game_front, now
        if self._front and self._game_front:
            self._front_by_game = True
        if self._front and now - self._front_since >= FRONT_DELAY and self._goal != "corner":
            self._goal = "corner"
            self._hunt_time = 0.0
            self._pick_edge()
            self._front_by_game = self._game_front
            if not self._dragging and self.state in STANDING:
                if self._front_by_game:
                    events.append(("say", "game_enter"))
                if self.state == "walk":  # 돌아다니던 걸음을 구석 쪽으로 바꿈(빠르기도 다시 정함)
                    self._walk_to(self.home(), now)
        elif not self._front and now - self._front_since >= BACK_DELAY and self._goal != "roam":
            self._goal = "roam"
            if self.state in self.profile.sitting:
                # 엎드려 자던 다래는 눈 비비며 일어나 앉은 뒤(6·7·8) 일어나기
                self._go("sleep_up" if self.state in ("sleep_down", "sleep_loop") else "rise", now)
                if self._front_by_game:
                    events.append(("say", "game_exit"))
            self._front_by_game = False
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
            nxt = "stand" if self.state == "motion" else self.profile.next_map[self.state]
            queued, self._queued_talk = self._queued_talk, None
            if self.state == "surprise" and queued is not None and now < queued[0]:
                self._start_talk(now, queued[0], queued[1], queued[2])  # 클릭 반응 뒤 이어서 말함(이안)
                nxt = self.state
            if self.state == "getup" and self._goal == "corner" and self._near(self.home()):
                nxt = "crouch"  # 게임 중 구석에 놓였으면 그 자리에서 다시 앉는다
            if self.state == "sleep_up" and self._goal == "corner":
                nxt = self.profile.sit_state   # 게임 중이면 다시 구석 앉아 있기로(게임이 끝났으면 일어나기)
            if nxt != self.state:
                self._go(nxt, now)
            if nxt == "stand":
                self._schedule_walk(now)
                self._schedule_extra(now)
                queued_motion, self._queued_motion = self._queued_motion, None
                if queued_motion is not None:
                    self.play_motion(queued_motion, now)
            elif nxt == "pet_loop":
                events.append(("say", "pet_during"))

        rare = self.profile.rare_extra
        if rare and self.state == rare and self.profile.rare_say and not self._rare_said:
            index, situation = self.profile.rare_say
            if self.frame(now) == self.profile.anims[rare][0][index]:
                self._rare_said = True
                events.append(("say", situation))
        if self.profile.sleep_gap:
            if self.state in self.profile.sitting and self._front:
                if self._sleep_next == 0.0:
                    self._sleep_next = now + self.rng.uniform(*self.profile.sleep_gap)
                if self.state in ("sit_drowsy", "sit_doze", "sit_half") and now >= self._sleep_next:
                    down = sum(self.profile.anims["sleep_down"][1])
                    self._sleep_until = now + down + self.rng.uniform(*self.profile.sleep_hold)
                    self._go("sleep_down", now)   # 엎드려 자기
                elif self.state == "sleep_loop" and now >= self._sleep_until:
                    self._go("sleep_up", now)     # 숨쉬다 다시 앉음
                    self._sleep_next = now + self.rng.uniform(*self.profile.sleep_gap)
            elif self.state not in self.profile.sitting:
                self._sleep_next = 0.0

        if self.state in self.profile.sitting and self._game_front:   # 호감도는 진짜 게임 중일 때만(빈 바닥 없음은 안 셈)
            self._corner_time += dt
            self._hunt_time += dt
            if self._corner_time >= 60.0:  # 1분마다 — 호감도(30분마다 +1·퀘스트 누적 분)는 창 쪽에서
                self._corner_time -= 60.0
                events.append(("corner_minute",))
            if self._hunt_time >= LONG_HUNT and self.state != self.profile.doze_state and self.state not in SLEEPING:
                self._hunt_time = 0.0
                events.append(("say", "long_hunt"))

        if self._goal == "roam" and self._spans is not None and not self._dragging:
            if self.state == "walk" and self._target is not None and not self._allowed(self._target[0]):
                self._walk_to((self._roam_x(), self.floor.y), now)    # 걷는 중 그 앞이 막힘 → 지금 빈 구간 안으로
            elif self.state in ("stand", self.profile.idle_extra, "motion") and not self._allowed(self.pos[0]):
                self._walk_to((self._nearest_free(self.pos[0]), self.floor.y), now)   # 막힌 곳에 서 있음 → 가까운 빈 곳으로
        if self.state == "walk":
            self._step(dt, now)
        elif self.state in ("stand", self.profile.idle_extra, rare, "motion"):  # 대기·드문 동작·모션 중이어도 걸을 차례·게임이 오면 바로 끊음
            if self._goal == "corner":
                if self._near(self.home()):
                    self._go("crouch", now)
                else:
                    self._walk_to(self.home(), now)
            elif now >= self._next_walk:
                self._walk_to((self._roam_x(), self.floor.y), now)
            elif self.state == "stand" and rare and now >= self._next_rare > 0:
                if self._next_idle - now < RARE_DEFER:   # 혼잣말이 곧 나올 차례 → 드문 동작은 다음 차례로
                    self._next_rare = now + RARE_DEFER
                else:
                    length = sum(self.profile.anims[rare][1])
                    self._next_rare = now + self.rng.uniform(*self.profile.rare_gap)
                    self._next_walk = max(self._next_walk, now + length + 1.0)       # 한 바퀴 다 하고 걷기
                    self._next_extra = max(self._next_extra, now + length + 1.0)     # 대기 동작과 안 겹침
                    self._rare_said = False
                    self._go(rare, now)
            elif self.state == "stand" and (self.profile.idle_extra or self.motion_weights) and now >= self._next_extra > 0:
                self._pick_idle(now)
            elif self.state == "stand" and self.motion_weights and self._next_extra == 0.0:
                self._schedule_extra(now)

        if now >= self._next_idle and rare and self.state == rare:
            self._next_idle = now + RARE_DEFER   # 드문 동작 중엔 혼잣말을 미룸
        if now >= self._next_idle:
            self._next_idle = now + self.rng.uniform(*IDLE_LINE)
            quiet = self.state in self.profile.sitting and self.state not in (
                "crouch", "sit_notice", self.profile.doze_state) + SLEEPING
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
            # 이안: 클릭 반응 그림(쓰다듬기 첫 장)은 머리 크기가 달라 튀어 보여(사용자 11-24) 바로 말하기 — 말풍선이 뜨면
            # talk가 사이 → 입으로 시작
            self._go("stand" if self.profile.click_talks else "surprise", now)
            self._schedule_extra(now)
            events.append(("say", "idle_extra_click" if stroking else "click_stand"))
        elif self.profile.doze_state is not None and (self.state == self.profile.doze_state
                                                      or self.state in ("sleep_down", "sleep_loop")):
            self._go("wake", now)
            events.append(("say", "click_sleep"))
        elif self.state in self.profile.sitting:
            self._go("sit_notice", now)
            events.append(("say", "click_sit"))
        return events

    def hover(self, now: float, x: float, on_head: bool) -> list[tuple]:
        """누르지 않은 채 캐릭터 위를 움직임. 머리 위를 좌우로 2번 이상 왕복(한 번에 RUB_MIN 이상)하면 쓰다듬기."""
        if self._press is not None or not on_head:
            self._rub_x, self._rub_dir, self._rub_turns = None, 0, []   # 머리를 벗어나면 처음부터 셈
            return []
        if self.state in ("pet_in", "pet_loop"):
            self._last_rub = now
            return []
        if self.state not in UPRIGHT:
            return []
        x = x - self.pos[0]   # 펫 기준 x — 걷는 중 펫 이동이 더해져 왕복 폭이 모자라지 않게(QA 11-26 '걸을 때 쓰다듬기 안 됨')
        if self._rub_x is None:
            self._rub_x, self._rub_dir, self._rub_from = x, 0, x
            return []
        d = x - self._rub_x
        if d == 0:
            return []
        direction = 1 if d > 0 else -1
        if self._rub_dir and direction != self._rub_dir:  # 돌아섬 — 지난 방향으로 충분히 움직였을 때만 전환 1번
            if abs(self._rub_x - self._rub_from) >= RUB_MIN:
                self._rub_turns = [t for t in self._rub_turns if now - t <= RUB_WINDOW] + [now]
                if self.state == "walk":   # 걷다가 머리 위에서 손이 왔다 갔다 → 멈춰 서서 손을 기다림
                    self._target = None
                    self._go("stand", now)
                    self._schedule_walk(now)
            self._rub_from = self._rub_x
        elif not self._rub_dir:
            self._rub_from = self._rub_x
        self._rub_dir = direction
        self._rub_x = x
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
            self._queued_talk = (now + max(0.6, chars * TYPE_SECONDS), mood, chars)  # 클릭 반응이 끝나면 이어서 말함
            return False
        if self.state not in UPRIGHT or self._dragging:
            return False
        if self.profile.rare_extra and self.state == self.profile.rare_extra:
            return False   # 드문 동작 중 말풍선(Starline 재채기 '누가 내 욕하나?')은 그림 위에만 — 동작은 끝까지(QA 11-25)
        self._target = None
        # 그 분위기 그림이 없는 캐릭터(아리아 '생각', 이안 생각·기쁨)는 보통 말하기로
        self._start_talk(now, now + max(0.6, chars * TYPE_SECONDS), mood, chars)
        return True

    def hold_talk(self, until: float) -> None:
        """대사 목소리가 글자보다 길면 말하기 그림을 소리 끝까지 유지(입 움직임). 짧으면 글자 기준 그대로."""
        if self.state in TALKING and self.state != "talk_end":
            self._talk_until = max(self._talk_until, until)

    def dragging(self) -> bool:
        return self._dragging
