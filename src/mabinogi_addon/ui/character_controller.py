"""캐릭터 컨트롤러 — 고른 캐릭터의 호감도·대사·펫 창을 묶는다(docs/character-pet-spec.md 2·3절).

- 앱을 켜면: 연속 켠 날 세기, 그날 처음이면 호감도 +2, 펫이 떠 있으면 인사(오랜만·밤·아침·보통).
- 알림 소리(notifier.on_play)가 고른 캐릭터 목소리 팩이면: 알림 누적 + 호감도 +1(하루 3번), 펫은 알아챔 + 같은 뜻 말풍선.
- 펫 사건: 말풍선(상황별 무작위·같은 줄 연속 금지), 클릭 반복 −1 + 짜증, 쓰다듬기 끝까지 +1(다 채운 뒤 또 → −1),
  구석에서 함께 1분마다 누적(오늘 30분마다 +1, 하루 2번), 끌어서 정한 구석 저장. 규칙은 character/affinity.py.
- 펫 창은 '화면에 캐릭터 띄우기'가 켜져 있고 고른 캐릭터에 SD 그림이 있을 때만(알파는 다래만) 뜬다.
- 알파는 제작자 전용(사용자 결정 11-24): set_enabled(False)면 펫·호감도·인사 모두 하지 않는다(알림 소리도 무시).
"""
from __future__ import annotations

import datetime
import logging
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from .. import config, paths
from ..character import roster
from ..character.affinity import Affinity, Rules
from ..character.brain import DARE, PROFILES, Brain, Floor
from ..character.lines import Lines, Picker, read

_log = logging.getLogger(__name__)
LONG_AWAY_DAYS = 3


def today(now: datetime.datetime | None = None) -> str:
    return (now or datetime.datetime.now()).strftime("%Y-%m-%d")


def greeting(last_seen: str, now: datetime.datetime) -> str | None:
    """앱을 켰을 때 인사 상황(그날 처음일 때만). 같은 날 다시 켜면 None."""
    if last_seen == today(now):
        return None
    try:
        away = (now.date() - datetime.date.fromisoformat(last_seen)).days if last_seen else 0
    except ValueError:
        away = 0
    if away > LONG_AWAY_DAYS:
        return "hello_long"
    if 0 <= now.hour < 5:
        return "night"
    if 6 <= now.hour < 10:
        return "morning"
    return "hello"


class CharacterController(QObject):
    affinity_changed = Signal()

    def __init__(self, watcher=None, parent: QObject | None = None, clock=time.monotonic) -> None:
        super().__init__(parent)
        self._watcher = watcher
        self._clock = clock
        self.window = None
        self._window_for = None       # 펫 창이 어느 캐릭터 것인지
        self._last_pos = None         # 캐릭터를 바꿀 때 새 펫이 이어받을 자리
        self.enabled = False
        self._started = False
        self._paused = False          # 앱 일시정지(알림 멈춤) — 대사 목소리도 안 냄
        from .voice_lines import VoiceLinePlayer
        self.voice = VoiceLinePlayer(self)
        self.voice.on_duration = self._hold_talk
        self._lines: dict[str, Picker] = {}
        self._feeds: dict = {}
        self.character = roster.by_pack(config.load_voice_pack())
        self.affinity = self._load_affinity()
        self._stage = self._current_stage()
        self.voice_alert_day = ""     # 캐릭터 목소리 팩으로 알림이 울린 날(featureUsage character_voice, 11-25)
        from .notifier import on_play
        on_play(self._on_sound)

    # ---- 시작·바뀜 ---------------------------------------------------------------------------
    def set_enabled(self, on: bool) -> None:
        """제작자 권한이 바뀜(로그인·로그아웃). 꺼지면 펫을 닫는다."""
        self.enabled = bool(on)
        if self._started or not self.enabled:
            self.sync_window()

    def reload_affinity(self) -> None:
        """제작자가 캐릭터 탭에서 호감도를 바꿈 → 저장 값으로 다시 읽는다(구간이 올랐으면 stage_up 한 번)."""
        self.affinity = self._load_affinity()
        self._check_stage()

    def start(self, now: datetime.datetime | None = None) -> None:
        self._started = True
        if not self.enabled:
            return
        now = now or datetime.datetime.now()
        last = config.load_pet_last_seen()
        hello = greeting(last, now)
        if self.affinity is not None:
            self.affinity.launched(today(now))  # 연속 켠 날(75→100 퀘스트)·그날 처음 +2
            self._save_affinity()
        config.save_character(lastSeen=today(now))
        self.sync_window()
        if hello and self.window is not None:
            self._say(self._pick(hello))

    def voice_changed(self) -> None:
        self.character = roster.by_pack(config.load_voice_pack())
        self.affinity = self._load_affinity()
        self._stage = self._current_stage()  # 캐릭터를 바꾼 건 구간이 오른 게 아님
        self.sync_window()

    def outfit_changed(self, key: str) -> None:
        """캐릭터 탭에서 옷을 갈아입음 → 지금 펫이 그 캐릭터면 창을 다시 만듦(착장 프레임이 있으면 그걸로)."""
        if self.window is not None and self.character is not None and self.character.key == key:
            self._window_for = None
            self.sync_window()

    def pet_visible(self) -> bool:
        """'화면에 캐릭터 띄우기' 켬 + 펫 창이 실제로 보임(featureUsage pet)."""
        return config.load_pet_on() and self.window is not None and self.window.isVisible()

    def voice_used_today(self) -> bool:
        """오늘 캐릭터 목소리로 알림이 울렸는지 + 지금도 캐릭터 목소리(featureUsage character_voice)."""
        return bool(config.load_voice_pack()) and self.voice_alert_day == today()

    def sync_window(self) -> None:
        """펫 창을 켜야 하면 만들고, 아니면 닫는다."""
        want = (self.enabled and config.load_pet_on() and self.character is not None
                and self.character.has_pet)
        if want and self.window is not None and self._window_for is not self.character:
            # 캐릭터 탭에서 다른 캐릭터를 고름 → 펫도 그 캐릭터로(창을 다시 만듦, 위치는 이어받음)
            self._last_pos = self.window.brain.pos
            self.window.stop()
            self.window.deleteLater()
            self.window = None
        if want and self.window is None:
            self.window = self._make_window()
            if self.window is not None:
                self.window.start()
        elif not want and self.window is not None:
            self.window.stop()
            self.window.deleteLater()
            self.window = None

    def shutdown(self) -> None:
        if self.enabled and self._started:
            self._save_affinity()  # 구석 분 누적(10분마다 저장) 나머지
        from .notifier import off_play
        off_play(self._on_sound)
        self.voice.stop()
        for feed in self._feeds.values():
            feed.shutdown()
        if self.window is not None:
            self.window.stop()

    # ---- 부품 --------------------------------------------------------------------------------
    def _load_affinity(self) -> Affinity | None:
        if self.character is None:
            return None
        return Affinity.load(config.load_affinity(self.character.key), Rules.from_dict(config.load_affinity_rules()))

    def _save_affinity(self) -> None:
        if self.character is not None and self.affinity is not None:
            config.save_character(affinity=(self.character.key, self.affinity.to_dict()))
            self.affinity_changed.emit()
            self._check_stage()

    def _current_stage(self) -> int:
        return self.affinity.stage if self.affinity is not None else 0

    def _check_stage(self) -> None:
        """구간이 오른 순간 그 구간 stage_up 한 줄을 한 번(여러 구간을 건너뛰면 가장 높은 구간 것만).
        내려가면 말 없음. 펫이 꺼져 있으면 말하지 않고 밀린 것도 쌓지 않는다(지금 구간만 기억)."""
        stage, before = self._current_stage(), self._stage
        self._stage = stage
        if stage > before and self.window is not None:
            picker = self.picker()
            if picker is not None:
                self._say(picker.stage_up(stage))

    def set_paused(self, paused: bool) -> None:
        """앱 일시정지(사냥 안 할 때) — 대사 목소리도 멈추고 안 냄."""
        self._paused = bool(paused)
        if paused:
            self.voice.stop()

    def _say(self, line) -> None:
        """말풍선 + (줄에 목소리가 있고 그 팩에 파일이 있으면) 대사 목소리 — 글자가 나오기 시작할 때 함께."""
        if self.window is None or not line:
            return
        self.voice.stop()  # 앞 대사 소리는 멈추고 새 것
        self.window.say(line)
        voice = getattr(line, "voice", None)
        if not voice or self._paused or not config.load_voice_lines() or self.character is None:
            return
        from .voice_lines import voice_file

        path = voice_file(self.character.pack, voice)
        if path is not None:
            self.voice.play(path)

    def _hold_talk(self, seconds: float) -> None:
        if self.window is not None:
            self.window.hold_talk(seconds)

    def _pick(self, situation: str):
        """지금 구간 대사로 고르기(구간 이하 줄, 지금 구간 줄 2배)."""
        picker = self.picker()
        return picker.pick(situation, self._current_stage()) if picker is not None else None

    def picker(self) -> Picker | None:
        if self.character is None or not self.character.has_pet:
            return None
        key = roster.folder(self.character)
        if key not in self._lines:
            self._lines[key] = Picker(self._read_lines(key))
            self._fetch_lines(key)
        return self._lines[key]

    def _fetch_lines(self, folder: str) -> None:
        """원격 대사 갱신을 한 번(펫이 쓰일 때만). 받으면 같은 고르기 상태로 데이터만 바꾼다."""
        if folder in self._feeds:
            return
        from .character_lines_feed import LinesFeed
        feed = LinesFeed(folder, self)
        feed.updated.connect(lambda lines, key=folder: setattr(self._lines[key], "data", lines))
        self._feeds[folder] = feed
        feed.start()

    def _read_lines(self, folder: str) -> Lines:
        from .character_lines_feed import cache_path
        cache = cache_path(folder)
        try:
            return read(cache)  # 원격 갱신본(배포 없이 늘린 대사)이 있으면 그걸
        except (OSError, ValueError, UnicodeError):
            return read(paths.resource_dir() / "characters" / folder / "lines.json")

    def _make_window(self):
        from .pet_window import PetWindow, load_frames

        folder = roster.folder(self.character)
        profile = PROFILES.get(folder, DARE).with_timing(config.load_pet_idle())
        frames = load_frames(folder, profile, config.load_outfit(self.character.key))
        if not frames:
            _log.warning("펫 그림을 찾지 못함 — 펫 창 안 띄움")
            return None
        area = QGuiApplication.primaryScreen().availableGeometry()
        floor = Floor(area.left(), area.right(), area.bottom())
        corner = config.load_pet_corner()
        if corner is not None and not area.adjusted(-40, -40, 40, 40).contains(*corner):
            corner = None  # 해상도가 바뀌어 화면 밖이면 기본 구석(바닥 오른쪽 끝)
        brain = Brain(floor, corner=corner, profile=profile)
        if self._last_pos is not None:
            brain.pos = (floor.clamp_x(self._last_pos[0]), min(self._last_pos[1], floor.y))
        game = (lambda: self._watcher.is_game_active()) if self._watcher is not None else (lambda: False)
        window = PetWindow(brain, frames, self.character.color, game_front=game, clock=self._clock,
                           outline=self.character.outline, blocked=self._blocked_fn(floor, profile))
        window.events.connect(self._on_events)
        self._window_for = self.character
        return window

    def _blocked_fn(self, floor, profile):
        """진짜 창모드(QA 11-26): 게임 창 중 보이는 부분이 바닥 띠와 겹치는 x 구간(논리 px). 모르면 ()."""
        def blocked():
            if self._watcher is None:
                return ()
            rects = self._watcher.visible_game_rects()
            if not rects:
                return ()
            from ..character import brain as brain_mod
            from ..character import floor_space
            from .dpi import screen_scale
            return floor_space.blocked_spans(floor_space.to_logical(rects, screen_scale()), floor,
                                             brain_mod.FIGURE_H * profile.scale)
        return blocked

    # ---- 사건 --------------------------------------------------------------------------------
    def _on_events(self, events: list) -> None:
        now = self._clock()
        picker = self.picker()
        for event in events:
            kind = event[0]
            if kind == "say" and picker is not None and self.window is not None:
                self._say(self._pick(event[1]))
            elif kind == "click" and self.affinity is not None:
                if self.affinity.click(now):
                    self._save_affinity()
                    if picker is not None and self.window is not None:
                        self._say(self._pick("annoyed_click"))
            elif kind == "pet_done" and self.affinity is not None:
                result = self.affinity.petted(now, today())
                if result != "none":
                    self._save_affinity()
                if result == "annoyed" and picker is not None and self.window is not None:
                    self._say(self._pick("annoyed_pet"))
            elif kind == "corner_minute" and self.affinity is not None:
                # 1분마다 누적 — 저장은 오를 때·10분마다만(설정 동기화가 매분 올리지 않게), 끌 때 한 번 더
                got = self.affinity.corner_minute(today())
                if got or self.affinity.totals.get("corner_minutes", 0) % 10 == 0:
                    self._save_affinity()
            elif kind == "corner_saved":
                config.save_character(corner={"x": round(event[1]), "y": round(event[2])})

    def _on_sound(self, _buff_id: str, path) -> None:
        """알림 소리 → 대사 목소리는 멈춤(알림 우선), 그 캐릭터 목소리면 호감도 +1·알아챔·말풍선."""
        self.voice.stop()
        if config.load_voice_pack():   # 기본 목소리가 아닌 팩을 고른 채 알림이 울림 — 사용 기록용(호감도와 무관)
            self.voice_alert_day = today()
        if not self.enabled or self.character is None or self.affinity is None:
            return
        try:
            pack = path.parent.name
        except AttributeError:
            return
        if pack != self.character.pack:
            return  # 기본 녹음 등 다른 목소리(팩에 없는 알림은 기본 녹음으로 대신 남)
        self.affinity.alerted(today())  # 알림 누적(50→75 퀘스트) + 오늘 3번까지 +1
        self._save_affinity()
        if self.window is not None:
            self.window.brain.notify(self._clock())
            picker = self.picker()
            if picker is not None:
                self.window.say(picker.alert(path.name))
