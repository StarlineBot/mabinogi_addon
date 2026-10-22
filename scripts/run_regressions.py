"""Own a pytest process tree; enforce phase-spanning bounds outside its GIL/Qt loop."""
import argparse
import json
import math
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from test_support.diagnostic_signal import ENVIRONMENT, FailureChannel

_console = None


class Console:
    """Console backpressure must never block deadlines or owned-process cleanup."""
    def __init__(self):
        self.messages = queue.Queue(maxsize=32)
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def send(self, data, descriptor=1):
        try: self.messages.put_nowait((descriptor, data[:8192]))
        except queue.Full: pass

    def _write(self):
        while True:
            descriptor, data = self.messages.get()
            if descriptor is None:
                data.set()
                continue
            try:
                while data:
                    data = data[os.write(descriptor, data):]
            except OSError:
                pass

    def flush(self):
        finished = threading.Event()
        try: self.messages.put_nowait((None, finished))
        except queue.Full: return
        finished.wait(.2)


def notice(message):
    if _console is None:
        print(message, flush=True)
    else:
        _console.send((message+'\n').encode('utf-8', errors='replace'))


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
    root=Path(root);success=True
    try: runs=[run for scope in ('','unit','native','smoke') for run in (root/scope).glob('run-*')]
    except OSError:
        notice('[watchdog] diagnostic collection failed: discovery')
        return False
    for run in sorted(runs)[-4:]:
        public=run/'public'
        try:
            public.mkdir(exist_ok=True)
            paths=sorted(run.iterdir())[:48]
        except OSError:
            success=False;continue
        unavailable=0;remaining=2*1024*1024;limited=0
        for path in paths:
            if path.suffix not in ('.raw','.json','.jsonl','.error'): continue
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
            if data:
                try: (public/name).write_bytes(data)
                except OSError: unavailable+=1
            remaining-=len(data)
        try: (public/'collection-status.json').write_text(json.dumps({'unavailable_files':unavailable,'limited_files':limited}),encoding='utf-8')
        except OSError: unavailable+=1
        if unavailable: success=False
    if not success: notice('[watchdog] diagnostic collection failed: bounded files unavailable')
    return success


def diagnostic_failure(run):
    # Marker contents are fixed-schema/sanitized by the writer. Existence alone
    # is sufficient; a reader can never lock a destination being replaced here.
    return next(run.glob('*.error'),None) is not None


def failure_record(run,reason):
    try: (run/'failure.json').write_text(json.dumps({'failure':reason}),encoding='utf-8')
    except OSError: notice('[watchdog] diagnostic failure record unavailable')
    notice('[watchdog] '+reason)


def relay_errors(stream,failed):
    """An independent notification channel still works when the disk is unwritable."""
    prefix=b'[watchdog] diagnostic infrastructure failure: '
    tail=b''
    try:
        while data:=os.read(stream.fileno(),4096):
            if prefix in tail+data: failed.set()
            tail=(tail+data)[-len(prefix):]
            if _console is None: os.write(2,data)
            else: _console.send(data,2)
    except OSError:
        failed.set()
    finally: stream.close()


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
    io_failed=threading.Event()
    try: channel=FailureChannel(io_failed,run)
    except OSError:
        failure_record(run,'diagnostic infrastructure failure: notification channel')
        collect(root)
        return 3
    env[ENVIRONMENT]=channel.endpoint
    command=[sys.executable,'-u','-m','scripts.run_regressions','--child','--gate',str(gate),
             '--diagnostics',str(root),'--',*arguments.pytest_args]
    try:
        process=subprocess.Popen(command,env=env,start_new_session=sys.platform!='win32',stderr=subprocess.PIPE)
    except BaseException:
        channel.close()
        raise
    relay=threading.Thread(target=relay_errors,args=(process.stderr,io_failed),daemon=True)
    relay.start()
    job=None;reason=None;states={};began=last_change=last_print=time.monotonic();signatures={};read_errors={};result=3
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
                        state=json.loads(path.read_text(encoding='utf-8'));states[path]=state
                        signatures[path]=stat.st_mtime_ns;last_change=now
                        read_errors.pop(path,None)
                    state=states[path]
                    if state.get('status')=='running' and now-state['started']>arguments.case_timeout:
                        reason='case timeout: '+json.dumps({k:state.get(k) for k in ('worker','pid','node','case_hash','phase')});break
                except (OSError,ValueError,KeyError):
                    if now-read_errors.setdefault(path,now)>1:
                        reason='diagnostic infrastructure failure: snapshot read';break
            if any(path.stat().st_size>8*1024*1024 for path in run.glob('*.raw')): reason='stack size limit'
            if now-began>arguments.session_timeout: reason='session timeout'
            if now-last_change>arguments.case_timeout: reason=reason or 'no test progress timeout'
            if (io_failed.is_set() or diagnostic_failure(run)) and reason is None: reason='diagnostic infrastructure failure: journal writer'
            if reason:
                failure_record(run,reason)
                break
            if now-last_print>=30:
                active=[{k:s.get(k) for k in ('worker','pid','node','case_hash','phase')} for s in states.values() if s.get('status')=='running']
                notice('[watchdog] active '+json.dumps(active));last_print=now
            time.sleep(.1)
        result=(3 if reason.startswith('diagnostic infrastructure') else 124) if reason else process.wait()
        if not reason and diagnostic_failure(run):
            failure_record(run,'diagnostic infrastructure failure: journal writer')
            result=result or 3
    finally:
        try: _stop(process,job)
        except (OSError,subprocess.SubprocessError):
            notice('[watchdog] owned process cleanup failed')
            result=result or 3
        relay.join(timeout=1)
        channel.close()
        if io_failed.is_set(): result=result or 3
        if not collect(root): result=result or 3
    return result


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
    if args.collect_only: return 0 if collect(args.diagnostics) else 3
    if args.child:
        deadline=time.monotonic()+30
        while not Path(args.gate).exists():
            if time.monotonic()>deadline: return 125
            time.sleep(.05)
        import pytest
        result=pytest.main(['-p','test_support.progress',*args.pytest_args])
        from test_support import progress
        return result or (3 if progress._state is not None and progress._state.failed else 0)
    return supervise(args)


if __name__=='__main__':
    _console=Console()
    try: raise SystemExit(main())
    finally: _console.flush()
