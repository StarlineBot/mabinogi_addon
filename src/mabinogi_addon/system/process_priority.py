"""게임 프로세스 우선순위 읽기·쓰기(최적화 명세 13.7). 읽기는 두 경로로 교차 확인한다.

2026-10-24 실사용: 작업 관리자는 게임 PID를 "높음"으로 보여 줬는데, 앱 기록(GetPriorityClass)은 64분 동안 "보통"이었다(리서치 7.7).
원인이 확인되기 전까지는 한 경로만 믿지 않는다.
- 경로 1 `GetPriorityClass`: 프로세스 핸들(조회 권한)로 묻는다. 보안 모듈이 핸들 권한을 걸러도 값을 줄 수 있는지 확인 대상.
- 경로 2 프로세스 목록(`CreateToolhelp32Snapshot`의 `pcPriClassBase`): 핸들 없이 시스템 목록에서 기본 우선순위 숫자를 읽는다.
두 값이 다르면 '확인 불가'로 다루고(적용 실패로 단정하지 않음), 원값을 app.log에 남긴다. Windows 전용 호출은 이 모듈에만 둔다.
"""
from __future__ import annotations

import logging
import sys

_log = logging.getLogger(__name__)

IDLE, BELOW_NORMAL, NORMAL, ABOVE_NORMAL, HIGH, REALTIME = 0x40, 0x4000, 0x20, 0x8000, 0x80, 0x100
NAMES = {IDLE: '낮음', BELOW_NORMAL: '보통 미만', NORMAL: '보통', ABOVE_NORMAL: '보통 초과', HIGH: '높음', REALTIME: '실시간'}
# 우선순위 클래스 → 프로세스 목록의 기본 우선순위 숫자
BASE = {IDLE: 4, BELOW_NORMAL: 6, NORMAL: 8, ABOVE_NORMAL: 10, HIGH: 13, REALTIME: 24}
CLASS_OF_BASE = {base: cls for cls, base in BASE.items()}
WRITABLE = (IDLE, BELOW_NORMAL, NORMAL, ABOVE_NORMAL, HIGH)  # 실시간은 절대 쓰지 않는다


class Unconfirmed(OSError):
    """두 경로의 우선순위가 달라(또는 둘 다 실패해) 지금 값을 확정할 수 없음. 적용 실패로 단정하지 않는다."""


def name(value) -> str:
    return NAMES.get(value, f'알 수 없음(0x{int(value or 0):X})' if isinstance(value, int) else '알 수 없음')


def judge(api_class, list_base):
    """두 경로의 결과 → (확정 클래스 또는 None, 상태). 상태: 'agree' | 'mismatch' | 'api_only' | 'list_only' | 'unknown'."""
    listed = CLASS_OF_BASE.get(list_base) if list_base is not None else None
    if api_class is not None and listed is not None:
        return (api_class, 'agree') if api_class == listed else (None, 'mismatch')
    if api_class is not None:
        return api_class, 'api_only'
    if listed is not None:
        return listed, 'list_only'
    return None, 'unknown'


def describe(reading) -> str:
    """기록·화면용 문구. 두 경로가 다르면 '확인 불가(…)'로 원값을 함께 적는다."""
    value, state = judge(reading.get('api'), reading.get('list_base'))
    if state == 'mismatch':
        listed = CLASS_OF_BASE.get(reading.get('list_base'))
        return f"확인 불가(API {name(reading.get('api'))} · 목록 {name(listed) if listed else reading.get('list_base')})"
    if value is None:
        return '확인 불가'
    return name(value)


# ---- Windows ----

def _kernel():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetPriorityClass.argtypes = [wintypes.HANDLE]
    kernel.GetPriorityClass.restype = wintypes.DWORD
    kernel.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.SetPriorityClass.restype = wintypes.BOOL
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    return kernel


def api_priority(pid, access=0x1000):
    """GetPriorityClass. access 기본은 PROCESS_QUERY_LIMITED_INFORMATION. (값 또는 None, 오류 문구)."""
    import ctypes
    kernel = _kernel()
    handle = kernel.OpenProcess(access, False, int(pid))
    if not handle:
        return None, f'OpenProcess(0x{access:X}) 실패 {ctypes.get_last_error()}'
    try:
        value = kernel.GetPriorityClass(handle)
        if not value:
            return None, f'GetPriorityClass 실패 {ctypes.get_last_error()}'
        return int(value), None
    finally:
        kernel.CloseHandle(handle)


def list_base_priorities():
    """프로세스 목록의 {PID: (이름, 기본 우선순위 숫자)}. 핸들을 열지 않는다."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD),
                    ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                    ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_wchar * 260)]

    kernel = _kernel()
    for fn in ('Process32FirstW', 'Process32NextW'):
        getattr(kernel, fn).argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        result = {}
        ok = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok and len(result) < 65536:
            result[int(entry.th32ProcessID)] = (entry.szExeFile, int(entry.pcPriClassBase))
            ok = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return result
    finally:
        kernel.CloseHandle(snapshot)


_reported = set()


def read(pid) -> dict:
    """두 경로로 읽는다: {'api', 'api_error', 'list_base'}. 다르면 한 번 app.log에 원값을 남긴다."""
    if sys.platform != 'win32':
        raise OSError('Windows에서만 사용할 수 있어요.')
    api, error = api_priority(pid)
    try:
        listed = list_base_priorities().get(int(pid))
        base = listed[1] if listed else None
    except OSError as exc:
        base, error = None, (error or '') + f' / 목록 조회 실패 {exc}'
    reading = dict(api=api, api_error=error, list_base=base)
    state = judge(api, base)[1]
    key = (int(pid), api, base, state)
    if state != 'agree' and key not in _reported and len(_reported) < 64:
        _reported.add(key)
        _log.warning('게임 우선순위 두 경로 결과: PID %s · GetPriorityClass=%s%s · 목록 기본 우선순위=%s → %s',
                     pid, hex(api) if api else None, f' ({error})' if error else '', base, state)
    return reading


def write(pid, value):
    """SetPriorityClass(PROCESS_SET_INFORMATION|PROCESS_QUERY_LIMITED_INFORMATION). 실시간은 거부."""
    import ctypes
    if value not in WRITABLE:
        raise ValueError('허용하지 않는 우선순위예요(실시간 금지).')
    kernel = _kernel()
    handle = kernel.OpenProcess(0x0200 | 0x1000, False, int(pid))
    if not handle:
        code = ctypes.get_last_error()
        if code == 87:
            raise ProcessLookupError()
        raise PermissionError(f'우선순위 변경 권한이 없어요(OpenProcess {code}).')
    try:
        if not kernel.SetPriorityClass(handle, value):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)
