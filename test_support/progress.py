"""Opt-in pytest worker journals and C-level stack snapshots for an external watchdog."""
import atexit
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import time
import pytest

_state=None
_CLOCK=time.monotonic
_REPLACE=os.replace
_OPEN=open
_SLEEP=time.sleep
_WRITE=os.write


class Journal:
    def __init__(self, config):
        self.root=Path(os.environ['MABINOGI_TEST_DIAGNOSTICS'])
        worker=getattr(config,'workerinput',{}).get('workerid','controller')
        self.key=f'{worker}-{os.getpid()}'
        self.path=self.root/(self.key+'.json')
        self.events=self.root/(self.key+'.jsonl')
        self.raw=None
        self.failed=None
        self.record=dict(worker=worker,pid=os.getpid(),node='',case_hash='',phase='configure',status='idle',
                         started=_CLOCK())
        self.interval=float(os.environ.get('MABINOGI_TEST_STACK_SECONDS','30'))
        def initialize():
            self.root.mkdir(parents=True,exist_ok=True)
            self.raw=_OPEN(self.root/(self.key+'.raw'),'w+b')
        self.io('initialize',initialize)
        if not self.failed:
            self.emit()
            self.arm()

    def fail(self,operation,error):
        if self.failed: return
        # Never include exception messages, paths or test parameter values.
        self.failed=dict(worker=self.record['worker'],pid=os.getpid(),operation=operation,
                         error=type(error).__name__,errno=error.errno,winerror=getattr(error,'winerror',None))
        notice=json.dumps(self.failed)+'\n'
        try: _WRITE(2,('[watchdog] diagnostic infrastructure failure: '+notice).encode())
        except OSError: pass
        try:
            # A separate, write-once channel: no replace and no shared reader handle.
            with _OPEN(self.root/(self.key+'.error'),'xb') as stream: stream.write(notice.encode())
        except OSError: pass

    def io(self,operation,action):
        if self.failed: return
        for attempt in range(8):
            try: return action()
            except OSError as error:
                if attempt==7:
                    self.fail(operation,error)
                    return
                _SLEEP(min(.01*2**attempt,.16))

    def arm(self):
        def reset():
            faulthandler.cancel_dump_traceback_later()
            self.raw.seek(0);self.raw.truncate()
            faulthandler.dump_traceback_later(self.interval,repeat=True,file=self.raw)
        self.io('stack reset',reset)

    def emit(self,**fields):
        if self.failed: return
        self.record.update(fields)
        self.record['utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        text=json.dumps(self.record,ensure_ascii=True)+'\n'
        temporary=self.path.with_suffix('.tmp')
        def snapshot():
            with _OPEN(temporary,'w',encoding='utf-8') as stream: stream.write(text)
            _REPLACE(temporary,self.path)
        self.io('snapshot',snapshot)
        def events():
            if self.events.exists() and self.events.stat().st_size>2*1024*1024:
                with _OPEN(self.events,'rb') as stream:
                    stream.seek(-1024*1024,os.SEEK_END);data=stream.read(1024*1024)
                with _OPEN(self.events,'wb') as stream: stream.write(data.partition(b'\n')[2])
            with _OPEN(self.events,'a',encoding='utf-8') as stream: stream.write(text)
        self.io('event journal',events)


def pytest_configure(config):
    global _state
    if os.environ.get('MABINOGI_TEST_DIAGNOSTICS'): _state=Journal(config)


@pytest.hookimpl(hookwrapper=True,tryfirst=True)
def pytest_collection(session):
    if _state: _state.emit(phase='collection',started=_CLOCK(),status='running')
    yield
    if _state: _state.emit(status='idle')


@pytest.hookimpl(hookwrapper=True,tryfirst=True)
def pytest_runtest_protocol(item,nextitem):
    if _state:
        _state.arm()
        # No parameter values or absolute user paths enter the journal.
        relative=Path(item.path).relative_to(item.config.rootpath).as_posix()
        function=getattr(item,'originalname',None) or item.name.split('[',1)[0]
        _state.emit(node=relative+'::'+function,case_hash=hashlib.sha256(item.nodeid.encode()).hexdigest()[:12],
                    phase='protocol',status='running',outcome=None,started=_CLOCK())
    yield
    if _state: _state.emit(phase='complete',status='idle')


@pytest.hookimpl(hookwrapper=True,tryfirst=True)
def pytest_runtest_setup(item):
    if _state: _state.emit(phase='setup')
    yield


@pytest.hookimpl(hookwrapper=True,tryfirst=True)
def pytest_runtest_call(item):
    if _state: _state.emit(phase='call')
    yield


@pytest.hookimpl(hookwrapper=True,tryfirst=True)
def pytest_runtest_teardown(item,nextitem):
    if _state: _state.emit(phase='teardown')
    yield


def pytest_runtest_logreport(report):
    if _state: _state.emit(outcome=report.outcome)


def pytest_sessionfinish(session,exitstatus):
    if _state:
        _state.emit(phase='session-finish',status='idle',exitstatus=int(exitstatus))
        if _state.failed and not exitstatus: session.exitstatus=pytest.ExitCode.INTERNAL_ERROR


def pytest_unconfigure(config):
    if _state:
        _state.emit(phase='interpreter-exit',status='idle')
        # Keep the C timer alive through threading._shutdown: a Python thread
        # leaked after fixture teardown must still leave a recoverable stack.
        def close():
            faulthandler.cancel_dump_traceback_later()
            if _state.raw is not None:
                try: _state.raw.close()
                except OSError: pass
        atexit.register(close)
