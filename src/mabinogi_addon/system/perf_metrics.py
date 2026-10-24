"""FPS 오버레이 추가 지표(FPS 명세 8.4): CPU·GPU·게임 메모리. 읽기 전용, 1초 1회.

- CPU: **가장 바쁜 논리 코어 사용률**(Processor(*)\\% Processor Time 최댓값). 마비노기처럼 한 스레드에 몰리는
  게임은 전체 CPU%가 낮게 나온다(16스레드 중 1개 100% → 약 6%). 게임 프로세스 기준 값도 같은 이유로
  코어 수로 나누면 낮고, 코어 1개 기준으로 두면 100%를 넘을 수 있어 '병목 코어'를 바로 보여주지 못한다.
- GPU: 작업 관리자와 같은 방식. GPU Engine(*)\\Utilization Percentage를 엔진(물리 GPU·eng_N)별로 프로세스 합을 내고
  그중 최댓값(보통 3D). 제조사와 무관하다.
- 메모리: 게임 프로세스의 전용 메모리(PrivateUsage, 커밋). 장시간 증가(누수 주장) 확인에 쓴다.

Windows 전용 조회는 `WindowsPerfReader`에만 둔다. 집계 함수는 맥/리눅스에서 테스트한다.
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import time

_log = logging.getLogger(__name__)

METRICS = ('fps', 'cpu', 'gpu', 'memory')
_ENGINE = re.compile(r'phys_(?P<phys>\d+)_eng_(?P<eng>\d+)', re.IGNORECASE)
_LUID = re.compile(r'luid_(0x[0-9a-f]+_0x[0-9a-f]+)', re.IGNORECASE)


def busiest_core(values: dict) -> float | None:
    """Processor 인스턴스별 사용률에서 _Total을 뺀 최댓값(0~100)."""
    cores = [float(v) for name, v in values.items() if not str(name).startswith('_')]
    return max(0.0, min(100.0, max(cores))) if cores else None


# GetPriorityClass 값 → 작업 관리자 이름(FPS 명세 9절: 외부 도구가 바꾼 우선순위를 기록)
from .process_priority import NAMES as PRIORITY_NAMES  # noqa: E402


def describe_affinity(mask, system_mask, cores=None) -> str:
    """게임 프로세스 CPU 선호도(마스크)를 읽기 쉬운 문구로. cores: 물리 코어별 논리 CPU 번호 묶음(모르면 None).

    예: 전체 / 코어당 1개(SMT 끔으로 보임) / 논리 CPU 8개(코어 4개)."""
    mask, system_mask = int(mask or 0), int(system_mask or 0)
    chosen = [i for i in range(64) if mask & (1 << i)]
    total = [i for i in range(64) if system_mask & (1 << i)]
    if not chosen:
        return '알 수 없음'
    if total and set(chosen) >= set(total):
        return f'전체(논리 CPU {len(total)}개)'
    if cores:
        used = [core for core in cores if set(core) & set(chosen)]
        per_core = [len(set(core) & set(chosen)) for core in used]
        if len(used) == len(cores) and all(n == 1 for n in per_core) and any(len(core) > 1 for core in cores):
            return f'코어당 1개(SMT 끔으로 보임 · 논리 CPU {len(chosen)}개)'
        return f'논리 CPU {len(chosen)}개(물리 코어 {len(used)}개)'
    return f'논리 CPU {len(chosen)}개' + (f'/{len(total)}개' if total else '')


def describe_priority(value) -> str:
    return PRIORITY_NAMES.get(int(value or 0), f'알 수 없음(0x{int(value or 0):X})')


def gpu_utilization(values: dict) -> float | None:
    """GPU 엔진 인스턴스(pid_..._luid_..._phys_0_eng_0_engtype_3D)별 사용률 → 작업 관리자식 GPU%(엔진별 합의 최댓값)."""
    totals = {}
    for name, value in values.items():
        engine = _ENGINE.search(str(name))
        if engine is None:
            continue
        luid = _LUID.search(str(name))
        key = (luid.group(1).lower() if luid else '', engine['phys'], engine['eng'])
        totals[key] = totals.get(key, 0.0) + float(value)
    return max(0.0, min(100.0, max(totals.values()))) if totals else None


class WindowsPerfReader:
    """PDH 카운터와 프로세스 메모리 조회. 켠 지표만 조회한다."""
    CPU = r'\Processor(*)\% Processor Time'
    GPU = r'\GPU Engine(*)\Utilization Percentage'

    def __init__(self, metrics):
        import win32pdh
        self._cores = None
        if 'process' in metrics:
            try:  # 물리 코어별 논리 CPU 묶음(읽기 전용). 모르면 선호도를 개수로만 적는다.
                from .optimization import WindowsOptimization
                self._cores = tuple(core.cpus for core in WindowsOptimization().topology().cores)
            except Exception as exc:
                _log.info('CPU 구조를 확인하지 못해 선호도를 개수로만 기록해요: %s', exc)
        self._pdh = win32pdh
        self._query = win32pdh.OpenQuery()
        self._counters = {}
        errors = []
        # 지표별로 따로 추가한다: 한 카운터가 없는 PC에서도 나머지는 표시한다(없는 값은 '—').
        for key, path in (('cpu', self.CPU), ('gpu', self.GPU)):
            if key in metrics:
                try:
                    self._counters[key] = win32pdh.AddEnglishCounter(self._query, path)
                except Exception as exc:
                    errors.append(f'{key}: {exc}')
        if errors:
            _log.warning('오버레이 지표 카운터 일부를 쓸 수 없어요: %s', '; '.join(errors))
            if not self._counters and not {'memory', 'process'} & set(metrics):
                self.close()
                raise OSError('; '.join(errors))
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
        if 'process' in metrics and pid:
            result['process'] = process_state(pid, self._cores)
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


def process_state(pid, cores=None) -> dict | None:
    """게임 프로세스의 CPU 선호도·우선순위(읽기 전용, 조회 권한만). 바꾸지 않는다."""
    import win32api
    import win32con
    import win32process
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    except Exception:
        return None
    try:
        mask, system_mask = win32process.GetProcessAffinityMask(handle)
    except Exception:
        return None
    finally:
        handle.Close()
    # 우선순위는 두 경로(핸들 API·프로세스 목록)로 교차 확인한다. 다르면 '확인 불가(…)'(최적화 명세 13.7 조사).
    from . import process_priority
    try:
        priority = process_priority.describe(process_priority.read(pid))
    except Exception:
        priority = '확인 불가'
    return dict(affinity=describe_affinity(mask, system_mask, cores), priority=priority)


class PerfSampler:
    """작업 스레드에서 1초마다 읽고 최신 값만 남긴다. UI 스레드는 `latest`만 읽는다(OS 호출 없음)."""

    RETRY_SECONDS = 30.0  # 조회기 생성 실패 뒤 같은 지표 조합을 다시 시도하기까지

    def __init__(self, reader_factory=None, interval=1.0, clock=time.monotonic):
        self._factory = reader_factory or (WindowsPerfReader if sys.platform == 'win32' else None)
        self._interval = interval
        self._lock = threading.Lock()
        self._metrics = frozenset()
        self._pid = None
        self._latest = {}
        self._stop = threading.Event()
        self._thread = None
        self._clock = clock
        self._retry_at = {}  # 지표 조합 → 다시 시도할 시각(생성 실패 시)
        self._warned = set()  # 경고는 조합마다 처음 1회만

    @property
    def latest(self):
        with self._lock:
            return dict(self._latest)

    def update(self, metrics, pid):
        """켠 지표(cpu/gpu/memory/process)와 게임 PID를 바꾼다. 지표가 없으면 스레드를 멈춘다."""
        wanted = frozenset(m for m in metrics if m in ('cpu', 'gpu', 'memory', 'process'))
        with self._lock:
            self._pid = pid
            changed = wanted != self._metrics
            self._metrics = wanted
            if changed:
                self._latest = {}
        if not wanted or self._factory is None:
            self.stop(join=False)
        elif changed or self._thread is None or not self._thread.is_alive():
            with self._lock:
                retry = self._retry_at.get(wanted)
            if retry is not None and self._clock() < retry:
                if changed:
                    self.stop(join=False)
                return  # 최근에 생성이 실패한 조합: 매 틱 다시 만들지 않는다
            self.stop(join=False)  # UI 스레드에서 이전 조회 스레드를 기다리지 않는다(다음 대기에서 스스로 끝남)
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(wanted, self._stop), daemon=True,
                                            name='overlay-metrics')
            self._thread.start()

    def stop(self, join=True):
        self._stop.set()
        thread, self._thread = self._thread, None
        if join and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _run(self, metrics, stop):
        try:
            reader = self._factory(metrics)
        except Exception as exc:
            with self._lock:
                self._retry_at[metrics] = self._clock() + self.RETRY_SECONDS
                first = metrics not in self._warned
                self._warned.add(metrics)
            if first:
                _log.warning('오버레이 지표 조회를 시작하지 못했어요(%d초 뒤 다시 시도): %s', self.RETRY_SECONDS, exc)
            return
        with self._lock:
            self._retry_at.pop(metrics, None)
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
