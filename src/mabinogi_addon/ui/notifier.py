"""종료 알림 사운드 재생 (기획서 3.3).

만료임박(EXPIRING) 알림이 발생한 버프의 사운드 파일을 재생한다.
TTS는 나중에 붙인다 — 지금은 미리 녹음한 mp3를 buff_id별로 매핑해 재생.

QtMultimedia(QMediaPlayer)로 재생한다. mp3라 QSoundEffect(WAV 전용)는 못 쓴다.
QtMultimedia가 없거나 백엔드가 없으면(헤드리스 등) 조용히 no-op.
재생은 메인 스레드에서(BuffController.on_alert 콜백) 호출된다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl

from ..config import PROJECT_ROOT

SOUND_DIR = PROJECT_ROOT / "tests" / "data" / "default"

# buff_id → 사운드 파일명(개발 자산). 배포 때 패키지 자산으로 옮긴다.
DEFAULT_SOUNDS: dict[str, str] = {
    "vivace": "비바체 연장.mp3",
    "sharp": "상태지원 알림.mp3",
    "han_adrenaline": "햄 버닝 연장.mp3",
    "march": "행진곡 연장.mp3",
}


def default_sound_map() -> dict[str, Path]:
    """존재하는 사운드 파일만 buff_id → 경로로."""
    out: dict[str, Path] = {}
    for bid, name in DEFAULT_SOUNDS.items():
        path = SOUND_DIR / name
        if path.exists():
            out[bid] = path
    return out


class SoundNotifier(QObject):
    """buff_id별 알림 사운드 재생기. 사운드 꺼진 버프는 호출 측에서 걸러준다."""

    def __init__(self, sounds: dict[str, Path], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sounds = dict(sounds)
        self._player = None
        self._audio = None
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._audio = QAudioOutput(self)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._audio)
        except Exception:  # noqa: BLE001 — QtMultimedia/백엔드 없음 → 무음
            self._player = None

    def set_sounds(self, sounds: dict[str, Path]) -> None:
        self._sounds = dict(sounds)

    def play(self, buff_id: str) -> bool:
        """해당 버프 사운드 재생. 재생 시도하면 True."""
        if self._player is None:
            return False
        path = self._sounds.get(buff_id)
        if path is None or not path.exists():
            return False
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        return True

    def alert(self, buff_ids) -> None:
        """여러 버프가 동시에 울리면 첫 번째만 재생(겹치면 마지막만 들림)."""
        for bid in buff_ids:
            if self.play(bid):
                return
