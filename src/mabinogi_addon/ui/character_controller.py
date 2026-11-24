"""캐릭터 컨트롤러 — 고른 캐릭터의 호감도·대사·펫 창을 묶는다(docs/character-pet-spec.md 2·3절).

- 앱을 켜면: 그날 처음이면 호감도 +3, 펫이 떠 있으면 인사(오랜만·밤·아침·보통).
- 알림 소리(notifier.on_play)가 고른 캐릭터 목소리 팩이면: 호감도 +1(하루 7번), 펫은 알아챔 + 같은 뜻 말풍선.
- 펫 사건: 말풍선(상황별 무작위·같은 줄 연속 금지), 클릭 반복 −1 + 짜증, 쓰다듬기 끝까지 +2(다 채운 뒤 또 → −1),
  구석에서 함께 30분 +1(하루 4번), 끌어서 정한 구석 저장.
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
from ..character.brain import Brain, Floor
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
        self.enabled = False
        self._started = False
        self._lines: dict[str, Picker] = {}
        self._feeds: dict = {}
        self.character = roster.by_pack(config.load_voice_pack())
        self.affinity = self._load_affinity()
        from .notifier import on_play
        on_play(self._on_sound)

    # ---- 시작·바뀜 ---------------------------------------------------------------------------
    def set_enabled(self, on: bool) -> None:
        """제작자 권한이 바뀜(로그인·로그아웃). 꺼지면 펫을 닫는다."""
        self.enabled = bool(on)
        if self._started or not self.enabled:
            self.sync_window()

    def reload_affinity(self) -> None:
        """제작자가 캐릭터 탭에서 호감도를 바꿈 → 저장 값으로 다시 읽는다."""
        self.affinity = self._load_affinity()

    def start(self, now: datetime.datetime | None = None) -> None:
        self._started = True
        if not self.enabled:
            return
        now = now or datetime.datetime.now()
        last = config.load_pet_last_seen()
        hello = greeting(last, now)
        if self.affinity is not None and self.affinity.gain("launch", today(now)):
            self._save_affinity()
        config.save_character(lastSeen=today(now))
        self.sync_window()
        if hello and self.window is not None:
            self.window.say(self.picker().pick(hello) if self.picker() else None)

    def voice_changed(self) -> None:
        self.character = roster.by_pack(config.load_voice_pack())
        self.affinity = self._load_affinity()
        self.sync_window()

    def sync_window(self) -> None:
        """펫 창을 켜야 하면 만들고, 아니면 닫는다."""
        want = (self.enabled and config.load_pet_on() and self.character is not None
                and self.character.has_pet)
        if want and self.window is None:
            self.window = self._make_window()
            if self.window is not None:
                self.window.start()
        elif not want and self.window is not None:
            self.window.stop()
            self.window.deleteLater()
            self.window = None

    def shutdown(self) -> None:
        from .notifier import off_play
        off_play(self._on_sound)
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

    def picker(self) -> Picker | None:
        if self.character is None or not self.character.has_pet:
            return None
        key = self.character.card.split("/")[0]
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

        frames = load_frames(self.character.card.split("/")[0])
        if not frames:
            _log.warning("펫 그림을 찾지 못함 — 펫 창 안 띄움")
            return None
        area = QGuiApplication.primaryScreen().availableGeometry()
        floor = Floor(area.left(), area.right(), area.bottom())
        corner = config.load_pet_corner()
        if corner is not None and not area.adjusted(-40, -40, 40, 40).contains(*corner):
            corner = None  # 해상도가 바뀌어 화면 밖이면 기본 구석(바닥 오른쪽 끝)
        brain = Brain(floor, corner=corner)
        game = (lambda: self._watcher.is_game_active()) if self._watcher is not None else (lambda: False)
        window = PetWindow(brain, frames, self.character.color, game_front=game, clock=self._clock)
        window.events.connect(self._on_events)
        return window

    # ---- 사건 --------------------------------------------------------------------------------
    def _on_events(self, events: list) -> None:
        now = self._clock()
        picker = self.picker()
        for event in events:
            kind = event[0]
            if kind == "say" and picker is not None and self.window is not None:
                self.window.say(picker.pick(event[1]))
            elif kind == "click" and self.affinity is not None:
                if self.affinity.click(now):
                    self._save_affinity()
                    if picker is not None and self.window is not None:
                        self.window.say(picker.pick("annoyed_click"))
            elif kind == "pet_done" and self.affinity is not None:
                result = self.affinity.petted(now, today())
                if result != "none":
                    self._save_affinity()
                if result == "annoyed" and picker is not None and self.window is not None:
                    self.window.say(picker.pick("annoyed_pet"))
            elif kind == "corner_time" and self.affinity is not None:
                if self.affinity.gain("corner", today()):
                    self._save_affinity()
            elif kind == "corner_saved":
                config.save_character(corner={"x": round(event[1]), "y": round(event[2])})

    def _on_sound(self, _buff_id: str, path) -> None:
        """알림 소리 → 그 캐릭터 목소리면 호감도 +1·알아챔·말풍선."""
        if not self.enabled or self.character is None or self.affinity is None:
            return
        try:
            pack = path.parent.name
        except AttributeError:
            return
        if pack != self.character.pack:
            return  # 기본 녹음 등 다른 목소리(팩에 없는 알림은 기본 녹음으로 대신 남)
        if self.affinity.gain("alert", today()):
            self._save_affinity()
        if self.window is not None:
            self.window.brain.notify(self._clock())
            picker = self.picker()
            if picker is not None:
                self.window.say(picker.alert(path.name))
