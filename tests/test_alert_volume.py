"""0.38.0 전체 알림 음량(설정 › 일반 › 알림 음량): 최종 음량 = 소리별 기본값 × 전체 음량."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui import notifier


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(notifier, "_master_volume", None)
    yield


@pytest.mark.parametrize("raw,expected", [(100, 100), (0, 0), (55, 55), (-10, 0), (250, 100), (42.6, 43),
                                          ("x", 100), (None, 100), (True, 100)])
def test_clamp(raw, expected):
    assert config.clamp_alert_volume(raw) == expected


def test_effective_volume_keeps_relative_balance():
    assert notifier.effective_volume(0.8, 100) == pytest.approx(0.8)  # 100% = 지금과 같음
    assert notifier.effective_volume(0.8, 50) == pytest.approx(0.4)
    assert notifier.effective_volume(0.6, 50) == pytest.approx(0.3)
    assert notifier.effective_volume(0.5, 0) == 0.0  # 0% = 무음
    assert notifier.effective_volume(1.5, 120) == pytest.approx(1.0)  # 범위 밖 보정


def test_default_is_100_and_saved_value_restored():
    assert config.load_alert_volume() == 100 and notifier.master_volume() == 100
    config.save_alert_volume(35)
    assert config.load_alert_volume() == 35
    notifier._master_volume = None
    assert notifier.master_volume() == 35


def _vol(audio):
    """테스트 격리(test_support.boundaries)의 가짜 출력은 _volume에, 실제 QAudioOutput은 volume()에."""
    return audio._volume if hasattr(audio, "_volume") else audio.volume()


def test_change_applies_to_running_players():
    a = notifier.SoundNotifier({}, volume=0.8)  # 보스·헤일로
    b = notifier.SoundNotifier({}, volume=0.6)  # 파티·게임창
    if a._audio is None:
        pytest.skip("QtMultimedia 없음")
    assert _vol(a._audio) == pytest.approx(0.8) and _vol(b._audio) == pytest.approx(0.6)
    assert notifier.set_master_volume(50) == 50
    assert _vol(a._audio) == pytest.approx(0.4) and _vol(b._audio) == pytest.approx(0.3)
    assert config.load_alert_volume() == 50
    c = notifier.SoundNotifier({}, volume=1.0)  # 새로 만든 재생기도 전체 음량을 따름
    assert _vol(c._audio) == pytest.approx(0.5)
    notifier.set_master_volume(0)
    assert _vol(a._audio) == 0 and _vol(c._audio) == 0
    notifier.set_master_volume(100)
    assert _vol(a._audio) == pytest.approx(0.8)


def test_module_players_follow_master(monkeypatch):
    class Audio:
        def __init__(self):
            self.v = 1.0

        def setVolume(self, v):
            self.v = v

    class Player:
        _audio = Audio()

    player = Player()
    monkeypatch.setattr(notifier, "_update_player", player)
    notifier.set_master_volume(30)
    assert player._audio.v == pytest.approx(0.3)


def test_settings_slider_saves_on_release_and_snaps():
    from types import SimpleNamespace
    from mabinogi_addon.ui.settings_tab import SettingsTab
    tab = SettingsTab(SimpleNamespace(is_game_active=lambda: False, is_self_active=lambda: False,
                                      set_game_exe=lambda *_: None))
    try:
        s = tab._alert_volume
        assert s.value() == 100 and tab._alert_volume_label.text() == "100%"
        s.setValue(62)  # 키보드 등: 5단위로 맞추고 바로 저장
        assert s.value() == 60 and tab._alert_volume_label.text() == "60%"
        assert config.load_alert_volume() == 60 and notifier.master_volume() == 60
    finally:
        tab.close()
