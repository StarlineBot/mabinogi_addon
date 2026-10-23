"""FPS 오버레이 추가 지표(FPS 명세 8.4): CPU·GPU·게임 메모리. 읽기 전용, 1초 1회.

- CPU: **가장 바쁜 논리 코어 사용률**(Processor(*)\\% Processor Time 최댓값). 마비노기처럼 한 스레드에 몰리는
  게임은 전체 CPU%가 낮게 나온다(16스레드 중 1개 100% → 약 6%). 게임 프로세스 기준 값도 같은 이유로
  코어 수로 나누면 낮고, 코어 1개 기준으로 두면 100%를 넘을 수 있어 '병목 코어'를 바로 보여주지 못한다.
- GPU: 작업 관리자와 같은 방식. GPU Engine(*)\\Utilization Percentage를 (물리 GPU, 엔진 종류)별로 더하고
  그중 최댓값(보통 3D). 제조사와 무관하다.
- 메모리: 게임 프로세스의 전용 메모리(PrivateUsage, 커밋). 장시간 증가(누수 주장) 확인에 쓴다.

Windows 전용 조회는 `WindowsPerfReader`에만 둔다. 집계 함수는 맥/리눅스에서 테스트한다.
"""
from __future__ import annotations

import logging
import re
import sys
import threading

_log = logging.getLogger(__name__)

METRICS = ('fps', 'cpu', 'gpu', 'memory')
_ENGINE = re.compile(r'phys_(?P<phys>\d+).*?engtype_(?P<type>.+)$', re.IGNORECASE)
_LUID = re.compile(r'luid_(0x[0-9a-f]+_0x[0-9a-f]+)', re.IGNORECASE)


def busiest_core(values: dict) -> float | None:
    """Processor 인스턴스별 사용률에서 _Total을 뺀 최댓값(0~100)."""
    cores = [float(v) for name, v in values.items() if not str(name).startswith('_')]
    return max(0.0, min(100.0, max(cores))) if cores else None


def gpu_utilization(values: dict) -> float | None:
    """GPU 엔진 인스턴스(pid_..._luid_..._phys_0_eng_0_engtype_3D)별 사용률 → 작업 관리자식 GPU%."""
    totals = {}
    for name, value in values.items():
        engine = _ENGINE.search(str(name))
        if engine is None:
            continue
        luid = _LUID.search(str(name))
        key = (luid.group(1).lower() if luid else '', engine['phys'], engine['type'].lower())
        totals[key] = totals.get(key, 0.0) + float(value)
    return max(0.0, min(100.0, max(totals.values()))) if totals else None


class WindowsPerfReader:
    """PDH 카운터와 프로세스 메모리 조회. 켠 지표만 조회한다."""
    CPU = r'\Processor(*)\% Processor Time'
    GPU = r'\GPU Engine(*)\Utilization Percentage'

    def __init__(self, metrics):
        import win32pdh
        self._pdh = win32pdh
        self._query = win32pdh.OpenQuery()
        self._counters = {}
        for key, path in (('cpu', self.CPU), ('gpu', self.GPU)):
            if key in metrics:
                self._counters[key] = win32pdh.AddEnglishCounter(self._query, path)
        if self._counters:
            win32pdh.CollectQueryData(self._query)  # 비율 카운터는 두 번째 수집부터 값이 나온다

    def read(self, pid, metrics):
        pdh, result = self._pdh, {}
        if self._counters:
            pdh.CollectQueryData(self._query)
            for key, counter in self._counters.items():
                try:
                    values = pdh.GetFormattedCounterArray(counter, pdh.PDH_FMT_DOUBLE | pdh.PDH_FMT_NOCAP100)
                except Exception:
                    values = {}
                result[key] = busiest_core(values) if key == 'cpu' else gpu_utilization(values)
        if 'memory' in metrics and pid:
            result['memory'] = process_private_bytes(pid)
        return result

    def close(self):
        try:
            self._pdh.CloseQuery(self._query)
        except Exception:
            pass


def process_private_bytes(pid) -> int | None:
    import win32api
    import win32con
    import win32process
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    except Exception:
        return None
    try:
        info = win32process.GetProcessMemoryInfo(handle)
        return int(info.get('PrivateUsage') or info.get('PagefileUsage') or 0) or None
    except Exception:
        return None
    finally:
        handle.Close()


class PerfSampler:
    """작업 스레드에서 1초마다 읽고 최신 값만 남긴다. UI 스레드는 `latest`만 읽는다(OS 호출 없음)."""

    def __init__(self, reader_factory=None, interval=1.0):
        self._factory = reader_factory or (WindowsPerfReader if sys.platform == 'win32' else None)
        self._interval = interval
        self._lock = threading.Lock()
        self._metrics = frozenset()
        self._pid = None
        self._latest = {}
        self._stop = threading.Event()
        self._thread = None

    @property
    def latest(self):
        with self._lock:
            return dict(self._latest)

    def update(self, metrics, pid):
        """켠 지표(cpu/gpu/memory)와 게임 PID를 바꾼다. 지표가 없으면 스레드를 멈춘다."""
        wanted = frozenset(m for m in metrics if m in ('cpu', 'gpu', 'memory'))
        with self._lock:
            self._pid = pid
            changed = wanted != self._metrics
            self._metrics = wanted
            if changed:
                self._latest = {}
        if not wanted or self._factory is None:
            self.stop()
        elif changed or self._thread is None or not self._thread.is_alive():
            self.stop()
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(wanted, self._stop), daemon=True,
                                            name='overlay-metrics')
            self._thread.start()

    def stop(self):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _run(self, metrics, stop):
        try:
            reader = self._factory(metrics)
        except Exception as exc:
            _log.warning('오버레이 지표 조회를 시작하지 못했어요: %s', exc)
            return
        try:
            while not stop.wait(self._interval):
                with self._lock:
                    pid = self._pid
                try:
                    values = reader.read(pid, metrics)
                except Exception as exc:
                    _log.debug('오버레이 지표 조회 실패: %s', exc)
                    values = {}
                with self._lock:
                    if not stop.is_set():
                        self._latest = values
        finally:
            close = getattr(reader, 'close', None)
            if close:
                close()
