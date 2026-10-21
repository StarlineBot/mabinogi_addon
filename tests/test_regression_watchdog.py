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


def test_public_artifacts_are_bounded_and_remove_absolute_paths(tmp_path):
    run=tmp_path/'run-example';run.mkdir()
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
