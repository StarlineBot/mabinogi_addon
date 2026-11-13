"""종료 알림 사운드 재생 (기획서 3.3).

만료임박(EXPIRING) 알림이 발생한 버프의 사운드 파일을 재생한다.
TTS는 나중에 붙인다 — 지금은 미리 녹음한 mp3를 buff_id별로 매핑해 재생.

QtMultimedia(QMediaPlayer)로 재생한다. mp3라 QSoundEffect(WAV 전용)는 못 쓴다.
QtMultimedia가 없거나 백엔드가 없으면(헤드리스 등) 조용히 no-op.
재생은 메인 스레드에서(BuffController.on_alert 콜백) 호출된다.
"""

from __future__ import annotations

import weakref

from pathlib import Path

from PySide6.QtCore import QObject, QUrl

from .. import paths

SOUND_DIR = paths.resource_dir() / "sounds"
# 파티 키워드 알림 효과음(있으면 재생, 없으면 호출 측에서 시스템 비프로 폴백).
PARTY_ALERT_FILE = SOUND_DIR / "파티 알림.mp3"
CREATOR_DIALOGUE_SOUND_FILE = SOUND_DIR / "제작자 잡담.mp3"


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


def second_sound_map() -> dict[str, Path]:
    """2차(막차) 알림용 buff_id → 경로.

    각 버프의 'OOO 연장2.mp3'(1차 파일명 뒤에 '2')가 활성 팩/기본에 있으면 그걸,
    없으면 1차 파일로 폴백한다(2차 녹음 전엔 1차 소리가 그대로 나오게). 둘 다 없으면 제외.
    """
    out: dict[str, Path] = {}
    for bid, name in DEFAULT_SOUNDS.items():
        p2 = sound_path(name[:-4] + "2.mp3")  # ".mp3"(4글자) → "2.mp3"
        if p2.exists():
            out[bid] = p2
            continue
        p1 = sound_path(name)
        if p1.exists():
            out[bid] = p1
    return out


# ---- 전체 알림 음량(0.38.0, 설정 › 일반 › 알림 음량) ---------------------------------------------
# 최종 음량 = 소리별 기본값(보스·헤일로 0.8, 파티·게임창 0.6 …) × 전체 음량. 상대 균형은 그대로, 0%면 무음.
_master_volume: int | None = None  # 0~100(처음 쓸 때 설정에서 읽음)
_live = weakref.WeakSet()  # 살아 있는 SoundNotifier(전체 음량을 바꾸면 바로 반영)


def effective_volume(base: float, master_percent) -> float:
    """소리별 기본값(0~1) × 전체 음량(0~100%) → 0~1."""
    from .. import config

    base = max(0.0, min(1.0, float(base)))
    return base * config.clamp_alert_volume(master_percent) / 100


def master_volume() -> int:
    global _master_volume
    if _master_volume is None:
        from .. import config

        _master_volume = config.load_alert_volume()
    return _master_volume


def set_master_volume(percent) -> int:
    """설정에서 바꿈: 저장하고 실행 중 재생기 모두에 바로 적용. 정리된 값(0~100)을 돌려준다."""
    global _master_volume
    from .. import config

    _master_volume = config.clamp_alert_volume(percent)
    config.save_alert_volume(_master_volume)
    for notifier in list(_live):
        notifier.apply_master_volume()
    for player in (_update_player, *_gone_players.values(), _blackbox_player):
        _set_player_volume(player)
    return _master_volume


def _set_player_volume(player) -> None:
    """모듈 일회성 재생기(업데이트·사라짐 경고·블랙박스, 기본값 1.0)에 전체 음량 반영."""
    if player is None:
        return
    try:
        player._audio.setVolume(effective_volume(1.0, master_volume()))
    except Exception:  # noqa: BLE001
        pass


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
        _sync_default_device(_update_player._audio)
        _set_player_volume(_update_player)  # 전체 알림 음량  # 지금 쓰는 출력 장치로 맞춤
        _update_player.setSource(QUrl.fromLocalFile(str(path)))
        _update_player.play()
        return True
    except Exception:  # noqa: BLE001 — 오디오 없으면 무음(알림은 배너·토스트로도 뜸)
        return False


# 사라짐 경고 효과음(assets/sounds/에 이 이름으로 두면 재생, 없으면 조용히 생략).
WARN_GONE_SOUND_FILE = "버프 사라짐.mp3"
# 디버프가 보스에서 떨어짐 — 버프 사라짐과 구분되는 소리(사용자 11-08, tests/data/universfield-new-notification-035-485894.mp3)
DEBUFF_GONE_SOUND_FILE = "디버프 사라짐.mp3"
_gone_players: dict[str, object] = {}  # 소리별 일회성 재생기(모듈에 보관해 재생 전 GC 방지, 버프·디버프가 서로 끊지 않게 따로)


def stop_warn_gone_sound():
    for player in _gone_players.values():
        try:
            player.stop()
        except Exception:
            pass


def _play_gone(filename: str) -> bool:
    path = sound_path(filename)
    if not path.exists():
        return False
    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        player = _gone_players.get(filename)
        if player is None:
            audio = QAudioOutput()
            player = QMediaPlayer()
            player.setAudioOutput(audio)
            player._audio = audio  # 오디오 출력도 함께 보관(재생 중 끊김 방지)
            _gone_players[filename] = player
        _sync_default_device(player._audio)  # 지금 쓰는 출력 장치로 맞춤
        _set_player_volume(player)  # 전체 알림 음량
        player.setSource(QUrl.fromLocalFile(str(path)))
        player.play()
        return True
    except Exception:  # noqa: BLE001 — 오디오 없으면 무음(시각 경고는 그대로 뜸)
        return False


# 알람(alarm-spec 2절): 사용자가 넣는 파일 — 없으면 기본 알림음(파티 알림과 같은 소리)
ALARM_SOUND_FILE = "알람.mp3"  # 시각 알람·미리 알림
TIMER_SOUND_FILE = "타이머.mp3"  # 몇 분 뒤 타이머
ALARM_FALLBACK_SOUND_FILE = "파티 알림.mp3"


def alarm_sound_file(kind: str) -> str:
    """kind: 'time'|'pre'|'timer' → 재생할 파일 이름(넣은 파일이 없으면 기본 알림음)."""
    name = TIMER_SOUND_FILE if kind == "timer" else ALARM_SOUND_FILE
    return name if sound_path(name).exists() else ALARM_FALLBACK_SOUND_FILE


def play_alarm_sound(kind: str) -> bool:
    """알람 소리 — 전투 보조 일시정지와 무관하게 늘 울린다. 음량은 앱 알림 음량."""
    return _play_gone(alarm_sound_file(kind))


def play_warn_gone_sound() -> bool:
    """사라짐 경고 버프가 사라졌을 때 효과음 재생. 파일/오디오 없으면 False."""
    return _play_gone(WARN_GONE_SOUND_FILE)


def play_debuff_gone_sound() -> bool:
    """사라짐 경고 디버프가 보스에서 떨어졌을 때 효과음 — 버프 사라짐과 다른 소리. 파일/오디오 없으면 False."""
    return _play_gone(DEBUFF_GONE_SOUND_FILE)


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
        self._loaded: str | None = None  # 지금 재생기에 열려 있는 파일(같은 파일이면 다시 열지 않음)
        self._base_volume = max(0.0, min(1.0, volume))  # 소리별 기본값(전체 음량을 곱하기 전)
        _live.add(self)
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._audio = QAudioOutput(self)
            self._audio.setVolume(effective_volume(volume, master_volume()))  # 기본값 × 전체 알림 음량
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._audio)
        except Exception:  # noqa: BLE001 — QtMultimedia/백엔드 없음 → 무음
            self._player = None

    def apply_master_volume(self) -> None:
        if self._audio is not None:
            try:
                self._audio.setVolume(effective_volume(self._base_volume, master_volume()))
            except Exception:  # noqa: BLE001
                pass

    def set_sounds(self, sounds: dict[str, Path]) -> None:
        self._sounds = dict(sounds)

    def stop(self) -> None:
        """Stop owned playback before feature revocation or shutdown."""
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass

    def _load(self, path: Path) -> None:
        """그 파일을 재생기에 연다 — 이미 열려 있으면 다시 열지 않는다(0.48.0: Windows Media Foundation이 매번 파일을
        다시 열어 소리가 늦던 것). 같은 소리를 다시 낼 땐 처음 위치로만 돌린다."""
        key = str(path)
        if key != self._loaded:
            self._player.setSource(QUrl.fromLocalFile(key))
            self._loaded = key
        else:
            self._player.setPosition(0)

    def prepare(self, buff_id: str) -> bool:
        """미리 열어 두기(첫 재생도 바로). 재생은 하지 않는다."""
        if self._player is None:
            return False
        path = self._sounds.get(buff_id)
        if path is None or not path.exists():
            return False
        if str(path) != self._loaded:
            self._load(path)
        return True

    def play(self, buff_id: str) -> bool:
        """해당 버프 사운드 재생. 재생 시도하면 True."""
        if self._player is None:
            return False
        path = self._sounds.get(buff_id)
        if path is None or not path.exists():
            return False
        _sync_default_device(self._audio)  # 지금 쓰는 출력 장치로 맞춤
        self._load(path)
        self._player.play()
        return True

    def alert(self, buff_ids) -> None:
        """여러 버프가 동시에 울리면 첫 번째만 재생(겹치면 마지막만 들림)."""
        for bid in buff_ids:
            if self.play(bid):
                return


# 블랙박스 저장 반응 효과음(블랙박스 명세 11.1). 접수 즉시 1회, 실패는 구분되는 소리. 완료는 문구만.
# 파일은 검토 후 assets/sounds/에 이 이름으로 추가한다. 없으면 조용히 생략(문구 오버레이는 그대로).
BLACKBOX_SOUND_FILES = {"accepted": "블랙박스 저장 접수.mp3", "failed": "블랙박스 저장 실패.mp3"}
_blackbox_player = None


def play_blackbox_sound(kind: str) -> bool:
    global _blackbox_player
    name = BLACKBOX_SOUND_FILES.get(kind)
    path = sound_path(name) if name else None
    if path is None or not path.exists():
        return False
    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        if _blackbox_player is None:
            audio = QAudioOutput()
            player = QMediaPlayer()
            player.setAudioOutput(audio)
            player._audio = audio
            _blackbox_player = player
        _sync_default_device(_blackbox_player._audio)
        _set_player_volume(_blackbox_player)  # 전체 알림 음량
        _blackbox_player.setSource(QUrl.fromLocalFile(str(path)))
        _blackbox_player.play()
        return True
    except Exception:  # noqa: BLE001 — 오디오 없으면 무음(문구 오버레이는 뜸)
        return False
