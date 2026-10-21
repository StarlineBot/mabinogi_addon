"""Own a pytest process tree; enforce phase-spanning bounds outside its GIL/Qt loop."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid


def public_trace(data,root):
    text=data.decode('utf-8',errors='replace')
    base=str(Path(root).resolve()).replace('\\','/').rstrip('/')+'/'
    def clean(match):
        value=match.group(1).replace('\\','/')
        safe=value[len(base):] if value.casefold().startswith(base.casefold()) else '<external>/'+value.rsplit('/',1)[-1]
        return 'File "'+safe+'"'
    return re.sub(r'File "([^"\n]+)"',clean,text)


def collect(root):
    """Only bounded safe journals/stacks are published; never upload raw dump files."""
    root=Path(root)
    runs=list(root.glob('run-*'))+list((root/'unit').glob('run-*'))+list((root/'native').glob('run-*'))
    for run in sorted(runs)[-4:]:
        public=run/'public';public.mkdir(exist_ok=True)
        unavailable=0;remaining=2*1024*1024;limited=0
        for path in sorted(run.iterdir())[:48]:
            if path.suffix not in ('.raw','.json','.jsonl'): continue
            try:
                with path.open('rb') as stream:
                    size=path.stat().st_size;stream.seek(max(0,size-256*1024));data=stream.read(256*1024)
            except OSError:
                unavailable+=1;continue
            if path.suffix=='.raw':
                # faulthandler includes stack frame locations, never frame locals.
                text=public_trace(data,Path.cwd())
                name=path.stem+'.stack.txt'
            else:
                if size>256*1024: data=data.partition(b'\n')[2]
                text=data.decode('utf-8',errors='replace');name=path.name
            data=text.encode('utf-8')
            if len(data)>remaining: limited+=1;data=data[-remaining:] if remaining else b''
            if data: (public/name).write_bytes(data)
            remaining-=len(data)
        (public/'collection-status.json').write_text(json.dumps({'unavailable_files':unavailable,'limited_files':limited}),encoding='utf-8')


def _stop(process,job):
    if sys.platform=='win32':
        if job is not None: job.close()
        if process.poll() is None: process.kill()
    else:
        if process.poll() is not None: return
        # The unreaped owned leader retains its PID while the group is killed.
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
    process.wait(timeout=5)


def supervise(arguments):
    root=Path(arguments.diagnostics).resolve();root.mkdir(parents=True,exist_ok=True)
    run=root/('run-'+uuid.uuid4().hex);run.mkdir()
    gate=run/'start'
    env=os.environ.copy();env['MABINOGI_TEST_DIAGNOSTICS']=str(run)
    env['MABINOGI_TEST_STACK_SECONDS']=str(arguments.stack_interval)
    command=[sys.executable,'-u','-m','scripts.run_regressions','--child','--gate',str(gate),
             '--diagnostics',str(root),'--',*arguments.pytest_args]
    process=subprocess.Popen(command,env=env,start_new_session=sys.platform!='win32')
    job=None;reason=None;states={};began=last_change=last_print=time.monotonic();signatures={}
    try:
        if sys.platform=='win32':
            from mabinogi_addon.system.process_job import ProcessJob
            job=ProcessJob(process.pid)
        # Pytest and its workers cannot start until the owner has assigned the job/group.
        gate.write_text('ready',encoding='utf-8')
        while process.poll() is None:
            now=time.monotonic()
            for path in list(run.glob('*.json'))[:16]:
                try:
                    stat=path.stat()
                    if stat.st_size>16384: reason='journal size limit';break
                    if signatures.get(path)!=stat.st_mtime_ns:
                        signatures[path]=stat.st_mtime_ns;last_change=now
                        state=json.loads(path.read_text(encoding='utf-8'));states[path]=state
                    state=states[path]
                    if state.get('status')=='running' and now-state['started']>arguments.case_timeout:
                        reason='case timeout: '+json.dumps({k:state.get(k) for k in ('worker','pid','node','case_hash','phase')});break
                except (OSError,ValueError,KeyError): continue
            if any(path.stat().st_size>8*1024*1024 for path in run.glob('*.raw')): reason='stack size limit'
            if now-began>arguments.session_timeout: reason='session timeout'
            if now-last_change>arguments.case_timeout: reason=reason or 'no test progress timeout'
            if reason:
                print('[watchdog] '+reason,flush=True)
                (run/'failure.json').write_text(json.dumps({'failure':reason}),encoding='utf-8')
                break
            if now-last_print>=30:
                active=[{k:s.get(k) for k in ('worker','pid','node','case_hash','phase')} for s in states.values() if s.get('status')=='running']
                print('[watchdog] active '+json.dumps(active),flush=True);last_print=now
            time.sleep(.1)
        result=124 if reason else process.wait()
        return result
    finally:
        _stop(process,job)
        collect(root)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--diagnostics',required=True)
    parser.add_argument('--case-timeout',type=float,default=180)
    parser.add_argument('--session-timeout',type=float,default=1500)
    parser.add_argument('--stack-interval',type=float,default=30)
    parser.add_argument('--child',action='store_true');parser.add_argument('--gate')
    parser.add_argument('--collect-only',action='store_true')
    args,extra=parser.parse_known_args(argv)
    args.pytest_args=extra[1:] if extra[:1]==['--'] else extra
    if any(not math.isfinite(value) or value<=0 for value in (args.case_timeout,args.session_timeout,args.stack_interval)):
        parser.error('timeouts must be finite and positive')
    if args.collect_only: collect(args.diagnostics);return 0
    if args.child:
        deadline=time.monotonic()+30
        while not Path(args.gate).exists():
            if time.monotonic()>deadline: return 125
            time.sleep(.05)
        import pytest
        return pytest.main(['-p','test_support.progress',*args.pytest_args])
    return supervise(args)


if __name__=='__main__': raise SystemExit(main())
