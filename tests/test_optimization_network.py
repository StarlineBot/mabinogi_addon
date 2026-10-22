"""Network identity, safe failure diagnostics and partial session reporting."""
import base64
from contextlib import nullcontext
import subprocess
import sys
from types import SimpleNamespace
import pytest
from mabinogi_addon.system.optimization import WindowsOptimization,WindowsCommandError
from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.optimization.session import Recovery
from test_support.regressions.optimization_network import (
    GUID,test_enumerated_adapter_matches_structural_predicate,
    test_distinct_shell_failures_leave_distinguishable_diagnostics,
)
from test_support.regressions.optimization_contract import LaunchDuringInspection


@pytest.mark.parametrize('ids',[[GUID,'{'+GUID.upper()+'}'],['bad'],[None]])
def test_invalid_or_duplicate_adapter_ids_fail_closed(monkeypatch,ids):
    b=WindowsOptimization()
    monkeypatch.setattr(b,'_ps',lambda *a:[dict(Name='Ethernet',InterfaceGuid=g) for g in ids])
    with pytest.raises((ValueError,TypeError,AttributeError)): b.adapters()


def test_multiple_devices_keep_only_selected_guid_in_lookup(monkeypatch):
    b=WindowsOptimization();other='22345678-1234-1234-1234-123456789abc'
    monkeypatch.setattr(b,'_ps',lambda *a:[dict(Name='same name',InterfaceGuid=g) for g in [GUID,other]])
    assert [r['InterfaceGuid'] for r in b.adapters()]==[GUID,other]
    assert GUID in b._adapter(GUID) and other not in b._adapter(GUID)
    with pytest.raises(ValueError): b._adapter("'; Restart-NetAdapter")


@pytest.mark.parametrize('encoding',['utf-8','utf-16','utf-16le'])
@pytest.mark.parametrize('marker,category',[
    ('MABI_OPT_ERROR:PermissionDenied','PermissionDenied'),
    ('MABI_OPT_ERROR:NotImplemented','NotImplemented'),
    ('MABI_OPT_ADAPTER:missing','AdapterMissing'),
    ('MABI_OPT_ADAPTER:ambiguous','AdapterAmbiguous'),
    ('MABI_OPT_COMMAND:missing','CommandMissing'),
])
def test_shell_errors_keep_safe_evidence_without_private_text(monkeypatch,encoding,marker,category):
    b=WindowsOptimization();secret='https://private.invalid?token=abc C:\\Users\\Private 10.1.2.3 Ethernet-Personal'
    error=(marker+'\nMABI_OPT_HRESULT:-2147024891\n'+secret).encode(encoding)
    monkeypatch.setattr(b,'_windows',lambda:None)
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout=b'',stderr=error))
    with pytest.raises(WindowsCommandError) as caught: b._ps('not displayed','조회/rss')
    exc=caught.value
    assert exc.category==category and exc.returncode==1 and exc.hresult==-2147024891
    assert exc.operation=='조회/rss' and len(exc.evidence)==12
    assert secret not in str(exc) and 'Private' not in str(exc) and '10.1.2.3' not in str(exc)
    assert len(str(exc))<200


def test_stderr_is_bounded_and_native_failure_code_retained():
    exc=WindowsCommandError('적용/autotuning',1,b'MABI_OPT_NATIVE:5\n'+b'x'*1000000)
    assert exc.nativecode==5 and len(str(exc))<200
    assert not hasattr(exc,'stderr')


@pytest.mark.parametrize('failure,category',[
    (subprocess.TimeoutExpired('private command',15),'Timeout'),
    (FileNotFoundError(2,'C:/Users/Private/powershell.exe'),'LaunchFailed'),
])
def test_process_launch_failures_are_safe(monkeypatch,failure,category):
    b=WindowsOptimization();monkeypatch.setattr(b,'_windows',lambda:None)
    def fail(*a,**k): raise failure
    monkeypatch.setattr(subprocess,'run',fail)
    with pytest.raises(WindowsCommandError) as caught: b._ps('secret')
    assert caught.value.category==category and 'Private' not in str(caught.value)


@pytest.mark.parametrize('stdout',[b'not json',b'\xff',b'x'*(1024*1024+1)])
def test_malformed_success_output_is_not_reported_as_success(monkeypatch,stdout):
    b=WindowsOptimization();monkeypatch.setattr(b,'_windows',lambda:None)
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=stdout,stderr=b''))
    with pytest.raises(WindowsCommandError,match='응답 형식 오류'): b._ps('query')


def test_powershell_uses_utf8_and_safe_error_record(monkeypatch):
    b=WindowsOptimization();monkeypatch.setattr(b,'_windows',lambda:None);calls=[]
    def run(args,**kwargs):
        calls.append(base64.b64decode(args[-1]).decode('utf-16le'))
        return SimpleNamespace(returncode=0,stdout='"이더넷"'.encode(),stderr=b'')
    monkeypatch.setattr(subprocess,'run',run)
    assert b._ps('read-only')=='이더넷'
    assert "MABI_OPT_ERROR:" in calls[0] and 'OutputEncoding=[Text.Encoding]::UTF8' in calls[0]
    assert 'Exception.Message' not in calls[0] and 'ScriptStackTrace' not in calls[0]


@pytest.mark.parametrize('kind',['ack','nodelay'])
@pytest.mark.parametrize('phase',['read','write'])
def test_native_registry_permission_error_retains_item_without_path(monkeypatch,kind,phase):
    b=WindowsOptimization();monkeypatch.setattr(b,'_windows',lambda:None)
    monkeypatch.setattr(b,'_ps',lambda *a:None)
    def fail(*a): raise PermissionError(13,'private path C:/Users/Private')
    monkeypatch.setitem(sys.modules,'winreg',SimpleNamespace(HKEY_LOCAL_MACHINE=1,KEY_SET_VALUE=2,OpenKey=fail))
    with pytest.raises(WindowsCommandError) as caught:
        b.read(kind,GUID) if phase=='read' else b.write(kind,GUID,1)
    assert kind in caught.value.operation and caught.value.category=='PermissionDenied'
    assert 'Private' not in str(caught.value)


@pytest.mark.parametrize('normal',[False,True])
def test_partial_tcp_failure_does_not_hide_autotuning_result(tmp_path,normal):
    import time
    b=LaunchDuringInspection();b.processes=lambda:[];b.game=lambda:None
    if normal: b.values['autotuning']='normal'
    read=b.read
    def selective_read(kind,target):
        if kind in ('ack','nodelay'): raise WindowsCommandError('조회/'+kind,1,category='AdapterMissing')
        return read(kind,target)
    b.read=selective_read
    r=Recovery(tmp_path/'recovery.json',b,lambda:True);e=Engine(b,r,lambda:True)
    assert e.start(dict(cpu=False,count=None,adapter=GUID,tcp=True,rss=False))
    try:
        deadline=time.monotonic()+3
        while 'autotuning:' not in e.status and time.monotonic()<deadline: e.cancel.wait(.01)
        assert 'autotuning:' in e.status
    finally:
        e.stop();e.thread.join(3)
    assert not e.busy
    assert 'ack 미적용' in e.status and 'nodelay 미적용' in e.status
    assert 'autotuning: '+('기존 값 일치·변경 없음' if normal else '적용값 확인 완료') in e.status
    assert b.values['autotuning']=='normal'


@pytest.mark.parametrize('phase',['original','verify','restore'])
def test_recovery_failure_reports_stage_and_keeps_originals(tmp_path,phase):
    b=LaunchDuringInspection();r=Recovery(tmp_path/'journal.json',b,lambda:True)
    read=b.read
    def fail(kind,target): raise WindowsCommandError('조회/ack',1,category='AdapterMissing')
    if phase=='restore':
        r.apply('ack',GUID,1)
        b.read=fail
        errors=r.restore(network=True)
        assert len(errors)==1 and '원복 전 확인/ack' in errors[0]
    else:
        if phase=='original': b.read=fail
        else:
            calls=[0]
            def verify_fail(kind,target):
                calls[0]+=1
                if calls[0]>1: return fail(kind,target)
                return read(kind,target)
            b.read=verify_fail
        with pytest.raises(OSError,match='원본·현재 조회' if phase=='original' else '적용값 확인'):
            r.apply('ack',GUID,1)
    if phase=='original': assert not r.pending and not b.writes
    else:
        assert r.pending[0]['old'] is None
        assert Recovery(r.path,b,lambda:False).pending==r.pending


@pytest.mark.parametrize('base,maximum,count',[
    (None,None,1),(None,0,1),(0,None,1),(None,None,2),(None,None,0),
])
def test_rss_unreported_groups_require_one_active_group(monkeypatch,base,maximum,count):
    b=WindowsOptimization()
    raw=dict(Enabled=True,BaseProcessorGroup=base,BaseProcessorNumber=14,
             MaxProcessorGroup=maximum,MaxProcessorNumber=15,MaxProcessors=2,
             NumberOfReceiveQueues=2,Profile='ClosestStatic')
    monkeypatch.setattr(b,'_windows',lambda:None)
    monkeypatch.setattr(b,'_ps',lambda *a:raw)
    monkeypatch.setattr(b,'_kernel',lambda:SimpleNamespace(GetActiveProcessorGroupCount=lambda:count))
    if count!=1:
        with pytest.raises(ValueError,match='RSS 프로세서 그룹'): b.read('rss',GUID)
    else:
        assert b.read('rss',GUID)==dict(raw,BaseProcessorGroup=0,MaxProcessorGroup=0)
    assert raw['BaseProcessorGroup'] is base and raw['MaxProcessorGroup'] is maximum


def test_rss_explicit_groups_and_other_missing_fields_are_not_overridden(monkeypatch):
    b=WindowsOptimization()
    raw=dict(Enabled=True,BaseProcessorGroup=0,BaseProcessorNumber=14,
             MaxProcessorGroup=1,MaxProcessorNumber=15,MaxProcessors=2,
             NumberOfReceiveQueues=2,Profile='ClosestStatic')
    monkeypatch.setattr(b,'_windows',lambda:None)
    monkeypatch.setattr(b,'_ps',lambda *a:raw)
    def no_fallback(): raise AssertionError('explicit groups must be preserved')
    monkeypatch.setattr(b,'_kernel',no_fallback)
    assert b.read('rss',GUID)==raw
    raw['MaxProcessors']=None
    with pytest.raises(ValueError,match='RSS 설정 형식'): b.read('rss',GUID)


def test_rss_null_readback_verifies_and_restores_legacy_failed_journal(monkeypatch,tmp_path):
    b=WindowsOptimization();writes=[]
    old=dict(Enabled=True,BaseProcessorGroup=0,BaseProcessorNumber=0,
             MaxProcessorGroup=0,MaxProcessorNumber=14,MaxProcessors=8,
             NumberOfReceiveQueues=2,Profile='NUMAStatic')
    planned=dict(old,BaseProcessorNumber=14,MaxProcessorNumber=15,
                 MaxProcessors=2,Profile='ClosestStatic')
    current=dict(old)
    def ps(script,*a):
        nonlocal current
        if 'Get-NetAdapterRss -Name' in script: return dict(current)
        if 'Set-NetAdapterRss -Name' in script:
            expected=planned if not writes else old
            for key,value in expected.items():
                if key!='Enabled': assert f'-{key} {value}' in script
            writes.append(dict(expected))
            current=dict(expected,BaseProcessorGroup=None,MaxProcessorGroup=None)
    monkeypatch.setattr(b,'_windows',lambda:None)
    monkeypatch.setattr(b,'_ps',ps)
    monkeypatch.setattr(b,'_kernel',lambda:SimpleNamespace(GetActiveProcessorGroupCount=lambda:1))
    r=Recovery(tmp_path/'recovery.json',b,lambda:True)
    # -NoRestart 쓰기는 재시작 후에야 반영되므로 재연결 직후 확인한다(그룹 null 보완 포함).
    assert r.apply('rss',GUID,planned)=='written' and r.items[0]['state']=='prepared'
    r.flush_network()
    assert r.items[0]['old']==old and r.items[0]['state']=='applied'
    current['MaxProcessors']=1
    errors=r.restore(network=True)
    assert len(errors)==1 and '복구 기록과 달라' in errors[0]
    assert 'MaxProcessors: 현재=1, 적용=2, 원본=8' in errors[0]
    assert GUID not in errors[0]
    assert r.items[0]['state']=='applied' and writes==[planned]
    current=dict(planned,BaseProcessorGroup=None,MaxProcessorGroup=None)
    r.items[0]['state']='failed'
    r._save()
    recovered=Recovery(r.path,b,lambda:False)
    assert not recovered.corrupt and recovered.restore(network=True)==[]
    assert writes==[planned,old] and not recovered.pending
    assert b.read('rss',GUID)==old


@pytest.mark.parametrize('kind',['ack','nodelay','rss'])
def test_selected_guid_shared_by_read_write_restart_and_existing_journal(monkeypatch,tmp_path,kind):
    import json
    b=WindowsOptimization();scripts=[];values={}
    rss=dict(Enabled=False,BaseProcessorGroup=0,BaseProcessorNumber=0,MaxProcessorGroup=0,
             MaxProcessorNumber=3,MaxProcessors=4,NumberOfReceiveQueues=2,Profile='Closest')
    monkeypatch.setattr(b,'_windows',lambda:None)
    def ps(script,*a):
        scripts.append(script)
        return rss if 'Get-NetAdapterRss' in script else None
    monkeypatch.setattr(b,'_ps',ps)
    def query(handle,name):
        if name not in values: raise FileNotFoundError(name)
        return values[name],4
    def delete(handle,name):
        if name not in values: raise FileNotFoundError(name)
        del values[name]
    monkeypatch.setitem(sys.modules,'winreg',SimpleNamespace(HKEY_LOCAL_MACHINE=1,KEY_SET_VALUE=2,REG_DWORD=4,
        OpenKey=lambda *a:nullcontext(object()),QueryValueEx=query,DeleteValue=delete,
        SetValueEx=lambda h,n,_,t,v:values.__setitem__(n,v)))
    b.read(kind,GUID);b.write(kind,GUID,rss if kind=='rss' else 1);b.restart_network(GUID)
    assert len(scripts)==3 and all(b._adapter(GUID) in script for script in scripts)
    if kind=='rss': return
    # Literal v0.10.0 schema: a pending prior change must still restore absence.
    path=tmp_path/'recovery.json'
    path.write_text(json.dumps(dict(schema=1,items=[dict(kind=kind,target=GUID,old=None,applied=1,state='applied')],
                                    restart_targets=[GUID])),encoding='utf-8')
    recovery=Recovery(path,b,lambda:False)
    assert not recovery.corrupt and recovery.pending[0]['old'] is None
    assert recovery.restore(network=True)==[]
    assert not values and not recovery.pending
    recovery.flush_network()
    assert not recovery.restart_targets
    assert all(b._adapter(GUID) in script for script in scripts)


@pytest.mark.parametrize('after_restart', ['changed', 'query_failed', 'unchanged'])
def test_restore_rechecks_rss_after_adapter_restart(tmp_path, after_restart):
    import copy
    from test_optimization import Backend
    import json
    old = dict(Enabled=True, BaseProcessorGroup=0, BaseProcessorNumber=0,
               MaxProcessorGroup=0, MaxProcessorNumber=14, MaxProcessors=8,
               NumberOfReceiveQueues=2, Profile='NUMAStatic')
    applied = dict(old, BaseProcessorNumber=14, MaxProcessorNumber=15,
                   MaxProcessors=2, Profile='ClosestStatic')
    b = Backend()
    key = ('rss', json.dumps(GUID))
    b.values[key] = copy.deepcopy(applied)
    r = Recovery(tmp_path/'recovery.json', b, lambda: True)
    r.items = [dict(kind='rss', target=GUID, old=old, applied=applied, state='failed')]
    r.restart_targets.add(GUID)
    r._save()
    def restart(target):
        b.restarts.append(target)
        if after_restart == 'changed':
            b.values[key] = copy.deepcopy(applied)  # driver changes settings on restart
        elif after_restart == 'query_failed':
            def fail(*args):
                raise OSError('read unavailable')
            b.read = fail
    b.restart_network = restart
    e = Engine(b, r, lambda: True)
    assert e.restore_network()
    e.thread.join(3)
    assert not e.busy
    if after_restart == 'unchanged':
        assert e.status == '원복 완료'
        assert not r.pending and not r.restart_targets
        assert b.values[key] == old and len(b.writes) == 1
        return
    assert '원복 완료' not in e.status
    assert '재연결 후 확인/rss' in e.status
    assert r.restart_targets == {GUID}
    assert r.pending and r.pending[0]['old'] == old
    assert len(b.writes) == 1  # no forced retry after restart
    reloaded = Recovery(r.path, b, lambda: True)
    assert reloaded.pending and reloaded.pending[0]['old'] == old
