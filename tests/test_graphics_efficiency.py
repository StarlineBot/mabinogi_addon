"""그래픽 효율 최적화(최적화 명세 13.6): NVIDIA 프로필 최대 프레임 400, 사용자 값 존중, 끌 때 원복, 화면."""
import json
from contextlib import contextmanager

import pytest

from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.optimization.result_summary import summarize
from mabinogi_addon.optimization.session import Recovery
from mabinogi_addon.system import nvidia_drs
from mabinogi_addon.system.nvidia_drs import FRL_FPS_ID, OWN_PROFILE, FrameLimit
from mabinogi_addon.ui import optimization_controller as module
from test_navigation import window  # noqa: F401  (픽스처)
from test_optimization import Backend, TARGET, _wait

EXE = 'client.exe'


# ---- NVAPI 논리(가짜 드라이버) ----

class FakeDrs:
    def __init__(self, apps=None):
        self.profiles = {'Mabinogi': {'apps': set(apps or ()), 'settings': {}}}
        self.saved = 0

    @contextmanager
    def session(self):
        yield 'session'

    def find_application(self, session, name):
        exact = next((p for p, v in self.profiles.items() if name in v['apps']), None)  # 전체 경로 등록이 더 구체적
        if exact is not None:
            return exact
        name = name.lower().replace('/', '\\').rsplit('\\', 1)[-1]
        return next((p for p, v in self.profiles.items() if name in v['apps']), None)

    def find_profile(self, session, name):
        return name if name in self.profiles else None

    def profile_name(self, session, profile):
        return profile

    def create_profile(self, session, name):
        self.profiles[name] = {'apps': set(), 'settings': {}}
        return name

    def delete_profile(self, session, profile):
        del self.profiles[profile]

    def add_application(self, session, profile, name):
        self.profiles[profile]['apps'].add(name)

    def get_setting(self, session, profile, setting_id):
        return self.profiles[profile]['settings'].get(setting_id)

    def set_setting(self, session, profile, setting_id, value):
        self.profiles[profile]['settings'][setting_id] = value

    def delete_setting(self, session, profile, setting_id):
        self.profiles[profile]['settings'].pop(setting_id, None)

    def save(self, session):
        self.saved += 1


def test_frame_limit_uses_existing_game_profile_and_deletes_only_the_setting():
    drs = FakeDrs(apps={EXE})
    limit = FrameLimit(drs)
    assert limit.read([r'C:\Nexon\Mabinogi\Client.exe', EXE]) is None
    limit.write([EXE], 400)
    assert drs.profiles['Mabinogi']['settings'] == {FRL_FPS_ID: 400} and limit.read([EXE]) == 400
    limit.write([EXE], None)
    assert drs.profiles['Mabinogi']['settings'] == {} and 'Mabinogi' in drs.profiles and drs.saved == 2


def test_frame_limit_creates_own_profile_when_missing_and_removes_it_on_restore():
    drs = FakeDrs()
    limit = FrameLimit(drs)
    limit.write([EXE], 400)
    assert drs.profiles[OWN_PROFILE] == {'apps': {EXE}, 'settings': {FRL_FPS_ID: 400}}
    limit.write([EXE], None)
    assert OWN_PROFILE not in drs.profiles  # 앱이 만든 프로필은 통째로 지운다
    with pytest.raises(ValueError):
        limit.write([EXE], 5000)


def test_nvidia_gpu_is_none_outside_windows():
    assert nvidia_drs.nvidia_gpu() is None


# ---- 엔진 ----

class GraphicsBackend(Backend):
    def __init__(self, frl=None):
        super().__init__()
        self.current = [None]
        self.values[('frl', json.dumps(EXE))] = frl
        self.values[('priority', json.dumps(TARGET, sort_keys=True))] = 0x20
        self.game = lambda: self.current[0]
        self.alive = lambda target: self.current[0] == target
        self.processes = lambda: []
        self.governor_running = lambda: False
        self.graphics = lambda: 'NVIDIA GeForce RTX 4080'

    def validate(self, kind, target, value):
        if kind == 'frl':
            assert target == EXE and (value is None or 0 <= value <= 1023)
            return
        return super().validate(kind, target, value)


def _start(tmp_path, frl=None, **extra):
    b = GraphicsBackend(frl)
    r = Recovery(tmp_path / 'j.json', b, lambda: True)
    e = Engine(b, r, lambda: True)
    options = dict(cpu=False, count=None, adapter=None, tcp=False, rss=False, priority=True, auto=False,
                   graphics=True, game_exe=EXE)
    options.update(extra)
    assert e.start(options)
    return b, r, e


def frl(b):
    return b.values[('frl', json.dumps(EXE))]


REQ = dict(priority=True, graphics=True)


def test_session_start_sets_400_before_game_and_off_restores_original(tmp_path):
    b, r, e = _start(tmp_path)
    assert _wait(lambda: e.outcome.get('graphics') == ('ok', '') and e.phase == 'waiting')  # 게임 전(로딩 화면부터)
    assert frl(b) == 400 and [i['kind'] for i in r.pending] == ['frl']
    assert '✓ 그래픽 효율 · 최대 프레임 400' not in summarize(e, r, REQ)[2]  # 대기 중엔 항목 줄 없음
    b.current[0] = TARGET
    assert _wait(lambda: e.phase == 'applied' and e.outcome.get('priority') == ('ok', ''), 6)
    headline, _level, lines = summarize(e, r, REQ)
    assert headline == '최적화 적용 중' and '✓ 그래픽 효율 · 최대 프레임 400' in lines
    e.stop_and_restore()
    e.thread.join(6)
    assert frl(b) is None and not r.pending  # 원래 '설정 없음'으로


def test_user_cap_at_or_below_400_is_left_alone(tmp_path):
    b, r, e = _start(tmp_path, frl=60)
    assert _wait(lambda: e.outcome.get('graphics') == ('low', ''))
    assert frl(b) == 60 and not any(i['kind'] == 'frl' for i in r.items)
    b.current[0] = TARGET
    assert _wait(lambda: e.phase == 'applied', 6)
    assert '✓ 그래픽 효율 · 이미 400 이하라 그대로 뒀어요' in summarize(e, r, REQ)[2]
    e.stop(); e.thread.join(5)


def test_unlimited_zero_is_raised_to_400_and_restored_to_zero(tmp_path):
    b, r, e = _start(tmp_path, frl=0)
    assert _wait(lambda: frl(b) == 400)
    e.stop_and_restore(); e.thread.join(6)
    assert frl(b) == 0


def test_manual_game_exit_keeps_400_until_turned_off(tmp_path):
    b, r, e = _start(tmp_path)
    b.current[0] = TARGET
    assert _wait(lambda: e.phase == 'applied', 6)
    b.current[0] = None
    e.thread.join(6)
    assert e.session_end == 'game_exit' and frl(b) == 400  # 게임이 끝나도 유지(다음 게임 로딩 화면부터)
    headline, _level, lines = summarize(e, r, REQ)
    assert headline == '최적화 적용 중' and lines == ['• 그래픽 효율 · 최대 프레임 400 적용 중 (최적화를 끄면 되돌려요)']


def test_auto_game_end_keeps_graphics_and_shows_applying_line(tmp_path):
    b, r, e = _start(tmp_path, auto=True)
    e.auto = True
    b.current[0] = TARGET
    assert _wait(lambda: e.phase == 'applied', 6)
    b.current[0] = None
    assert _wait(lambda: e.phase == 'ended', 6)
    assert frl(b) == 400
    lines = summarize(e, r, dict(REQ, auto=True))[2]
    assert lines == ['↺ 게임 우선순위 · 되돌림', '• 그래픽 효율 · 최대 프레임 400 적용 중 (최적화를 끄면 되돌려요)']
    e.stop(); e.thread.join(5)


def test_control_panel_change_is_not_overwritten_on_restore(tmp_path):
    b, r, e = _start(tmp_path)
    assert _wait(lambda: frl(b) == 400)
    b.values[('frl', json.dumps(EXE))] = 144  # 사용자가 제어판에서 바꿈
    e.stop_and_restore(); e.thread.join(6)
    assert frl(b) == 144 and [i['state'] for i in r.items] == ['released']


def test_missing_game_exe_reports_reason(tmp_path):
    b, r, e = _start(tmp_path, game_exe=None)
    assert _wait(lambda: e.outcome.get('graphics', ('',))[0] == 'fail')
    assert e.outcome['graphics'][1] == '게임 실행 파일을 먼저 등록해 주세요.'
    e.stop(); e.thread.join(5)


# ---- 화면 ----

def _controller(window, monkeypatch, gpu):
    w = window[0]
    c = w.optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True); c.refresh_access()
    c._gpu, c._gpu_checked = gpu, True
    c._show_gpu()
    c._tick()
    return w, c


def test_nvidia_shows_card_and_recommendation_includes_graphics(window, monkeypatch):
    w, c = _controller(window, monkeypatch, 'NVIDIA GeForce RTX 4080')
    d = c.panel
    assert d.graphics.isChecked() and d.graphics.isEnabled()
    assert d.gpu_label.text() == 'NVIDIA GeForce RTX 4080 · 최대 프레임 400'
    assert d.recommend.text().endswith('· 그래픽 효율')
    d.graphics.setChecked(False)
    c._tick()
    assert d.recommend.text().startswith('직접 고른 설정') and not d.reset_recommended.isHidden()
    from mabinogi_addon import config
    assert config.load_optimization_selection()['graphics'] is False


def test_other_gpu_disables_item_with_reason(window, monkeypatch):
    w, c = _controller(window, monkeypatch, None)
    d = c.panel
    assert not d.graphics.isEnabled() and d.gpu_label.text() == 'NVIDIA 그래픽카드에서만 쓸 수 있어요'
    assert '그래픽 효율' not in d.recommend.text() and not c._graphics_on()


def test_turning_off_with_only_graphics_left_asks_no_network_question(window, monkeypatch):
    w, c = _controller(window, monkeypatch, 'NVIDIA GeForce RTX 4080')
    c.recovery.items = [dict(kind='frl', target=EXE, old=None, applied=400, state='applied')]
    asked, calls = [], []
    monkeypatch.setattr(c, '_network_confirmation', lambda: asked.append(1) or True)
    monkeypatch.setattr(c.engine, 'stop_and_restore', lambda **k: calls.append(k))
    c._restore_all()
    assert not asked and calls == [dict(network=False, accept_normalized=False, network_deferred=False)]


# ---- 0.23.0 Windows 실측 후속: 이름만으로 찾으면 다른 프로필(`Client.exe`)이 잡힘 → 전체 경로만 ----

def test_profile_lookup_uses_only_full_path_and_remembers_it(monkeypatch, tmp_path):
    from mabinogi_addon import config
    from mabinogi_addon.system.nvidia_drs import GamePathUnknown
    from mabinogi_addon.system.optimization import WindowsOptimization
    path = tmp_path / 'c.json'
    read, write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, '_read_local_config', lambda *a, **k: read(path))
    monkeypatch.setattr(config, '_write_local_config', lambda data, *a, **k: write(data, path))
    backend = WindowsOptimization()
    backend.game = lambda: None  # 게임 꺼짐
    with pytest.raises(GamePathUnknown):
        backend._frl_names(EXE)  # 한 번도 본 적 없으면 이름만으로 찾지 않는다
    config.save_game_image_path(r'C:\Nexon\Mabinogi\Client.exe')
    assert backend._frl_names(EXE) == [r'C:\Nexon\Mabinogi\Client.exe']
    with pytest.raises(GamePathUnknown):
        backend._frl_names('other.exe')  # 다른 실행 파일 이름이면 기억한 경로를 쓰지 않는다


class PathUnknownBackend(GraphicsBackend):
    def read(self, kind, target):
        if kind == 'frl' and self.current[0] is None and not getattr(self, 'seen', False):
            from mabinogi_addon.system.nvidia_drs import GamePathUnknown
            raise GamePathUnknown('위치 모름')
        if kind == 'frl':
            self.seen = True
        return super().read(kind, target)


def test_unknown_game_path_defers_until_game_is_seen(tmp_path):
    b = PathUnknownBackend()
    r = Recovery(tmp_path / 'j.json', b, lambda: True)
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=False, count=None, adapter=None, tcp=False, rss=False, priority=True, auto=False,
                        graphics=True, game_exe=EXE))
    assert _wait(lambda: e.outcome.get('graphics') == ('deferred', '마비노기를 한 번 실행하면 적용해요') and e.phase == 'waiting')
    assert frl(b) is None and not r.items
    b.current[0] = TARGET
    # 경로를 안 시점에는 이미 게임이 실행 중 → 이 게임은 다음 실행부터(실측: 다시 켜야 반영)
    assert _wait(lambda: e.outcome.get('graphics', ('',))[0] == 'next' and frl(b) == 400, 6)
    assert '• 그래픽 효율 · 다음 게임 실행부터 적용돼요' in summarize(e, r, REQ)[2]
    e.stop_and_restore(); e.thread.join(6)
    assert frl(b) is None


# ---- 실측(2026-10-26): 실행 중인 게임에는 바로 반영되지 않고 게임을 다시 켜야 400 상한 ----

def test_applied_while_game_runs_says_next_launch_then_ok_on_new_game(tmp_path):
    from test_optimization_auto import SECOND
    b = GraphicsBackend()
    b.current[0] = TARGET  # 게임 실행 중에 시작
    b.values[('priority', json.dumps(SECOND, sort_keys=True))] = 0x20
    r = Recovery(tmp_path / 'j.json', b, lambda: True)
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=False, count=None, adapter=None, tcp=False, rss=False, priority=True, auto=True,
                        graphics=True, game_exe=EXE))
    e.auto = True
    assert _wait(lambda: e.outcome.get('graphics') == ('next', '다음 게임 실행부터 적용돼요') and e.phase == 'applied')
    assert frl(b) == 400
    assert '• 그래픽 효율 · 다음 게임 실행부터 적용돼요' in summarize(e, r, dict(REQ, auto=True))[2]
    b.current[0] = None
    assert _wait(lambda: e.phase == 'ended', 6)
    b.current[0] = SECOND  # 다시 켠 게임부터 적용
    assert _wait(lambda: e.phase == 'applied' and e.outcome.get('graphics') == ('ok', ''), 6)
    assert '✓ 그래픽 효율 · 최대 프레임 400' in summarize(e, r, dict(REQ, auto=True))[2]
    e.stop_and_restore(); e.thread.join(6)
    assert frl(b) is None


# ---- 0.23.0 QA 보류 후속 ----

@pytest.mark.parametrize('state', ['applied', 'restored', 'released'])
def test_tick_survives_frl_record_and_consumes_inspection(window, monkeypatch, state):
    from test_cpu_layouts import X9800
    w, c = _controller(window, monkeypatch, None)
    c.recovery.items = [dict(kind='frl', target=EXE, old=None, applied=400, state=state)]
    c.engine.inspection, c.engine.inspection_gpu = (X9800, []), 'NVIDIA GeForce RTX 4080'
    c._tick()  # QA ①: kinds 표에 frl이 없어 KeyError → 상세·환경 확인 반영이 멈췄음
    assert c.engine.inspection is None and c.panel.split.findData('focus') >= 0
    assert c.panel.gpu_label.text() == 'NVIDIA GeForce RTX 4080 · 최대 프레임 400'
    assert '그래픽 효율(최대 프레임)' in c.panel.details.text()


def test_only_graphics_left_after_restart_is_applying_not_restore_wait(window, monkeypatch, tmp_path):
    # QA ②: 그래픽 효율만 남은 채 앱 재시작 → '네트워크 원복 대기'·'원복 대기'(warn)가 아니라 '적용 중'
    journal = tmp_path / 'recovery.json'
    journal.write_text(json.dumps(dict(schema=1, restart_targets=[], items=[
        dict(kind='frl', target=EXE, old=None, applied=400, state='applied')])), encoding='utf-8')
    w = window[0]
    c = w.optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True)
    c.recovery = Recovery(journal, GraphicsBackend(400), lambda: True)
    assert not c.recovery.corrupt
    c._restore_wait = c._network_left()  # __init__과 같은 규칙
    c.engine.recovery = c.recovery
    c.refresh_access(); c._tick()
    assert c.panel.toggle.text() == '최적화 적용 중'
    assert module.optimization_badge(c.recovery, c.engine, None, restore_wait=c._restore_wait,
                                     kept_on=c._kept_on) == ('최적화: 적용 중', 'neutral')


def test_own_profile_registers_full_path():
    # QA ③: 앱이 만든 프로필에 이름만 넣으면 사전 정의 'Client.exe'와 겹친다 → 전체 경로로 등록
    drs = FakeDrs()
    full = r'C:\Nexon\Mabinogi\Client.exe'
    added = []
    original = drs.add_application
    drs.add_application = lambda session, profile, name: added.append(name) or original(session, profile, name)
    FrameLimit(drs).write([full], 400)
    assert added == [full]


def test_other_game_profile_with_same_exe_name_is_never_written():
    # 실측(2026-10-26): 없는 경로도 사전 정의 'Client.exe'(다른 게임) 프로필로 잡힘 → 그 프로필은 건드리지 않고 앱 프로필을 만든다
    drs = FakeDrs()
    drs.profiles = {'Client.exe': {'apps': {EXE}, 'settings': {}}}
    limit = FrameLimit(drs)
    full = r'D:\Games\Mabinogi\Client.exe'
    assert limit.read([full]) is None
    limit.write([full], 400)
    assert drs.profiles['Client.exe']['settings'] == {}
    assert drs.profiles[OWN_PROFILE] == {'apps': {full}, 'settings': {FRL_FPS_ID: 400}}
    assert limit.read([full]) == 400
    limit.write([full], None)
    assert OWN_PROFILE not in drs.profiles and drs.profiles['Client.exe']['settings'] == {}
