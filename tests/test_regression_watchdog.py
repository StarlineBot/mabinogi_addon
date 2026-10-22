"""External deadlines include setup/teardown/native GIL stalls and xdist children."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from scripts.run_regressions import collect,public_trace

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('phase',['setup','call','teardown','native'])
def test_external_watchdog_fails_stuck_phase_with_safe_stack(tmp_path,phase):
    suite=tmp_path/'suite';suite.mkdir()
    block='threading.Event().wait()'
    if phase=='native':
        block="ctypes.PyDLL('kernel32').Sleep(60000) if sys.platform=='win32' else ctypes.PyDLL(None).sleep(60)"
    code='import pytest,threading,ctypes,sys\n@pytest.fixture\ndef resource():\n'
    code+='    '+(block if phase=='setup' else 'pass')+'\n    yield\n'
    code+='    '+(block if phase=='teardown' else 'pass')+'\ndef test_stall(resource):\n'
    code+='    '+(block if phase in ('call','native') else 'pass')+'\n'
    (suite/'test_stall.py').write_text(code,encoding='utf-8')
    diagnostics=tmp_path/'diagnostics'
    result=subprocess.run([sys.executable,'-m','scripts.run_regressions','--diagnostics',str(diagnostics),
        '--case-timeout','1.5','--session-timeout','15','--stack-interval','.25','--','-q',str(suite)],
        cwd=ROOT,capture_output=True,text=True,timeout=20)
    assert result.returncode==124,result.stdout+result.stderr
    records=[json.loads(p.read_text(encoding='utf-8')) for p in diagnostics.glob('run-*/*.json') if p.name!='failure.json']
    expected='call' if phase=='native' else phase
    assert any(s['phase']==expected and s['node'].endswith('test_stall') for s in records),records
    stack=''.join(p.read_text(encoding='utf-8') for p in diagnostics.glob('run-*/public/*.stack.txt'))
    assert 'test_stall.py' in stack and str(tmp_path) not in stack
    assert 'case timeout' in result.stdout


def test_xdist_healthy_suite_retains_all_cases_and_nonzero_assertion(tmp_path):
    suite=tmp_path/'suite';suite.mkdir()
    (suite/'test_small.py').write_text('import pytest\n@pytest.mark.parametrize("n",range(4))\ndef test_good(n): assert n>=0\ndef test_bad(): assert False\n',encoding='utf-8')
    diagnostics=tmp_path/'diagnostics'
    result=subprocess.run([sys.executable,'-m','scripts.run_regressions','--diagnostics',str(diagnostics),
        '--case-timeout','15','--session-timeout','30','--','-n','2','-q',str(suite)],
        cwd=ROOT,capture_output=True,text=True,timeout=35)
    assert result.returncode==1 and '4 passed' in result.stdout and '1 failed' in result.stdout,result.stdout+result.stderr
    records=[json.loads(p.read_text(encoding='utf-8')) for p in diagnostics.glob('run-*/*.json')]
    assert {s.get('worker') for s in records}>={'gw0','gw1','controller'}
    assert not list(diagnostics.glob('run-*/public/*.raw'))


@pytest.mark.parametrize('scope',['','unit','native','smoke'])
def test_public_artifacts_are_bounded_and_remove_absolute_paths(tmp_path,scope):
    run=tmp_path/scope/'run-example';run.mkdir(parents=True)
    (run/'gw0-1.raw').write_text('Thread 0x123:\n  File "C:\\Users\\PRIVATE\\secret.py", line 1 in wait\n'+
        '  File "'+str(ROOT/'tests/test_example.py')+'", line 2 in test_example\n',encoding='utf-8')
    collect(tmp_path)
    text=(run/'public/gw0-1.stack.txt').read_text(encoding='utf-8')
    assert 'PRIVATE' not in text and 'tests/test_example.py' in text and '<external>/secret.py' in text


def test_timeout_kills_descendants_but_preserves_other_owned_process(tmp_path):
    import time
    suite=tmp_path/'suite';suite.mkdir();pidfile=tmp_path/'descendant.pid'
    grandchild="import threading;threading.Event().wait()"
    code=('import subprocess,sys,threading\nfrom pathlib import Path\n'
          'def test_stall():\n'
          f'    p=subprocess.Popen([sys.executable,"-c",{grandchild!r}])\n'
          f'    Path({str(pidfile)!r}).write_text(str(p.pid),encoding="utf-8")\n'
          '    threading.Event().wait()\n')
    (suite/'test_tree.py').write_text(code,encoding='utf-8')
    sentinel=subprocess.Popen([sys.executable,'-c',grandchild])
    try:
        result=subprocess.run([sys.executable,'-m','scripts.run_regressions','--diagnostics',str(tmp_path/'diagnostics'),
            '--case-timeout','2','--session-timeout','15','--stack-interval','.25','--','-q',str(suite)],
            cwd=ROOT,capture_output=True,text=True,timeout=20)
        assert result.returncode==124,result.stdout+result.stderr
        assert sentinel.poll() is None
        pid=int(pidfile.read_text(encoding='utf-8'))
        def alive():
            if sys.platform=='win32':
                import ctypes
                k=ctypes.WinDLL('kernel32',use_last_error=True)
                k.OpenProcess.restype=ctypes.c_void_p
                k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
                k.CloseHandle.argtypes=[ctypes.c_void_p]
                handle=k.OpenProcess(0x100000,False,pid)
                if not handle: return False
                try: return k.WaitForSingleObject(handle,0)==258
                finally: k.CloseHandle(handle)
            status=Path(f'/proc/{pid}/stat')
            if status.exists() and status.read_text(encoding='utf-8').split(') ',1)[1].startswith('Z'): return False
            try: os.kill(pid,0);return True
            except ProcessLookupError: return False
        deadline=time.monotonic()+3
        while alive() and time.monotonic()<deadline: time.sleep(.02)
        assert not alive()
    finally:
        sentinel.kill();sentinel.wait(timeout=3)


def test_passing_test_with_stuck_interpreter_exit_still_fails(tmp_path):
    suite=tmp_path/'suite';suite.mkdir()
    (suite/'test_exit.py').write_text('import threading\ndef test_thread():\n    threading.Thread(target=threading.Event().wait,daemon=False).start()\n',encoding='utf-8')
    diagnostics=tmp_path/'diagnostics'
    result=subprocess.run([sys.executable,'-m','scripts.run_regressions','--diagnostics',str(diagnostics),
        '--case-timeout','1.5','--session-timeout','15','--stack-interval','.25','--','-q',str(suite)],
        cwd=ROOT,capture_output=True,text=True,timeout=20)
    assert result.returncode==124 and '1 passed' in result.stdout and 'no test progress timeout' in result.stdout
    records=[json.loads(p.read_text(encoding='utf-8')) for p in diagnostics.glob('run-*/*.json') if p.name!='failure.json']
    assert any(s['phase']=='interpreter-exit' for s in records)
    stack=''.join(p.read_text(encoding='utf-8') for p in diagnostics.glob('run-*/public/*.stack.txt'))
    assert 'threading.py' in stack


@pytest.mark.parametrize('value',['0','nan','inf'])
def test_invalid_deadline_never_disables_watchdog(tmp_path,value):
    from scripts.run_regressions import main
    with pytest.raises(SystemExit) as caught: main(['--diagnostics',str(tmp_path),'--collect-only','--case-timeout',value])
    assert caught.value.code==2


def test_public_diagnostic_budget_reports_truncation(tmp_path):
    run=tmp_path/'run-budget';run.mkdir()
    data=('Thread 0x123:\n  File "/home/private/stack.py", line 1 in wait\n'*6000).encode()
    for n in range(16): (run/f'gw{n}-1.raw').write_bytes(data)
    collect(tmp_path)
    published=list((run/'public').iterdir())
    assert sum(p.stat().st_size for p in published)<=2*1024*1024+256
    status=json.loads((run/'public/collection-status.json').read_text(encoding='utf-8'))
    assert status['limited_files']>0 and status['unavailable_files']==0
    assert all('/home/private' not in p.read_text(encoding='utf-8') for p in published)


def test_transient_replace_denial_recovers_through_actual_report_hook(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from test_support import progress
    monkeypatch.setenv('MABINOGI_TEST_DIAGNOSTICS',str(tmp_path))
    monkeypatch.setattr(progress.Journal,'arm',lambda self:None)
    journal=progress.Journal(SimpleNamespace());attempts=[];replace=progress._REPLACE
    def transient(source,target):
        attempts.append(1)
        if len(attempts)==1: raise PermissionError(13,'denied')
        return replace(source,target)
    monkeypatch.setattr(progress,'_REPLACE',transient)
    monkeypatch.setattr(progress,'_state',journal)
    try:
        progress.pytest_runtest_logreport(SimpleNamespace(outcome='passed'))
        assert len(attempts)==2 and not journal.failed
        assert json.loads(journal.path.read_text(encoding='utf-8'))['outcome']=='passed'
        assert not list(tmp_path.glob('*.error'))
    finally: journal.raw.close()


@pytest.mark.parametrize('operation',['snapshot','snapshot-write','append','rotate-read','rotate-write','stack','all-writes'])
def test_permanent_journal_io_failure_is_bounded_and_explicit(tmp_path,monkeypatch,operation):
    from types import SimpleNamespace
    from test_support import progress
    monkeypatch.setenv('MABINOGI_TEST_DIAGNOSTICS',str(tmp_path))
    original_arm=progress.Journal.arm
    monkeypatch.setattr(progress.Journal,'arm',lambda self:None)
    journal=progress.Journal(SimpleNamespace())
    sleeps=[];monkeypatch.setattr(progress,'_SLEEP',sleeps.append)
    original_open=progress._OPEN
    def deny(*args,**kwargs): raise PermissionError(13,'private path must never enter the error channel')
    if operation=='snapshot': monkeypatch.setattr(progress,'_REPLACE',deny)
    else:
        if operation.startswith('rotate'): journal.events.write_bytes(b'x'*(2*1024*1024+1))
        def opened(path,mode='r',*args,**kwargs):
            if (operation=='all-writes' or (operation=='snapshot-write' and Path(path).suffix=='.tmp') or
                (Path(path)==journal.events and mode=={'append':'a','rotate-read':'rb','rotate-write':'wb'}.get(operation))):
                return deny()
            return original_open(path,mode,*args,**kwargs)
        monkeypatch.setattr(progress,'_OPEN',opened)
    try:
        if operation=='stack':
            class Broken:
                def seek(self,*args): deny()
            raw=journal.raw;journal.raw=Broken()
            try: original_arm(journal)
            finally: journal.raw=raw
        else: journal.emit(outcome='passed')
        assert journal.failed and len(sleeps)==7 and sum(sleeps)<1
        assert journal.failed['error']=='PermissionError'
        if operation=='all-writes': assert not list(tmp_path.glob('*.error'))
        else:
            marker=next(tmp_path.glob('*.error')).read_text(encoding='utf-8')
            assert 'private path' not in marker and len(marker)<512
        previous=journal.path.read_bytes()
        journal.emit(phase='fake-progress')
        assert journal.path.read_bytes()==previous and len(sleeps)==7
        monkeypatch.setattr(progress,'_state',journal)
        session=SimpleNamespace(exitstatus=0)
        progress.pytest_sessionfinish(session,0)
        assert session.exitstatus==3
        session.exitstatus=1;progress.pytest_sessionfinish(session,1)
        assert session.exitstatus==1
    finally: journal.raw.close()


@pytest.mark.parametrize('marker_available',[True,False])
@pytest.mark.parametrize('capture_enabled',[True,False])
def test_writer_error_stops_owned_suite_as_infrastructure_failure(tmp_path,marker_available,capture_enabled):
    suite=tmp_path/'suite';suite.mkdir()
    (suite/'test_broken.py').write_text('''import threading
from test_support import progress
def test_broken():
    def denied(*args,**kwargs): raise PermissionError(13, 'denied')
    progress._REPLACE=denied
    if not MARKER_AVAILABLE:
        progress._OPEN=denied
    progress._state.emit(outcome='passed')
    threading.Event().wait()
'''.replace('MARKER_AVAILABLE',repr(marker_available)),encoding='utf-8')
    diagnostics=tmp_path/'diagnostics'
    capture=[] if capture_enabled else ['-s']
    result=subprocess.run([sys.executable,'-m','scripts.run_regressions','--diagnostics',str(diagnostics),
        '--case-timeout','3','--session-timeout','15','--','-q',*capture,str(suite)],
        cwd=ROOT,capture_output=True,text=True,timeout=12)
    assert result.returncode==3,result.stdout+result.stderr
    assert 'diagnostic infrastructure failure' in result.stdout
    assert bool(list(diagnostics.glob('run-*/public/*.error')))==marker_available


@pytest.mark.parametrize('descriptor',[1,2])
def test_blocked_console_does_not_block_deadline_or_cleanup(tmp_path,descriptor):
    suite=tmp_path/'suite';suite.mkdir()
    suffix=''
    if descriptor==2:
        suffix=('    from test_support import progress\n'
                '    def denied(*a,**k): raise PermissionError(13,"denied")\n'
                '    progress._REPLACE=progress._OPEN=denied\n'
                '    progress._state.emit(outcome="passed")\n'
                '    threading.Event().wait()\n')
    (suite/'test_output.py').write_text(
        f'import os,threading\ndef test_output():\n    os.write({descriptor},b"x"*(4*1024*1024))\n'+suffix,encoding='utf-8')
    diagnostics=tmp_path/'diagnostics'
    process=subprocess.Popen([sys.executable,'-m','scripts.run_regressions',
        '--diagnostics',str(diagnostics),'--case-timeout','3','--session-timeout','15',
        '--stack-interval','.25','--','-q','-s',str(suite)],
        cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    expired=False
    try:
        try: code=process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            expired=True;process.kill()
        # Read only after the watchdog must already have stopped its owned suite.
        process.communicate(timeout=10)
        assert not expired,'watchdog deadline blocked on a full console pipe'
        assert code==(124 if descriptor==1 else 3)
        record=json.loads(next(diagnostics.glob('run-*/public/failure.json')).read_text(encoding='utf-8'))
        assert ('timeout' if descriptor==1 else 'diagnostic infrastructure') in record['failure']
    finally:
        if process.poll() is None: process.kill();process.communicate(timeout=10)


@pytest.mark.parametrize('original_code',[0,1,124])
def test_collection_failure_preserves_test_or_timeout_exit(tmp_path,monkeypatch,original_code,capsys):
    from types import SimpleNamespace
    from scripts import run_regressions as runner
    class Process:
        pid=123
        stderr=None
        def poll(self): return original_code
        def wait(self,**kwargs): return original_code
    monkeypatch.setattr(runner.subprocess,'Popen',lambda *a,**k:Process())
    monkeypatch.setattr(runner,'_stop',lambda *a:None)
    monkeypatch.setattr(runner,'relay_errors',lambda *a:None)
    monkeypatch.setattr(runner,'collect',lambda *a:False)
    # Do not allocate a real Windows Job for a synthetic process.
    if sys.platform=='win32':
        from mabinogi_addon.system import process_job
        monkeypatch.setattr(process_job,'ProcessJob',lambda *a:None)
    args=SimpleNamespace(diagnostics=str(tmp_path),stack_interval=30,pytest_args=[],case_timeout=180,session_timeout=1500)
    assert runner.supervise(args)==(original_code or 3)


def test_collector_retains_other_evidence_on_output_failure(tmp_path,monkeypatch):
    run=tmp_path/'run-example';run.mkdir()
    (run/'a.json').write_text('{}',encoding='utf-8');(run/'b.json').write_text('{}',encoding='utf-8')
    original=Path.write_bytes
    def write(path,data):
        if path.name=='a.json' and path.parent.name=='public': raise PermissionError(13,'denied')
        return original(path,data)
    monkeypatch.setattr(Path,'write_bytes',write)
    assert collect(tmp_path) is False
    assert (run/'public/b.json').read_text(encoding='utf-8')=='{}'
    assert json.loads((run/'public/collection-status.json').read_text(encoding='utf-8'))['unavailable_files']==1


def test_persistent_reader_failure_is_infrastructure_error_without_fake_progress(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from scripts import run_regressions as runner
    class Process:
        pid=123;stderr=None
        def poll(self): return None
    def start(*args,**kwargs):
        (Path(kwargs['env']['MABINOGI_TEST_DIAGNOSTICS'])/'worker.json').write_text('{}',encoding='utf-8')
        return Process()
    original=Path.read_text
    def read(path,*args,**kwargs):
        if path.name=='worker.json': raise PermissionError(13,'denied')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',read)
    monkeypatch.setattr(runner.subprocess,'Popen',start)
    monkeypatch.setattr(runner,'relay_errors',lambda *a:None)
    monkeypatch.setattr(runner,'_stop',lambda *a:None)
    monkeypatch.setattr(runner,'collect',lambda *a:True)
    if sys.platform=='win32':
        from mabinogi_addon.system import process_job
        monkeypatch.setattr(process_job,'ProcessJob',lambda *a:None)
    args=SimpleNamespace(diagnostics=str(tmp_path),stack_interval=30,pytest_args=[],case_timeout=30,session_timeout=40)
    assert runner.supervise(args)==3
    failure=json.loads(next(tmp_path.glob('run-*/failure.json')).read_text(encoding='utf-8'))
    assert failure['failure']=='diagnostic infrastructure failure: snapshot read'
