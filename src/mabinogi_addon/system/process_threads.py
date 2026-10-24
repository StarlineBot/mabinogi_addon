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
