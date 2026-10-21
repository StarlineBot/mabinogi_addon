"""Real collector schema and mutations interrupted at distinct lifecycle boundaries."""
from pathlib import Path
import pytest
from mabinogi_addon.optimization.session import Core,Topology,Recovery,ChangeDeferred
from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.optimization.frames import FrameStream
from test_support.regressions.optimization_contract import (
    GUID,GAME,LaunchDuringInspection,
    test_pinned_v1_qpc_header_is_accepted,
    test_parser_control_modern_header,
    test_game_start_during_inspection_defers_network,
    test_network_control_game_already_running,
)

FIXTURE=Path(__file__).parent/'data'/'presentmon-v2.3.1-v1-qpc.csv'


def test_pinned_fixture_uses_absolute_qpc_not_relative_seconds():
    stream=FrameStream(123,1000)
    stream.boundary(100.25)
    for line in FIXTURE.read_text(encoding='utf-8').splitlines(): stream.feed(line,100.52)
    assert stream.snapshot(100.52)['fps']==pytest.approx(50)
    assert stream.sources['0xabc'][0]>100.25


@pytest.mark.parametrize('columns',['QPCTime,MsBetweenPresents','TimeInQPC,msBetweenPresents',
                                   'QPCTime,msBetweenPresents,QPCTime','TimeInSeconds,msBetweenPresents',
                                   'QPCTime,msBetweenPresents,TimeInQPC,MsBetweenPresents'])
def test_ambiguous_or_relative_time_schema_is_rejected(columns):
    with pytest.raises(ValueError): FrameStream(123,1000).feed('Application,ProcessID,SwapChainAddress,'+columns,100)


class Transition(LaunchDuringInspection):
    def __init__(self,phase,action='game'):
        super().__init__()
        self.phase,self.action=phase,action
        self.engine=None
        self.access=True
        self.values.update(cpu=15,rss={'old':True})
    def hit(self,phase):
        if self.phase!=phase: return
        if self.action=='game': self.running=True
        elif self.action=='cancel': self.engine.cancel.set()
        elif self.action=='revoke': self.access=False
    def processes(self): self.hit('processes'); return []
    def governor_running(self): self.hit('governor'); return False
    def rss_plan(self,*args): self.hit('rss_plan'); return {'new':True}
    def topology(self): return Topology('two cores',(Core(0,(0,1)),Core(1,(2,3))))
    def validate(self,kind,target,value):
        if kind!='rss': super().validate(kind,target,value)
    def read(self,kind,target):
        self.hit('read_'+kind)
        return super().read(kind,target)
    def write(self,kind,target,value):
        super().write(kind,target,value)
        self.hit('write_'+kind)
    def alive(self,target):
        return not any(w[0]=='cpu' for w in self.writes)


def run_session(tmp_path,phase,action='game',cpu=False,rss=False):
    b=Transition(phase,action)
    r=Recovery(tmp_path/'recovery.json',b,lambda:b.access)
    e=b.engine=Engine(b,r,lambda:b.access)
    # Non-CPU probes finish as soon as their game is observed.
    if not cpu: b.alive=lambda target:False
    if phase=='preflight':
        def guarded_write(kind,target,value,guard):
            b.hit('preflight')
            guard()
            b.write(kind,target,value)
        b.guarded_write=guarded_write
    if phase=='save':
        save=r._save
        def save_and_transition():
            save()
            if r.items: b.hit('save')
        r._save=save_and_transition
    assert e.start(dict(cpu=cpu,count=1 if cpu or rss else None,adapter=GUID,tcp=True,rss=rss))
    e.thread.join(4)
    if e.busy:
        e.cancel.set();e.thread.join(3)
        pytest.fail('session did not stop')
    return b,r,e


@pytest.mark.parametrize('phase',['processes','governor','rss_plan','read_ack','save','preflight'])
def test_game_start_before_first_write_defers_all_network(tmp_path,phase):
    b,r,e=run_session(tmp_path,phase,rss=phase=='rss_plan')
    assert not b.writes and not b.restarts
    assert not r.restart_targets
    if r.items: assert r.items[0]['old'] is None  # Abort after durable preparation preserves originals.


@pytest.mark.parametrize('action',['game','cancel','revoke'])
@pytest.mark.parametrize('phase',['write_ack','write_autotuning'])
def test_interruption_preserves_partial_changes_without_restart(tmp_path,phase,action):
    b,r,e=run_session(tmp_path,phase,action)
    assert [w[0] for w in b.writes]==(['ack'] if phase=='write_ack' else ['ack','nodelay','autotuning'])
    assert not b.restarts and r.restart_targets=={GUID}
    assert r.pending[0]['old'] is None and r.pending[0]['applied']==1
    reloaded=Recovery(r.path,b,lambda:False)
    assert reloaded.restart_targets=={GUID} and reloaded.pending==r.pending
    # Explicit recovery remains possible after revocation, never runs automatically mid-game.
    assert reloaded.restore(network=True)==[]
    assert b.values=={'ack':None,'nodelay':None,'autotuning':'disabled','cpu':15,'rss':{'old':True}}


@pytest.mark.parametrize('action',['cancel','revoke'])
def test_interruption_during_original_read_prevents_write(tmp_path,action):
    b,r,e=run_session(tmp_path,'read_ack',action)
    assert not b.writes and not b.restarts and not r.items


def test_cpu_still_applies_and_restores_when_network_is_deferred(tmp_path):
    b,r,e=run_session(tmp_path,'processes',cpu=True)
    assert [(w[0],w[1]) for w in b.writes]==[('cpu',3),('cpu',15)]
    assert not b.restarts and not r.pending


def test_guarded_native_registry_write_rechecks_after_adapter_lookup(monkeypatch):
    import sys
    from contextlib import nullcontext
    from types import SimpleNamespace
    from mabinogi_addon.system.optimization import WindowsOptimization
    b=WindowsOptimization();running=[False];writes=[]
    monkeypatch.setattr(b,'_windows',lambda:None)
    monkeypatch.setattr(b,'_ps',lambda *_:running.__setitem__(0,True))
    monkeypatch.setitem(sys.modules,'winreg',SimpleNamespace(HKEY_LOCAL_MACHINE=1,KEY_SET_VALUE=2,
        OpenKey=lambda *a:nullcontext(object()),SetValueEx=lambda *a:writes.append(a),REG_DWORD=4))
    def guard():
        if running[0]: raise ChangeDeferred('game started')
    with pytest.raises(ChangeDeferred): b.guarded_write('ack',GUID,1,guard)
    assert not writes and not b.restarts
