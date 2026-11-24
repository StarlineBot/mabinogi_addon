"""캐릭터 대사 목소리 재생(docs/character-pet-spec.md '대사 목소리 재생', 사용자 11-24).

- 말풍선 줄의 `voice`(팩 폴더 기준 상대 경로) 파일이 **고른 캐릭터의 팩 폴더에 실제로 있을 때만** 재생 — 기본 녹음으로 폴백 안 함.
- 음량 = 설정의 알림 음량(0%면 안 냄). 알림 소리가 나오는 중이면 건너뜀(말풍선은 그대로), 대사 중 알림이 오면 대사를 멈춤
  (컨트롤러가 notifier.on_play에서 stop). 새 말풍선이 뜨면 앞 소리를 멈추고 새 것.
- 소리 길이를 알면(durationChanged) on_duration(초)로 알려 말하기 그림을 그만큼 유지한다.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QUrl

_log = logging.getLogger(__name__)


def voice_file(pack: str, voice: str | None) -> Path | None:
    """그 팩 폴더 안 대사 목소리 파일(있을 때만)."""
    if not pack or not voice:
        return None
    from .notifier import SOUND_DIR

    path = SOUND_DIR / pack / voice
    try:
        path.resolve().relative_to((SOUND_DIR / pack).resolve())  # 팩 밖으로 나가는 경로는 쓰지 않음
    except (ValueError, OSError):
        return None
    return path if path.is_file() else None


class VoiceLinePlayer(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = None
        self._audio = None
        self.on_duration = None   # (초) → 말하기 그림 유지

    def _ensure(self) -> bool:
        if self._player is not None:
            return True
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._audio = QAudioOutput(self)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._audio)
            self._player.durationChanged.connect(self._duration)
            return True
        except Exception:  # noqa: BLE001 — 오디오 없음 → 말풍선만
            _log.debug("대사 목소리 재생기 만들기 실패", exc_info=True)
            self._player = None
            return False

    def play(self, path: Path) -> bool:
        """재생 시작이면 True. 알림이 나오는 중이거나 음량 0이면 건너뜀."""
        from .notifier import _sync_default_device, alert_playing, effective_volume, master_volume

        if alert_playing():
            return False
        volume = effective_volume(1.0, master_volume())
        if volume <= 0 or not self._ensure():
            return False
        self.stop()
        _sync_default_device(self._audio)
        self._audio.setVolume(volume)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        return True

    def stop(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:  # noqa: BLE001
                pass

    def _duration(self, ms: int) -> None:
        if ms > 0 and self.on_duration is not None:
            self.on_duration(ms / 1000.0)
