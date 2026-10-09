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

from .. import paths

SOUND_DIR = paths.resource_dir() / "sounds"
# 파티 키워드 알림 효과음(있으면 재생, 없으면 호출 측에서 시스템 비프로 폴백).
PARTY_ALERT_FILE = SOUND_DIR / "파티 알림.mp3"


def _sync_default_device(audio) -> None:
    """출력 장치를 현재 시스템 기본으로 맞춘다(헤드셋/스피커 전환 따라가기).

    QAudioOutput은 '생성 시점'의 기본 장치에 고정된다. 재생기들이 서로 다른 때 만들어져
    중간에 장치가 바뀌면(헤드셋 꽂기 등) 어떤 소리는 옛 장치로 나간다. 재생 직전에 현재
    기본 출력으로 다시 설정해, 모든 알림이 지금 쓰는 장치로 일관되게 나오게 한다.
    """
    if audio is None:
        return
    try:
        from PySide6.QtMultimedia import QMediaDevices

        audio.setDevice(QMediaDevices.defaultAudioOutput())
    except Exception:  # noqa: BLE001, S110 — 장치 동기화 실패해도 재생은 계속
        pass


def list_voice_packs() -> list[str]:
    """사용 가능한 목소리 팩(하위 폴더) 이름들. 기본(녹음본)은 flat이라 제외."""
    if not SOUND_DIR.exists():
        return []
    return sorted(p.name for p in SOUND_DIR.iterdir() if p.is_dir())


def sound_path(filename: str) -> Path:
    """활성 목소리 팩에 그 파일이 있으면 그 경로, 없으면 기본(flat) 경로.

    팩은 '같은 파일명, 다른 음성·말투' 묶음이라 폴더만 바뀐다. 팩에 없는 알림은
    기본 녹음본으로 폴백한다.
    """
    from .. import config

    pack = config.load_voice_pack()
    if pack:
        candidate = SOUND_DIR / pack / filename
        if candidate.exists():
            return candidate
    return SOUND_DIR / filename

# buff_id → 사운드 파일명(개발 자산). 배포 때 패키지 자산으로 옮긴다.
DEFAULT_SOUNDS: dict[str, str] = {
    "vivace": "비바체 연장.mp3",
    "sharp": "상태지원 알림.mp3",
    "han_adrenaline": "햄 버닝 연장.mp3",
    "march": "행진곡 연장.mp3",
    "overture_of_the_battlefield": "전장의 서곡 연장.mp3",
}


def default_sound_map() -> dict[str, Path]:
    """존재하는 사운드 파일만 buff_id → 경로로(활성 목소리 팩 우선)."""
    out: dict[str, Path] = {}
    for bid, name in DEFAULT_SOUNDS.items():
        path = sound_path(name)
        if path.exists():
            out[bid] = path
    return out


# 새 버전 감지 알림 효과음(assets/sounds/에 이 이름으로 두면 재생, 없으면 조용히 생략).
UPDATE_SOUND_FILE = "업데이트 알림.mp3"
_update_player = None  # 일회성 재생기(모듈에 보관해 재생 전 GC 방지)


def play_update_sound() -> bool:
    """새 버전 감지 시 알림 효과음 재생. 파일 없거나 오디오 백엔드 없으면 False."""
    global _update_player
    path = sound_path(UPDATE_SOUND_FILE)
    if not path.exists():
        return False
    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        if _update_player is None:
            audio = QAudioOutput()
            player = QMediaPlayer()
            player.setAudioOutput(audio)
            player._audio = audio  # 오디오 출력도 함께 보관(재생 중 끊김 방지)
            _update_player = player
        _sync_default_device(_update_player._audio)  # 지금 쓰는 출력 장치로 맞춤
        _update_player.setSource(QUrl.fromLocalFile(str(path)))
        _update_player.play()
        return True
    except Exception:  # noqa: BLE001 — 오디오 없으면 무음(알림은 배너·토스트로도 뜸)
        return False


class SoundNotifier(QObject):
    """buff_id별 알림 사운드 재생기. 사운드 꺼진 버프는 호출 측에서 걸러준다."""

    def __init__(
        self,
        sounds: dict[str, Path],
        parent: QObject | None = None,
        volume: float = 1.0,
    ) -> None:
        super().__init__(parent)
        self._sounds = dict(sounds)
        self._player = None
        self._audio = None
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._audio = QAudioOutput(self)
            self._audio.setVolume(max(0.0, min(1.0, volume)))  # 0.0~1.0
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
        _sync_default_device(self._audio)  # 지금 쓰는 출력 장치로 맞춤
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        return True

    def alert(self, buff_ids) -> None:
        """여러 버프가 동시에 울리면 첫 번째만 재생(겹치면 마지막만 들림)."""
        for bid in buff_ids:
            if self.play(bid):
                return
