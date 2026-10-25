"""게임 CPU(FPS 명세 10.4 D안): 마비노기 프로세스에서 가장 바쁜 스레드의 사용률(코어 1개 = 100%). 읽기만 한다.

`NtQuerySystemInformation(SystemProcessInformation)`의 프로세스·스레드 목록에서 스레드별 CPU 시간(커널+사용자)을 1초 간격으로
두 번 읽어 차이로 계산한다. 게임 프로세스 핸들을 열지 않으므로 보안 모듈이 핸들 권한을 걸러도 영향을 받지 않는다.
구조체 오프셋은 64비트 Windows 기준이다. 해석은 OS 없이 테스트하고(parse), 호출만 Windows에서 한다(query).
"""
from __future__ import annotations

import struct
import sys
import time

# SYSTEM_PROCESS_INFORMATION(x64): NextEntryOffset@0, NumberOfThreads@4, BasePriority@72, UniqueProcessId@80, 크기 256
# SYSTEM_THREAD_INFORMATION(x64, 80바이트): KernelTime@0, UserTime@8, ClientId.UniqueThread@48
PROCESS_SIZE, THREAD_SIZE = 256, 80


def parse(buffer: bytes, pid: int):
    """버퍼에서 pid의 {스레드 ID: CPU 시간(100ns)}와 기본 우선순위를 찾는다. 없으면 (None, None)."""
    offset = 0
    for _ in range(65536):
        if offset + PROCESS_SIZE > len(buffer):
            break
        next_offset, threads = struct.unpack_from('<II', buffer, offset)
        process_id = struct.unpack_from('<Q', buffer, offset + 80)[0]
        if process_id == pid:
            base_priority = struct.unpack_from('<i', buffer, offset + 72)[0]
            times = {}
            for index in range(min(threads, 16384)):
                at = offset + PROCESS_SIZE + index * THREAD_SIZE
                if at + THREAD_SIZE > len(buffer):
                    break
                kernel, user = struct.unpack_from('<qq', buffer, at)
                thread_id = struct.unpack_from('<Q', buffer, at + 48)[0]
                times[thread_id] = kernel + user
            return times, base_priority
        if not next_offset:
            break
        offset += next_offset
    return None, None


def busiest_percent(before, after, seconds):
    """두 시점의 스레드 CPU 시간 차이 중 최댓값 → 코어 1개 기준 %(0~100). 같은 스레드끼리만 비교한다."""
    if not before or not after or seconds <= 0:
        return None
    deltas = [after[tid] - before[tid] for tid in after.keys() & before.keys() if after[tid] >= before[tid]]
    if not deltas:
        return None
    return max(0.0, min(100.0, max(deltas) / (seconds * 10_000_000) * 100))


_last_size = 1 << 20


def query() -> bytes:
    """전체 프로세스·스레드 목록 원본(Windows 전용). 버퍼가 작으면 키운다(최대 64MiB)."""
    if sys.platform != 'win32':
        raise OSError('Windows에서만 사용할 수 있어요.')
    import ctypes
    from ctypes import wintypes
    ntdll = ctypes.WinDLL('ntdll')
    fn = ntdll.NtQuerySystemInformation
    fn.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    fn.restype = ctypes.c_long
    global _last_size
    size = _last_size  # 지난번에 맞았던 크기부터(매초 1MiB부터 다시 키우지 않게)
    while size <= 64 << 20:
        buffer = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG()
        status = fn(5, buffer, size, ctypes.byref(needed)) & 0xFFFFFFFF
        if status == 0:
            _last_size = size
            return buffer.raw[:max(needed.value, PROCESS_SIZE) if needed.value else size]
        if status != 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH 외에는 실패
            raise OSError(f'프로세스 정보 조회 실패(NTSTATUS 0x{status:08X})')
        size = max(size * 2, needed.value + (1 << 16))
    raise OSError('프로세스 정보가 너무 커요.')


class GameCpu:
    """게임 CPU를 1초 간격 표본 두 개로 계산한다. 처음 표본에서는 None(—)."""

    def __init__(self, source=query, clock=time.monotonic):
        self._source, self._clock = source, clock
        self._previous = None  # (pid, 시각, 스레드 시간)

    def read(self, pid):
        if not pid:
            self._previous = None
            return None
        times, _base = parse(self._source(), int(pid))
        now = self._clock()
        if times is None:
            self._previous = None
            return None
        previous, self._previous = self._previous, (int(pid), now, times)
        if previous is None or previous[0] != int(pid):
            return None
        return busiest_percent(previous[2], times, now - previous[1])


# ---- 블랙박스 11.4: 앱·인코더 CPU(작업 관리자 '세부 정보'와 같은 기준: 전체 논리 코어 = 100%) ----
# SYSTEM_PROCESS_INFORMATION(x64): UserTime@40, KernelTime@48, InheritedFromUniqueProcessId@88

def process_times(buffer: bytes):
    """버퍼의 모든 프로세스 → {PID: (부모 PID, CPU 시간 100ns)}."""
    table, offset = {}, 0
    for _ in range(65536):
        if offset + PROCESS_SIZE > len(buffer):
            break
        next_offset = struct.unpack_from('<I', buffer, offset)[0]
        user, kernel = struct.unpack_from('<qq', buffer, offset + 40)
        pid, parent = struct.unpack_from('<QQ', buffer, offset + 80)
        table[pid] = (parent, user + kernel)
        if not next_offset:
            break
        offset += next_offset
    return table


def tree(table, root):
    """root와 그 하위 프로세스 PID 집합(인코더 호스트 → ffmpeg 같은 손자까지)."""
    if not root or root not in table:
        return set()
    children = {}
    for pid, (parent, _) in table.items():
        if pid != parent:
            children.setdefault(parent, []).append(pid)
    found, stack = set(), [root]
    while stack and len(found) < 4096:
        pid = stack.pop()
        if pid not in found:
            found.add(pid)
            stack.extend(children.get(pid, ()))
    return found


class ProcessTreeCpu:
    """sample(앱 PID, 인코더 PID) → 직전 표본 이후 (앱 전체 %, 인코더 %). 앱 전체는 하위 프로세스(인코더 포함) 합계.
    처음 표본은 None. 표본 사이에 끝난 프로세스의 시간은 빠진다(긴 간격 요약용이라 영향이 작다)."""

    def __init__(self, source=query, clock=time.monotonic, cores=None):
        import os
        self._source, self._clock = source, clock
        self._cores = cores or os.cpu_count() or 1
        self._previous = None  # (시각, {PID: CPU 시간})

    def sample(self, app_pid, encoder_pid=None):
        table = process_times(self._source())
        now = self._clock()
        app, encoder = tree(table, app_pid), tree(table, encoder_pid)
        times = {pid: table[pid][1] for pid in app | encoder}
        previous, self._previous = self._previous, (now, times)
        if previous is None or now <= previous[0]:
            return None
        scale = 100 / ((now - previous[0]) * 10_000_000 * self._cores)

        def used(pids):
            return sum(max(0, times[pid] - previous[1].get(pid, 0)) for pid in pids) * scale
        return used(app), used(encoder)
