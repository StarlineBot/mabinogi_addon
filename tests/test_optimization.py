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
    assert observed.is_set() and not b.writes and not b.restarts
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
