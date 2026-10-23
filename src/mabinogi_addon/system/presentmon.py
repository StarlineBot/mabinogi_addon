"""Owned console collector. No service install, elevation or foreign ETW cleanup."""
import ctypes
import hashlib
from pathlib import Path
import sys
import os
import re
from functools import lru_cache
import uuid
from PySide6.QtCore import QObject, QProcess, Signal
from .. import paths

SHA256 = '364e5d98d4d134bd54dd25c22ed2ca2f4883f8bc3ed6502bee0c151e3436d30c'


@lru_cache(maxsize=1)
def _clock_api():
    if sys.platform != 'win32':
        raise OSError('FPS 측정은 Windows에서 사용할 수 있어요.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    frequency = ctypes.c_longlong()
    if not kernel.QueryPerformanceFrequency(ctypes.byref(frequency)) or frequency.value <= 0:
        raise OSError('Windows 프레임 시계를 확인하지 못했어요.')
    return kernel.QueryPerformanceCounter, frequency.value


def clock():
    counter = ctypes.c_longlong()
    query, frequency = _clock_api()
    if not query(ctypes.byref(counter)):
        raise OSError('Windows 프레임 시계를 확인하지 못했어요.')
    return counter.value / frequency, frequency


def game_context(game, target):
    import win32gui
    from .dialogue_visibility import desktop_unlocked
    active = bool(target and target[1] == game['pid'] and desktop_unlocked()
                  and not win32gui.IsIconic(target[0]) and win32gui.GetForegroundWindow() == target[0])
    return active, tuple(target) if target else None


class Wnode(ctypes.Structure):
    _fields_ = [('BufferSize',ctypes.c_uint32),('ProviderId',ctypes.c_uint32),
        ('HistoricalContext',ctypes.c_uint64),('TimeStamp',ctypes.c_int64),
        ('Guid',ctypes.c_ubyte*16),('ClientContext',ctypes.c_uint32),('Flags',ctypes.c_uint32)]
class Properties(ctypes.Structure):
    _fields_ = [('Wnode',Wnode)] + [(name,ctypes.c_uint32) for name in
        ('BufferSize','MinimumBuffers','MaximumBuffers','MaximumFileSize','LogFileMode',
         'FlushTimer','EnableFlags','AgeLimit','NumberOfBuffers','FreeBuffers','EventsLost',
         'BuffersWritten','LogBuffersLost','RealTimeBuffersLost')] + [
        ('LoggerThreadId',ctypes.c_void_p),('LogFileNameOffset',ctypes.c_uint32),('LoggerNameOffset',ctypes.c_uint32)]

@lru_cache(maxsize=1)
def _etw_api():
    fn = ctypes.WinDLL('advapi32',use_last_error=True).ControlTraceW
    fn.argtypes = [ctypes.c_uint64,ctypes.c_wchar_p,ctypes.POINTER(Properties),ctypes.c_uint32]
    fn.restype = ctypes.c_uint32
    return fn


def session_losses(session, *, stop=False):
    """Query loss counters, or explicitly stop the recorded owned UUID during cleanup."""
    if not session or not re.fullmatch(r'MabinogiAddon-[0-9a-f]{32}',session):
        raise ValueError('Invalid owned ETW session')
    buffer = ctypes.create_string_buffer(ctypes.sizeof(Properties)+4096)
    properties = Properties.from_buffer(buffer)
    properties.Wnode.BufferSize = ctypes.sizeof(buffer)
    properties.LoggerNameOffset = ctypes.sizeof(Properties)
    properties.LogFileNameOffset = ctypes.sizeof(Properties)+2048
    fn = _etw_api()
    code = fn(0,session,ctypes.byref(properties),1 if stop else 0)
    if stop and code == 4201: return 0
    if code: raise OSError('프레임 수집 상태를 확인하지 못했어요. 측정을 다시 시작해 주세요.')
    return properties.EventsLost + properties.LogBuffersLost + properties.RealTimeBuffersLost


def executable():
    path = paths.resource_dir() / 'presentmon' / 'PresentMon.exe'
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
        raise OSError('포함된 FPS 수집 도구가 없거나 손상됐어요. 앱 파일을 확인해 주세요.')
    return path


def arguments(pid, session):
    if type(pid) is not int or pid <= 0 or not session.startswith('MabinogiAddon-'):
        raise ValueError('Invalid collector identity')
    return ['--process_id',str(pid),'--session_name',session,'--output_stdout',
            '--no_console_stats','--v1_metrics','--qpc_time','--no_track_display',
            '--no_track_gpu','--no_track_input','--terminate_on_proc_exit']


class Collector(QObject):
    line = Signal(str)
    failed = Signal(str)
    ended = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.started.connect(self._started)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._error_output)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.active = False
        self.buffer = b''
        self.session = None
        self.path = None
        self.job = None
        self.cleanup_problem = ''
        self.marker = paths.user_data_dir().parent / 'StarlineMabinogiAddonRuntime' / 'fps-session.txt'
        if self.marker.exists():
            try:
                if self.marker.stat().st_size>128: raise ValueError('large marker')
                session = self.marker.read_text(encoding='utf-8').strip()
                if not re.fullmatch(r'MabinogiAddon-[0-9a-f]{32}',session): raise ValueError('invalid marker')
                self.session = session
            except Exception:
                self.cleanup_problem = '이전 FPS 복구 기록이 손상됐어요. 추정한 세션을 종료하지 않아요.'

    @property
    def pending(self):
        return bool(self.session or self.cleanup_problem)

    def _started(self):
        if not self.active: return
        try:
            from .process_job import ProcessJob
            self.job = ProcessJob(int(self.process.processId()))
        except Exception:
            self.failed.emit('수집기의 종료 보호를 준비하지 못했어요. 측정을 중단해요.')

    def start(self, pid):
        if self.active:
            raise RuntimeError('이미 측정 중이에요.')
        clock()
        if self.pending and not self.stop():
            raise RuntimeError(self.cleanup_problem or '이전 FPS 수집기 정리가 필요해요.')
        self.path = executable()
        self.session = 'MabinogiAddon-' + uuid.uuid4().hex
        self.marker.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.marker.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('x',encoding='utf-8') as file:
                os.chmod(temporary,0o600)
                file.write(self.session)
                file.flush();os.fsync(file.fileno())
            os.replace(temporary,self.marker)
        finally: temporary.unlink(missing_ok=True)
        self.buffer = b''
        self.active = True
        self.process.start(str(self.path), arguments(pid, self.session))

    def _read(self):
        data = bytes(self.process.readAllStandardOutput())
        if not self.active: return
        self.buffer += data
        if len(self.buffer) > 512*1024:
            self.failed.emit('프레임 수신이 밀려 측정을 중단해요.')
            return
        while b'\n' in self.buffer and self.active:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try: decoded = line.decode('utf-8-sig').strip()
            except UnicodeDecodeError:
                self.failed.emit('프레임 데이터 인코딩을 확인하지 못했어요.')
                return
            self.line.emit(decoded)

    def _error_output(self):
        data = bytes(self.process.readAllStandardError())
        if data and self.active:
            # Do not silently pass event-loss warnings or expose process paths.
            self.failed.emit('수집 도구가 오류·경고를 보고했어요. 권한 또는 다른 계측 도구와의 충돌을 확인해 주세요.')

    def _process_error(self, error):
        if self.active:
            self.failed.emit('FPS 수집 도구를 실행하지 못했어요. Windows 권한·앱 파일을 확인해 주세요.')

    def _finished(self, code, status):
        if self.active:
            self.ended.emit(code)

    def stop(self):
        self.active = False
        self.buffer = b''
        if self.session and self.path:
            # PresentMon's graceful ETW cleanup addresses only our unique session.
            cleanup = QProcess()
            cleanup.start(str(self.path), ['--session_name',self.session,'--terminate_existing_session'])
            if not cleanup.waitForFinished(1000):
                cleanup.kill()
                cleanup.waitForFinished(300)
            if self.process.state() != QProcess.ProcessState.NotRunning:
                if not self.process.waitForFinished(300):
                    self.process.kill()
                    self.process.waitForFinished(300)
        if self.job is not None:
            self.job.close()
            self.job = None
        if self.session:
            try:
                session_losses(self.session,stop=True)
                self.marker.unlink(missing_ok=True)
                self.session = None
                self.cleanup_problem = ''
            except Exception:
                self.cleanup_problem = '이전 FPS 수집 세션을 정리하지 못했어요. FPS 표시를 다시 눌러 주세요.'
        return not self.pending
