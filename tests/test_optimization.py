"""Fault boundaries for creator alpha: journal, process identity and frame events."""
import copy
import json
import math
import threading
import pytest
from mabinogi_addon.optimization.session import Core, Topology, Recovery
from mabinogi_addon.optimization.frames import FrameStream
from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.system.optimization import WindowsOptimization
from mabinogi_addon.system.presentmon import arguments, executable


class Backend:
    validate = staticmethod(WindowsOptimization.validate)
    def __init__(self):
        self.values = {}
        self.writes = []
        self.restart_fail = False
        self.restarts = []
    def read(self, kind, target): return copy.deepcopy(self.values[(kind,json.dumps(target,sort_keys=True))])
    def write(self, kind, target, value):
        self.writes.append((kind,copy.deepcopy(target),copy.deepcopy(value)))
        self.values[(kind,json.dumps(target,sort_keys=True))] = copy.deepcopy(value)
    def restart_network(self, target):
        if self.restart_fail: raise OSError('adapter unavailable')
        self.restarts.append(target)


TARGET = {'pid':123,'birth':'987654321'}
GUID = '12345678-1234-1234-1234-123456789abc'


@pytest.fixture
def recovery(tmp_path):
    backend = Backend()
    backend.values[('cpu',json.dumps(TARGET,sort_keys=True))] = 15
    backend.values[('ack',json.dumps(GUID))] = None
    allowed = [True]
    recovery = Recovery(tmp_path/'journal.json',backend,lambda:allowed[0])
    return recovery, backend, allowed


def test_physical_siblings_and_hybrid_defaults():
    t = Topology('AMD Ryzen 7 9800X3D',tuple(Core(i,(i*2,i*2+1)) for i in range(8)))
    assert t.plan()['count'] == 7
    for n in (6,7):
        p = t.plan(n)
        assert not p['game'] & p['background']
        assert p['game'] | p['background'] == 65535
        assert p['background_cpus'] == list(range(n*2,16))
    hybrid = Topology('hybrid',t.cores+tuple(Core(i+8,(i+16,),False) for i in range(8)))
    assert hybrid.plan()['count'] == 4
    assert hybrid.plan()['background'] & (255<<16) == 255<<16


@pytest.mark.parametrize('cores',[(Core(0,(0,1)),),(Core(0,(0,1)),Core(1,(1,2))),
                                  (Core(0,()),Core(1,(2,3))),(Core(0,(0,1)),Core(1,(64,65)))])
def test_unknown_or_unsafe_topologies_refused(cores):
    with pytest.raises(ValueError): Topology('unknown',cores).plan()


def test_write_ahead_survives_crash_and_access_revocation(recovery):
    r,b,allowed = recovery
    original_write = b.write
    def write(kind,target,value):
        persisted = json.loads(r.path.read_text(encoding='utf-8'))['items'][0]
        assert persisted['old']==15 and persisted['state']=='prepared'
        original_write(kind,target,value)
    b.write = write
    r.apply('cpu',TARGET,3)
    b.write = original_write
    allowed[0] = False
    reloaded = Recovery(r.path,b,lambda:False)
    assert reloaded.restore() == []
    assert b.read('cpu',TARGET)==15
    assert not reloaded.pending


def test_failed_journal_write_never_changes_system(recovery,monkeypatch):
    r,b,_=recovery
    monkeypatch.setattr(r,'_save',lambda:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError): r.apply('cpu',TARGET,3)
    assert not b.writes and not r.items


def test_external_change_blocks_retry_and_restore_without_overwrite(recovery):
    r,b,_=recovery
    r.apply('cpu',TARGET,3)
    b.values[('cpu',json.dumps(TARGET,sort_keys=True))] = 7
    with pytest.raises(RuntimeError): r.apply('cpu',TARGET,1)
    assert r.restore() and b.read('cpu',TARGET)==7
    assert r.items[0]['old']==15
    assert len(b.writes)==1


def test_network_absence_recovery_and_restart_journal(recovery):
    r,b,_=recovery
    r.apply('ack',GUID,1)
    assert r.restore()==[] and b.read('ack',GUID)==1
    assert r.restart_targets=={GUID}
    b.restart_fail=True
    with pytest.raises(OSError): r.flush_network()
    r=Recovery(r.path,b,lambda:True)
    assert r.restart_targets=={GUID}
    assert r.restore(network=True)==[]
    assert b.read('ack',GUID) is None
    with pytest.raises(RuntimeError): r.finish()
    b.restart_fail=False
    r.flush_network()
    r.finish()
    assert not r.pending and not r.restart_targets


def test_noop_does_not_write_or_restart(recovery):
    r,b,_=recovery
    r.apply('cpu',TARGET,15)
    r.apply('ack',GUID,None)
    assert not b.writes and not r.restart_targets and not r.items


def test_corrupt_journal_never_guesses_originals(recovery):
    r,b,_=recovery
    r.path.write_text('{broken',encoding='utf-8')
    bad=Recovery(r.path,b,lambda:True)
    assert bad.corrupt and bad.restore(network=True)
    with pytest.raises(PermissionError): bad.apply('cpu',TARGET,3)
    assert not b.writes and r.path.read_text(encoding='utf-8')=='{broken'


def test_pid_reuse_does_not_write_old_mask(recovery):
    r,b,_=recovery
    r.apply('cpu',TARGET,3)
    b.read=lambda *_:(_ for _ in ()).throw(ProcessLookupError())
    assert r.restore()==[] and not r.pending
    assert len(b.writes)==1


def test_inspection_never_restores_pending_changes(recovery):
    r,b,_=recovery
    r.apply('cpu',TARGET,3)
    b.topology=lambda:Topology('cpu',(Core(0,(0,1)),Core(1,(2,3))))
    b.adapters=lambda:[]
    e=Engine(b,r,lambda:True)
    e.inspect()
    e.thread.join(2)
    assert not e.busy and b.read('cpu',TARGET)==3
    assert len(b.writes)==1


def stream():
    s=FrameStream(123,1000)
    s.feed('Application,ProcessID,SwapChainAddress,TimeInQPC,MsBetweenPresents',100)
    return s


def frames(s,start=100,source='0xabc',count=61,rate=60):
    for n in range(count):
        stamp=start+n/rate
        s.feed(f'game.exe,123,{source},{round(stamp*1000)},{1000/rate:.5f}',stamp)


def test_fps_uses_present_events_and_stales_to_unknown():
    s=stream()
    # Integer millisecond input uses exact 50 FPS for this test.
    frames(s,rate=50,count=51)
    assert s.snapshot(101)['fps']==pytest.approx(50)
    assert s.snapshot(104)['fps'] is None
    s.boundary(104)
    frames(s,start=103,rate=50,count=20)
    assert s.snapshot(104)['fps'] is None
    frames(s,start=104.1,rate=50,count=20)
    assert s.snapshot(104.5)['fps']==pytest.approx(50)


def test_multiple_swapchains_never_sum_and_explicit_selection_resets():
    s=stream()
    frames(s,rate=50,count=51)
    frames(s,source='0xdef',rate=50,count=51)
    assert s.snapshot(101)['fps'] is None
    s.select('0xdef',101)
    assert s.snapshot(101)['fps'] is None
    frames(s,start=101.1,source='0xdef',rate=50,count=21)
    assert s.snapshot(101.5)['fps']==pytest.approx(50)


@pytest.mark.parametrize('line', ['game.exe,999,0xabc,100000,20','game.exe,123,0xabc,100000,nan',
                                 'game.exe,123,0x0,100000,20','invalid,row'])
def test_invalid_or_foreign_frames_rejected(line):
    with pytest.raises(ValueError): stream().feed(line,100)


def test_event_loss_and_timestamp_reversal_reset_window():
    s=stream()
    frames(s,rate=50,count=51)
    s.feed('game.exe,123,0xabc,101100,20',101.1)
    assert s.snapshot(101.1)['fps'] is None
    assert '누락' in s.snapshot(101.1)['status']
    s.feed('game.exe,123,0xabc,101050,20',101.1)
    assert s.snapshot(101.1)['fps'] is None


def test_bundled_collector_contract_is_pinned_and_noninvasive():
    assert executable().stat().st_size==421312
    args=arguments(123,'MabinogiAddon-test')
    assert '--process_id' in args and '--qpc_time' in args
    assert not any(x in args for x in ('--restart_as_admin','--stop_existing_session','--hotkey'))


def test_session_restores_cpu_on_game_exit_without_autostart(recovery):
    r,b,_=recovery
    entered=threading.Event()
    alive=[True]
    b.topology=lambda:Topology('cpu',(Core(0,(0,1)),Core(1,(2,3))))
    b.game=lambda:TARGET
    b.processes=lambda:[]
    b.governor_running=lambda:False
    b.alive=lambda target:alive[0]
    original=b.write
    def write(kind,target,value):
        original(kind,target,value)
        if value==3: entered.set()
    b.write=write
    e=Engine(b,r,lambda:True)
    assert e.start(dict(cpu=True,count=1,adapter=None,tcp=False,rss=False))
    assert entered.wait(2)
    assert not e.start(dict(cpu=True,count=1,adapter=None,tcp=False,rss=False))
    alive[0]=False
    e.thread.join(4)
    assert not e.busy and not r.pending
    assert b.read('cpu',TARGET)==15 and len(b.writes)==2
    assert e.recovery_requested


def test_existing_game_defers_network_and_does_not_write_on_just_waiting(recovery):
    r,b,_=recovery
    observed=threading.Event()
    b.game=lambda:TARGET
    b.processes=lambda:[]
    b.governor_running=lambda:False
    def alive(target): observed.set(); return False
    b.alive=alive
    e=Engine(b,r,lambda:True)
    assert e.start(dict(cpu=False,count=None,adapter=GUID,tcp=True,rss=False))
    e.thread.join(2)
    # CPU를 끈 세션은 게임을 기다리지 않고 끝난다(네트워크 보류 안내는 남김).
    assert not e.busy and not observed.is_set() and not b.writes and not b.restarts
    assert '게임 실행 중: TCP·RSS 적용을 보류' in e.status and '게임 실행 대기' not in e.status
    assert not r.pending


def test_rss_exact_background_range_or_unsupported(recovery):
    r,b,_=recovery
    original=dict(Enabled=True,BaseProcessorGroup=0,BaseProcessorNumber=0,MaxProcessorGroup=0,
                  MaxProcessorNumber=15,MaxProcessors=8,NumberOfReceiveQueues=2,Profile='Closest')
    b.values[('rss',json.dumps(GUID))]=original
    plan=WindowsOptimization.rss_plan(b,GUID,[12,13,14,15])
    assert plan['BaseProcessorNumber']==12 and plan['MaxProcessorNumber']==15 and plan['MaxProcessors']==4
    assert plan['Profile']=='ClosestStatic' and plan['NumberOfReceiveQueues']==2
    with pytest.raises(ValueError): WindowsOptimization.rss_plan(b,GUID,[7,15])
    assert not b.writes


@pytest.mark.parametrize('change',[{'protected':True},{'same_user':False},{'same_session':False},
                                  {'name':'PresentMon.exe'},{'path':'C:/Windows/System32/worker.exe'},
                                  {'path':'C:/Program Files/AntiCheat/random.exe'}, {'target':TARGET}])
def test_background_exclusions_are_not_affinity_targets(change):
    info=dict(target={'pid':456,'birth':'123'},name='ordinary.exe',path='C:/Apps/ordinary.exe',
              same_user=True,same_session=True,protected=False)
    assert WindowsOptimization.background_candidate(info,TARGET)
    info.update(change)
    assert not WindowsOptimization.background_candidate(info,TARGET)


def test_etw_health_poll_does_not_accumulate_ctypes_types(monkeypatch):
    import ctypes
    from mabinogi_addon.system import presentmon
    calls=[]
    def query(handle,session,pointer,command):
        p=pointer._obj
        assert p.Wnode.BufferSize==ctypes.sizeof(p)+4096
        assert p.LoggerNameOffset==ctypes.sizeof(p)
        calls.append(command)
        p.EventsLost=2;p.RealTimeBuffersLost=1
        return 0
    monkeypatch.setattr(presentmon,'_etw_api',lambda:query)
    before=len(ctypes._pointer_type_cache)
    for _ in range(1000):
        assert presentmon.session_losses('MabinogiAddon-'+'a'*32)==3
    assert len(ctypes._pointer_type_cache)<=before+1
    assert calls==[0]*1000
    assert presentmon.session_losses('MabinogiAddon-'+'a'*32,stop=True)==3
    assert calls[-1]==1


def test_etw_missing_owned_session_is_only_success_for_cleanup(monkeypatch):
    from mabinogi_addon.system import presentmon
    monkeypatch.setattr(presentmon,'_etw_api',lambda:(lambda *a:4201))
    name='MabinogiAddon-'+'b'*32
    assert presentmon.session_losses(name,stop=True)==0
    with pytest.raises(OSError): presentmon.session_losses(name)
    with pytest.raises(ValueError): presentmon.session_losses('OtherApp',stop=True)


def test_unsupported_cpu_inspection_still_lists_network_without_invalid_plan(recovery):
    r,b,_=recovery
    b.topology=lambda:Topology('one core',(Core(0,(0,1)),))
    b.adapters=lambda:[{'Name':'Ethernet','InterfaceGuid':GUID}]
    e=Engine(b,r,lambda:True)
    e.inspect();e.thread.join(2)
    assert not e.busy and e.inspection==(None,[{'Name':'Ethernet','InterfaceGuid':GUID}])
    assert '코어' in e.status and not b.writes


# --- 0.11.1 라이브 제보: RSS 복구 잠김 ------------------------------------------------
# 사용자 화면값: 원본 14/8, 적용 15/2, 재시작 후 현재 14/1. Windows RSS는 SMT 형제를 쓰지 않아
# 어댑터 재시작 때 물리 코어당 대표 논리 CPU만 남긴다(아래 장치 모형).
RSS_ORIGINAL = dict(Enabled=True, BaseProcessorGroup=0, BaseProcessorNumber=0, MaxProcessorGroup=0,
                    MaxProcessorNumber=14, MaxProcessors=8, NumberOfReceiveQueues=8, Profile='NUMAStatic')


class SmtNic(Backend):
    def __init__(self):
        super().__init__()
        self.values[('rss', json.dumps(GUID))] = copy.deepcopy(RSS_ORIGINAL)

    def restart_network(self, target):
        super().restart_network(target)
        v = self.values[('rss', json.dumps(GUID))]
        evens = [n for n in range(v['BaseProcessorNumber'], v['MaxProcessorNumber'] + 1) if n % 2 == 0]
        v['MaxProcessorNumber'] = max(evens)
        v['MaxProcessors'] = min(v['MaxProcessors'], len(evens))


def test_rss_plan_uses_one_logical_cpu_per_physical_core():
    t = Topology('AMD Ryzen 7 9800X3D', tuple(Core(i, (i * 2, i * 2 + 1)) for i in range(8)))
    assert t.plan(7)['background_cores'] == [(14, 15)]
    assert t.plan(6)['background_cores'] == [(12, 13), (14, 15)]
    b = SmtNic()
    plan = WindowsOptimization.rss_plan(b, GUID, t.plan(7)['background_cores'])
    assert (plan['BaseProcessorNumber'], plan['MaxProcessorNumber'], plan['MaxProcessors']) == (14, 14, 1)
    plan = WindowsOptimization.rss_plan(b, GUID, t.plan(6)['background_cores'])
    assert (plan['BaseProcessorNumber'], plan['MaxProcessorNumber'], plan['MaxProcessors']) == (12, 14, 2)
    # 물리 코어가 끊긴 묶음은 하나의 범위로 표현할 수 없다.
    with pytest.raises(ValueError):
        WindowsOptimization.rss_plan(b, GUID, [(10, 11), (14, 15)])


def test_rss_smt_plan_survives_adapter_restart_and_restores(tmp_path):
    b = SmtNic()
    cores = Topology('AMD Ryzen 7 9800X3D', tuple(Core(i, (i * 2, i * 2 + 1)) for i in range(8))).plan(7)['background_cores']
    r = Recovery(tmp_path / 'journal.json', b, lambda: True)
    plan = WindowsOptimization.rss_plan(b, GUID, cores)
    assert r.apply('rss', GUID, plan) == 'written'
    r.flush_network()
    assert b.read('rss', GUID) == plan  # 정규화 결과가 적용값과 같다
    assert r.items[0]['state'] == 'applied'
    assert r.restore(network=True) == []
    r.flush_network(verify_restored=True)
    assert b.read('rss', GUID) == RSS_ORIGINAL and not r.pending
    r.finish()


def _legacy_locked(tmp_path):
    """0.11.1에서 이미 잠긴 기록: 14~15/2를 쓴 뒤 장치가 14/1로 줄인 상태(파일에서 다시 연다)."""
    b = SmtNic()
    applied = dict(RSS_ORIGINAL, BaseProcessorNumber=14, MaxProcessorNumber=15, MaxProcessors=2,
                   Profile='ClosestStatic')
    # 0.11.1이 남긴 기록 형식 그대로 만든다(당시엔 적용값 15/2가 'applied'로 기록되고 장치가 14/1로 줄임).
    (tmp_path / 'journal.json').write_text(json.dumps(dict(schema=1, restart_targets=[], items=[
        dict(kind='rss', target=GUID, old=RSS_ORIGINAL, applied=applied, state='applied')])), encoding='utf-8')
    b.values[('rss', json.dumps(GUID))] = dict(applied, MaxProcessorNumber=14, MaxProcessors=1)
    return b, Recovery(tmp_path / 'journal.json', b, lambda: True)


def test_rss_legacy_locked_journal_needs_confirmation_then_restores(tmp_path):
    b, r = _legacy_locked(tmp_path)
    writes = len(b.writes)
    errors = r.restore(network=True)
    assert errors and '자체 규칙' in errors[0] and r.pending and len(b.writes) == writes  # 확인 전엔 쓰지 않음
    assert r.normalized_review and r.normalized_review[0]['old'] == RSS_ORIGINAL
    with pytest.raises(RuntimeError): r.finish()
    assert r.restore(network=True, accept_normalized=True) == []
    r.flush_network(verify_restored=True)
    assert b.read('rss', GUID) == RSS_ORIGINAL and not r.pending and not r.restart_targets
    r.finish()


@pytest.mark.parametrize('change', [dict(Profile='Closest'), dict(NumberOfReceiveQueues=2),
                                    dict(MaxProcessorNumber=12, MaxProcessors=1), dict(MaxProcessors=3)])
def test_rss_other_changes_are_not_treated_as_normalization(tmp_path, change):
    b, r = _legacy_locked(tmp_path)
    b.values[('rss', json.dumps(GUID))].update(change)  # 다른 도구·범위 밖 변경
    writes = len(b.writes)
    errors = r.restore(network=True, accept_normalized=True)
    assert errors and '보류' in errors[0] and not r.normalized_review
    assert len(b.writes) == writes and r.pending


# --- 0.11.2 최적화 실사용 결과(2026-10-23) -------------------------------------------------------
CHAT = {'pid': 200, 'birth': '1'}
TOOL = {'pid': 201, 'birth': '2'}


def _wait(predicate, timeout=3):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate(): return True
        time.sleep(0.01)
    return False


def test_external_cpu_change_releases_only_that_process_and_names_it(recovery):
    r, b, _ = recovery
    for target in (CHAT, TOOL):
        b.values[('cpu', json.dumps(target, sort_keys=True))] = 15
    alive = [True]
    b.topology = lambda: Topology('cpu', (Core(0, (0, 1)), Core(1, (2, 3))))
    b.game = lambda: TARGET
    b.processes = lambda: [dict(target=CHAT, name='chat.exe'), dict(target=TOOL, name='tool.exe')]
    b.background_candidate = lambda info, game: True
    b.governor_running = lambda: False
    b.alive = lambda target: alive[0]
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=True, count=1, adapter=None, tcp=False, rss=False))
    assert _wait(lambda: len(b.writes) == 3)
    b.values[('cpu', json.dumps(CHAT, sort_keys=True))] = 1  # 다른 도구가 변경
    assert _wait(lambda: 'chat.exe (PID 200)' in e.status)
    assert e.busy and '다른 도구가 CPU 배치를 바꿨어요' in e.status and '현재=0x1' in e.status
    states = {item['target']['pid']: item['state'] for item in r.items}
    assert states == {123: 'applied', 200: 'released', 201: 'applied'}
    b.values[('cpu', json.dumps(TARGET, sort_keys=True))] = 2  # 게임 자신이 변경
    assert _wait(lambda: '게임 프로세스가 직접' in e.status)
    assert e.busy
    alive[0] = False
    e.thread.join(4)
    assert not e.busy and not r.pending
    # 관리에서 뺀 프로세스는 원복하지 않고, 남은 항목만 원복한다.
    assert b.read('cpu', CHAT) == 1 and b.read('cpu', TARGET) == 2 and b.read('cpu', TOOL) == 15
    r.finish()


def test_session_exception_keeps_earlier_results_and_notices(recovery):
    r, b, _ = recovery
    b.topology = lambda: Topology('cpu', (Core(0, (0, 1)), Core(1, (2, 3))))
    b.game = lambda: TARGET
    b.processes = lambda: []
    b.governor_running = lambda: False
    def alive(target): raise RuntimeError('boom')
    b.alive = alive
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=True, count=1, adapter=GUID, tcp=True, rss=False))
    e.thread.join(2)
    assert '게임 실행 중: TCP·RSS 적용을 보류' in e.status and '작업을 완료하지 못했어요: boom' in e.status


def test_status_is_replaced_immediately_when_work_starts(recovery):
    r, b, _ = recovery
    gate = threading.Event()
    b.topology = lambda: Topology('cpu', (Core(0, (0, 1)), Core(1, (2, 3))))
    b.game = lambda: gate.wait(2) and None
    b.processes = lambda: []
    b.governor_running = lambda: False
    e = Engine(b, r, lambda: True)
    e.status = '원복 완료'
    assert e.start(dict(cpu=True, count=1, adapter=None, tcp=False, rss=False))
    assert e.status == '적용 중…'
    e.cancel.set(); gate.set(); e.thread.join(3)
    e.status = '원복 완료'
    hold = threading.Event()
    original = r.restore
    r.restore = lambda **k: hold.wait(2) and original(**k)
    assert e.restore_network() and e.status == '네트워크 원복 중…'
    hold.set(); e.thread.join(2)
    assert e.status == '원복 완료'



def test_apply_verification_failure_shows_field_differences(tmp_path):
    b = SmtNic()
    plan = dict(RSS_ORIGINAL, BaseProcessorNumber=14, MaxProcessorNumber=14, MaxProcessors=1, Profile='ClosestStatic')
    original_write = b.write
    def write(kind, target, value):
        original_write(kind, target, value)
        b.values[('rss', json.dumps(GUID))]['NumberOfReceiveQueues'] = 1  # 드라이버가 즉시 다른 값으로 저장
    b.write = write
    r = Recovery(tmp_path / 'journal.json', b, lambda: True)
    assert r.apply('rss', GUID, plan) == 'written'
    with pytest.raises(RuntimeError) as caught:
        r.flush_network()  # 재연결 직후 확인에서 실패
    assert r.items[0]['state'] == 'failed' and not r.restart_targets
    assert '재연결 후 확인/rss: 적용값을 확인하지 못했어요' in str(caught.value)
    assert 'NumberOfReceiveQueues: 현재=1, 적용=8' in str(caught.value) and GUID not in str(caught.value)


def test_rss_is_verified_after_restart_not_before(tmp_path):
    """0.11.3 실측: -NoRestart 직후 조회는 이전(실행 중) 값이라 항상 확인 실패 → failed로 남아 다음 시작이 막혔다."""
    class StagedNic(SmtNic):
        def __init__(self):
            super().__init__(); self.staged = None
        def write(self, kind, target, value):
            self.writes.append((kind, target, value)); self.staged = copy.deepcopy(value)  # 재시작 전엔 반영 안 됨
        def restart_network(self, target):
            if self.staged is not None:
                self.values[('rss', json.dumps(GUID))] = self.staged; self.staged = None
            super().restart_network(target)
    b = StagedNic()
    r = Recovery(tmp_path / 'journal.json', b, lambda: True)
    plan = dict(RSS_ORIGINAL, BaseProcessorNumber=14, MaxProcessorNumber=15, MaxProcessors=2, Profile='ClosestStatic')
    assert r.apply('rss', GUID, plan) == 'written' and b.read('rss', GUID) == RSS_ORIGINAL
    r.flush_network()
    item = r.items[0]
    # 장치가 14/1로 정규화해도 적용 성공으로 인정하고, 그 값을 적용값으로 기록한다.
    assert item['state'] == 'applied' and (item['applied']['MaxProcessorNumber'], item['applied']['MaxProcessors']) == (14, 1)
    assert r.restore(network=True) == [] and not r.normalized_review
    r.flush_network(verify_restored=True)
    assert b.read('rss', GUID) == RSS_ORIGINAL and not r.pending
    r.finish()


def test_engine_reports_rss_written_then_verified_after_reconnect(recovery):
    r, b, _ = recovery
    b.values[('rss', json.dumps(GUID))] = copy.deepcopy(RSS_ORIGINAL)
    b.topology = lambda: Topology('AMD Ryzen 7 9800X3D', tuple(Core(i, (i * 2, i * 2 + 1)) for i in range(8)))
    b.rss_plan = lambda guid, cores: WindowsOptimization.rss_plan(b, guid, cores)
    b.game = lambda: None
    b.processes = lambda: []
    b.governor_running = lambda: False
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=False, count=7, adapter=GUID, tcp=False, rss=True))
    e.thread.join(3)
    assert 'rss: 적용 · 재연결 후 확인' in e.status and 'rss: 재연결 후 적용값 확인 완료' in e.status
    assert r.items[0]['state'] == 'applied' and not r.restart_targets



def test_stop_and_restore_reverts_cpu_then_network_in_one_action(recovery):
    """원버튼 원복: 실행 중 세션(TCP 적용 → 게임 실행 → CPU 적용)을 멈추고, CPU를 되돌린 뒤
    같은 작업에서 네트워크까지 되돌린다."""
    r, b, _ = recovery
    b.values[('ack', json.dumps(GUID))] = None
    b.values[('nodelay', json.dumps(GUID))] = None
    b.values[('autotuning', json.dumps('global'))] = 'normal'
    entered = threading.Event()
    b.topology = lambda: Topology('cpu', (Core(0, (0, 1)), Core(1, (2, 3))))
    b.game = lambda: TARGET if b.restarts else None  # 네트워크 적용·재연결이 끝난 뒤 게임 실행
    b.processes = lambda: []
    b.governor_running = lambda: False
    b.alive = lambda target: True
    original = b.write
    def write(kind, target, value):
        original(kind, target, value)
        if kind == 'cpu' and value == 3: entered.set()
    b.write = write
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=True, count=1, adapter=GUID, tcp=True, rss=False))
    assert entered.wait(5), e.status
    assert e.busy and {i['kind'] for i in r.pending} == {'cpu', 'ack', 'nodelay'}, e.status
    assert e.stop_and_restore(network=True) and e.status == '중단 · 원복 중…'
    e.thread.join(5)
    assert not e.busy and not r.pending and not r.restart_targets
    assert b.read('cpu', TARGET) == 15 and b.read('ack', GUID) is None and b.read('nodelay', GUID) is None
    assert '네트워크 원복 완료' in e.status
