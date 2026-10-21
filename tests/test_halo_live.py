"""Live battle continuity, role split and isolated halo sound regressions."""

from pathlib import Path, PureWindowsPath
import hashlib

import pytest
from PySide6.QtCore import QObject

from mabinogi_addon import config, paths
import mabinogi_addon.ui.halo_capture_section as module
from mabinogi_addon.ui import notifier
from test_halo_presentation import creator_section, window


def live_section(window, monkeypatch):
    w, app, section = creator_section(window, monkeypatch)
    monkeypatch.setattr(section._watcher, 'is_game_active', lambda: True)
    monkeypatch.setattr(section._watcher, 'is_self_active', lambda: False)
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    section._target = (11,22,0,0,1920,1080)
    for moment,raw in ((100,838),(100.5,838),(101,837)):
        now[0] = moment
        section.set_boss_context('lenen_miir_hoehan')
        section._monitor(raw)
    assert section._clock.anchor == (837,101)
    return w, app, section, now


@pytest.mark.parametrize('output', ['countdown', 'warning'])
def test_confirmed_battle_keeps_outputs_while_timer_advances_without_boss_bar(window, monkeypatch, output):
    _, _, section, now = live_section(window,monkeypatch)
    alerts = []
    monkeypatch.setattr(section._warning,'show_message',lambda *args:alerts.append(args))
    now[0] = 102
    section.set_boss_context(None)
    section._monitor(836)
    if output == 'countdown':
        assert section._countdown.isVisible()
    else:
        now[0] = 103
        section.set_boss_context(None)
        section._monitor(835)
        assert alerts == [('헤일로 5초 전',5000)]
    assert not section._target_boss_active()  # Collection remains gated separately.
    section._store(None)
    assert section._session is None


@pytest.mark.parametrize('boundary', ['process','other_boss','missing','pause','logout'])
def test_live_battle_stops_or_suspends_at_real_boundaries(window,monkeypatch,boundary):
    w, _, s, now = live_section(window,monkeypatch)
    now[0] = 102
    s.set_boss_context(None)
    raw = 836
    if boundary == 'process':
        s._target = (55,66,0,0,1920,1080)
    elif boundary == 'other_boss':
        s.set_boss_context('lenen_miir')
    elif boundary == 'missing':
        raw = None
    elif boundary == 'pause':
        w._paused = True
    else:
        monkeypatch.setattr(config,'load_discord_user',lambda:None)
    s._monitor(raw)
    assert not s._countdown.isVisible() and not s._warning.isVisible()
    if boundary == 'pause':
        assert s._battle_target is not None and s._clock.armed
        assert s._clock.last_remaining == raw  # Keep observing; pause must not shift the clock.
    elif boundary != 'missing':
        assert s._battle_target is None and not s._clock.armed
    else:
        assert s._clock.last_remaining is None


@pytest.fixture
def recorded_audio(monkeypatch):
    players = []
    class RecordingNotifier(QObject):
        def __init__(self,sounds,parent=None,volume=1):
            super().__init__(parent)
            self.sounds = sounds
            self.calls = []
            self.stopped = False
            players.append(self)
        def play(self,key):
            self.calls.append(key)
            return True
        def stop(self):
            self.stopped = True
    monkeypatch.setattr(notifier,'SoundNotifier',RecordingNotifier)
    return players


def test_beta_can_read_and_warn_but_cannot_collect(window,monkeypatch,tmp_path,recorded_audio):
    w, _, s, now = live_section(window,monkeypatch)
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':'ordinary-beta'})
    s._root = tmp_path / 'no-collection'
    s._refresh()
    assert w.boss_tab.pattern_tabs.isTabVisible(1)
    assert s.region_btn.isEnabled() and not s.disclosure.isVisible()
    assert not s._collect_allowed() and s._allowed()
    s.collect.setChecked(True)
    assert not s.collect.isChecked() and s._session is None
    s._snapshot()
    s._store(None)
    assert not s._root.exists()
    s.sound.setChecked(True)
    now[0] = 103
    s.set_boss_context(None)
    s._monitor(835)
    assert s._countdown.isVisible() and s._warning.isVisible()
    assert recorded_audio[0].calls == ['halo']
    s._monitor(835)
    assert recorded_audio[0].calls == ['halo'] and len(recorded_audio)==1
    monkeypatch.setattr(config,'load_discord_user',lambda:None)
    s._tick()
    assert s.isHidden() and not s._countdown.isVisible()
    assert recorded_audio[0].stopped and s._notifier is None


@pytest.mark.parametrize('sound_on', [False, True])
def test_preview_is_independent_of_battle_and_respects_sound(window,monkeypatch,recorded_audio,sound_on):
    _, _, s = creator_section(window,monkeypatch)
    monkeypatch.setattr(s,'_capture',lambda:None)
    s.sound.setChecked(sound_on)
    fired = set(s._clock.fired)
    s.preview_alert.click()
    assert s._warning.isVisible()
    s._tick()
    assert s._warning.isVisible() and s._clock.fired==fired
    assert len(recorded_audio)==int(sound_on)
    if sound_on:
        assert recorded_audio[0].calls==['halo']
        s.sound.setChecked(False)
        assert recorded_audio[0].stopped


@pytest.mark.parametrize('failure', ['init','play','missing','backend_false'])
def test_audio_failure_cannot_stop_visual_warning(window,monkeypatch,tmp_path,failure):
    _, _, s, now = live_section(window,monkeypatch)
    s.sound.setChecked(True)
    def fail(*args,**kwargs):
        raise RuntimeError('controlled decoder failure')
    if failure == 'init':
        monkeypatch.setattr(notifier,'SoundNotifier',fail)
    elif failure == 'play':
        monkeypatch.setattr(notifier.SoundNotifier,'play',fail)
    elif failure == 'missing':
        monkeypatch.setattr(paths,'resource_dir',lambda:tmp_path)
    else:
        monkeypatch.setattr(notifier.SoundNotifier,'play',lambda *a:False)
    now[0] = 103
    s.set_boss_context(None)
    s._monitor(835)
    assert s._warning.isVisible() and s._countdown.isVisible() and s._clock.armed
    assert (s._notifier is None) == (failure != 'backend_false')


def test_creator_to_beta_revokes_only_collection(window,monkeypatch):
    _, _, s, _ = live_section(window,monkeypatch)
    s.collect.setChecked(True)
    session = s._session
    assert session is not None
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':'ordinary-beta'})
    monkeypatch.setattr(s,'_capture',lambda:None)
    s._tick()
    assert session.cancelled.is_set() and not s.collect.isChecked()
    assert not s.isHidden() and s.region_btn.isEnabled()
    assert not s.disclosure.isVisible()


def test_dedicated_notifier_does_not_interrupt_other_sound(window,monkeypatch):
    _, _, s = creator_section(window,monkeypatch)
    source = paths.resource_dir()/'sounds/헤일로 알림.mp3'
    other = notifier.SoundNotifier({'other':source}, parent=s)
    try:
        assert other.play('other')
        s.sound.setChecked(True)
        s.preview_alert.click()
        assert s._notifier is not other
        actual = Path(s._notifier._player.source().toLocalFile())
        assert actual == source
        assert actual != source.with_name('other.mp3')
        assert actual != source.parent.parent/source.name
        assert other._player._playing
        s.sound.setChecked(False)
        assert other._player._playing
    finally:
        other.stop()
        other.deleteLater()


def test_windows_sound_path_representation_preserves_full_identity():
    source = PureWindowsPath('D:/a/app/assets/sounds/헤일로 알림.mp3')
    qt_path = source.as_posix()
    assert qt_path != str(source)
    actual = PureWindowsPath(qt_path)
    assert actual == source
    assert actual != source.with_name('other.mp3')
    assert actual != source.parent.parent/source.name


def test_uploaded_sound_is_bundled_losslessly():
    source = Path(__file__).parent/'data/universfield-new-notification-014-363678.mp3'
    packaged = paths.resource_dir()/'sounds/헤일로 알림.mp3'
    assert hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(packaged.read_bytes()).digest()


def test_default_order_size_and_saved_positions_are_stable(window,monkeypatch):
    w, _, s = creator_section(window,monkeypatch)
    assert s._warning._font_px==round(w.boss_tab._overlay._font_px*.85)
    assert not s._warning._bold and w.boss_tab._overlay._bold
    for _ in range(20):
        s._place_warning()
        assert s._warning.y()==s._countdown.y()+s._countdown.height()+8
    s._countdown.move(-80,100)
    s._save_countdown_position()
    s._warning.move(300,-30)
    s._save_warning_position()
    s._place_warning()
    assert (s._countdown.x(),s._countdown.y())==(-80,100)
    assert (s._warning.x(),s._warning.y())==(300,-30)
