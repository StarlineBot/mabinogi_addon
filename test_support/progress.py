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


class Journal:
    def __init__(self, config):
        self.root=Path(os.environ['MABINOGI_TEST_DIAGNOSTICS'])
        self.root.mkdir(parents=True,exist_ok=True)
        worker=getattr(config,'workerinput',{}).get('workerid','controller')
        self.key=f'{worker}-{os.getpid()}'
        self.path=self.root/(self.key+'.json')
        self.events=self.root/(self.key+'.jsonl')
        self.raw=(self.root/(self.key+'.raw')).open('w+b')
        self.record=dict(worker=worker,pid=os.getpid(),node='',case_hash='',phase='configure',status='idle',
                         started=_CLOCK())
        self.interval=float(os.environ.get('MABINOGI_TEST_STACK_SECONDS','30'))
        self.emit()
        self.arm()

    def arm(self):
        faulthandler.cancel_dump_traceback_later()
        self.raw.seek(0);self.raw.truncate()
        faulthandler.dump_traceback_later(self.interval,repeat=True,file=self.raw)

    def emit(self,**fields):
        self.record.update(fields)
        self.record['utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        text=json.dumps(self.record,ensure_ascii=True)+'\n'
        temporary=self.path.with_suffix('.tmp')
        with _OPEN(temporary,'w',encoding='utf-8') as stream: stream.write(text)
        _REPLACE(temporary,self.path)
        if self.events.exists() and self.events.stat().st_size>2*1024*1024:
            data=self.events.read_bytes()[-1024*1024:]
            self.events.write_bytes(data.partition(b'\n')[2])
        with _OPEN(self.events,'a',encoding='utf-8') as stream: stream.write(text)


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
    if _state: _state.emit(phase='session-finish',status='idle',exitstatus=int(exitstatus))


def pytest_unconfigure(config):
    if _state:
        _state.emit(phase='interpreter-exit',status='idle')
        # Keep the C timer alive through threading._shutdown: a Python thread
        # leaked after fixture teardown must still leave a recoverable stack.
        def close():
            faulthandler.cancel_dump_traceback_later()
            _state.raw.close()
        atexit.register(close)
