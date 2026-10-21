"""Windows alpha boundaries: process identity, topology and selected network settings.

No operation elevates, installs a service, kills another app or changes game data.
"""
from contextlib import contextmanager
from pathlib import PureWindowsPath
import base64
import ctypes
from ctypes import wintypes
import json
import os
import re
import struct
import subprocess
import sys
import uuid
from functools import lru_cache

from ..optimization.session import Core, Topology

AUTOTUNING = {'disabled','highlyrestricted','restricted','normal','experimental'}
EXCLUDED = re.compile(r'(?:system|idle|registry|smss|csrss|wininit|winlogon|services|lsass|svchost|'
    r'fontdrvhost|dwm|sihost|taskhostw|shellexperiencehost|startmenuexperiencehost|'
    r'msmpeng|mpsigstub|securityhealthservice|securityhealthsystray|nissrv|'
    r'audiodg|spoolsv|searchindexer|searchhost|ctfmon|conhost|wmiprvse|dllhost|'
    r'mabinogi-addon|presentmon|powershell|pwsh|processgovernor|processlasso)(?:\.exe)?$', re.I)
PROTECTED = re.compile(r'anti.?cheat|blackcipher|nexon|ngs|xigncode|gameguard|easyanticheat|'
                       r'battleye|vgc|vgtray|defender|avast|avp|antivirus|faceit', re.I)


class Entry(ctypes.Structure):
    _fields_ = [('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),
        ('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),
        ('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
        ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),
        ('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]

class WindowsOptimization:
    def __init__(self):
        self.restarts = set()
        self._game_window = None

    @staticmethod
    def _windows():
        if sys.platform != 'win32':
            raise OSError('Windows에서만 사용할 수 있어요.')

    @staticmethod
    def validate(kind, target, value):
        if kind == 'cpu':
            if (not isinstance(target,dict) or set(target) != {'pid','birth'} or
                    type(target['pid']) is not int or not 0 < target['pid'] < 2**32 or
                    not isinstance(target['birth'], str) or not target['birth'].isdecimal()):
                raise ValueError('프로세스 식별값을 확인해 주세요.')
            if type(value) is not int or not 0 < value < 2**64: raise ValueError('잘못된 CPU 집합')
        elif kind == 'autotuning':
            if target != 'global' or value not in AUTOTUNING: raise ValueError('잘못된 TCP 값')
        elif kind in ('ack','nodelay','rss'):
            uuid.UUID(target)
            if kind != 'rss':
                if value is not None and (type(value) is not int or not 0 <= value < 2**32):
                    raise ValueError('레지스트리 값 형식을 지원하지 않아요.')
            elif (not isinstance(value,dict) or set(value) != {'Enabled','BaseProcessorGroup','BaseProcessorNumber',
                    'MaxProcessorGroup','MaxProcessorNumber','MaxProcessors','NumberOfReceiveQueues','Profile'} or
                    type(value['Enabled']) is not bool or value['Profile'] not in
                    ('Closest','ClosestStatic','NUMA','NUMAStatic','Conservative') or
                    any(type(value[k]) is not int or not 0 <= value[k] <= 65535 for k in value if k not in ('Enabled','Profile'))):
                raise ValueError('RSS 설정 형식을 지원하지 않아요.')
        else:
            raise ValueError('지원하지 않는 변경 항목')

    @staticmethod
    @lru_cache(maxsize=1)
    def _kernel():
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)]*4
        kernel.GetProcessAffinityMask.argtypes = [wintypes.HANDLE,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]
        kernel.SetProcessAffinityMask.argtypes = [wintypes.HANDLE,ctypes.c_size_t]
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
        return kernel

    @contextmanager
    def _process(self, target, *, write=False, affinity=False):
        self._windows()
        kernel = self._kernel()
        handle = kernel.OpenProcess((0x400 if affinity else 0x1000) | (0x200 if write else 0), False, target['pid'])
        if not handle:
            if ctypes.get_last_error() == 87: raise ProcessLookupError()
            raise PermissionError('프로세스 권한을 확인해 주세요.')
        try:
            birth, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle,ctypes.byref(birth),ctypes.byref(exit_time),ctypes.byref(kernel_time),ctypes.byref(user_time)):
                raise ctypes.WinError(ctypes.get_last_error())
            if exit_time.dwHighDateTime or exit_time.dwLowDateTime:
                raise ProcessLookupError()
            identity = str((birth.dwHighDateTime << 32) | birth.dwLowDateTime)
            if target.get('birth') is not None and identity != target['birth']: raise ProcessLookupError()
            if write and self._protected(kernel,handle):
                raise PermissionError('보호 프로세스는 CPU 변경 대상에서 제외해요.')
            yield kernel, handle, identity
        finally:
            kernel.CloseHandle(handle)

    @staticmethod
    def _protected(kernel, handle):
        level = wintypes.DWORD()
        fn = kernel.GetProcessInformation
        fn.argtypes = [wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD]
        # ProcessProtectionLevelInfo (7), PROTECTION_LEVEL_NONE (0xfffffffe).
        if not fn(handle,7,ctypes.byref(level),ctypes.sizeof(level)):
            raise PermissionError('프로세스 보호 상태를 확인하지 못했어요.')
        return level.value != 0xfffffffe

    def governor_running(self):
        self._windows()
        kernel=self._kernel()
        kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
        snapshot=kernel.CreateToolhelp32Snapshot(2,0)
        if snapshot == ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry=Entry();entry.dwSize=ctypes.sizeof(entry)
            for name in ('Process32FirstW','Process32NextW'):
                getattr(kernel,name).argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
            found=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
            if not found: raise ctypes.WinError(ctypes.get_last_error())
            for _ in range(65536):
                if entry.szExeFile.lower()=='processgovernor.exe': return True
                if not kernel.Process32NextW(snapshot,ctypes.byref(entry)):
                    if ctypes.get_last_error()!=18: raise ctypes.WinError(ctypes.get_last_error())
                    return False
            raise OSError('프로세스 목록 한도를 초과했어요.')
        finally: kernel.CloseHandle(snapshot)

    def process_info(self, pid):
        import win32api
        import win32security
        import win32process
        with self._process({'pid':pid}) as (kernel,handle,birth):
            path = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(path))
            if not kernel.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(length)): raise PermissionError()
            token = win32security.OpenProcessToken(int(handle), 8)
            try:
                sid = win32security.GetTokenInformation(token,win32security.TokenUser)[0]
            finally: token.Close()
            own_token = win32security.OpenProcessToken(win32api.GetCurrentProcess(),8)
            try: own_sid = win32security.GetTokenInformation(own_token,win32security.TokenUser)[0]
            finally: own_token.Close()
            return dict(target={'pid':int(pid),'birth':birth}, name=PureWindowsPath(path.value).name,
                        path=path.value, same_user=sid == own_sid, protected=self._protected(kernel,handle),
                        same_session=self._session_id(pid) == self._session_id(os.getpid()))

    @staticmethod
    def _session_id(pid):
        value = wintypes.DWORD()
        fn = WindowsOptimization._kernel().ProcessIdToSessionId
        fn.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        if not fn(pid,ctypes.byref(value)): raise ctypes.WinError(ctypes.get_last_error())
        return value.value

    def processes(self):
        self._windows()
        import win32process
        out = []
        for pid in win32process.EnumProcesses()[:4096]:
            if not pid: continue
            try: out.append(self.process_info(pid))
            except (OSError, PermissionError, ProcessLookupError): pass
            except Exception: pass  # Protected/system processes are never mutation candidates.
        return out

    @staticmethod
    def background_candidate(info, game):
        name = info['name']
        path = PureWindowsPath(info['path'])
        windows = PureWindowsPath(os.environ.get('WINDIR', 'C:/Windows'))
        return (info['target'] != game and info['target']['pid'] != os.getpid()
                and info['same_user'] and info['same_session'] and not info.get('protected',True)
                and not path.is_relative_to(windows) and not EXCLUDED.fullmatch(name)
                and not PROTECTED.search(str(path))
                and name.lower() != PureWindowsPath(sys.executable).name.lower())

    def game(self):
        from .window_capture import registered_game_target
        target = self._game_window = registered_game_target(self._game_window)
        if target is None: return None
        with self._process({'pid':target[1]}) as (_,handle,birth):
            return {'pid':target[1],'birth':birth}

    def alive(self, target):
        try:
            with self._process(target): return True
        except ProcessLookupError: return False
        # Access failures are not proof that the game ended.

    def topology(self):
        self._windows()
        import winreg
        kernel = self._kernel()
        size = wintypes.DWORD()
        fn = kernel.GetLogicalProcessorInformationEx
        fn.argtypes = [wintypes.DWORD,wintypes.LPVOID,ctypes.POINTER(wintypes.DWORD)]
        fn(0,None,ctypes.byref(size))
        if not 0 < size.value <= 1024*1024: raise ValueError('CPU 구조 크기를 확인하지 못했어요.')
        buffer = ctypes.create_string_buffer(size.value)
        if not fn(0,buffer,ctypes.byref(size)): raise ctypes.WinError(ctypes.get_last_error())
        data, offset, records = buffer.raw[:size.value], 0, []
        while offset < len(data):
            relation, length = struct.unpack_from('<II',data,offset)
            if relation != 0 or length < 48 or offset+length > len(data): raise ValueError('CPU 구조 형식 미지원')
            groups = struct.unpack_from('<H',data,offset+30)[0]
            mask, group = struct.unpack_from('<QH',data,offset+32)
            if groups != 1 or group != 0: raise ValueError('다중 프로세서 그룹은 아직 지원하지 않아요.')
            records.append((data[offset+9],tuple(i for i in range(64) if mask & (1 << i))))
            offset += length
        classes = {r[0] for r in records}
        if len(classes) > 2: raise ValueError('이 CPU의 성능 코어 구분을 확인하지 못했어요.')
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            name = winreg.QueryValueEx(key,'ProcessorNameString')[0]
        return Topology(name, tuple(Core(i,cpus,eff == max(classes)) for i,(eff,cpus) in enumerate(records)))

    def _ps(self, script):
        self._windows()
        executable = os.path.join(os.environ.get('SystemRoot','C:\\Windows'),'System32','WindowsPowerShell','v1.0','powershell.exe')
        script = "$ErrorActionPreference='Stop'; " + script
        encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
        result = subprocess.run([executable,'-NoProfile','-NonInteractive','-EncodedCommand',encoded],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,creationflags=0x08000000)
        if result.returncode or len(result.stdout)>1024*1024: raise OSError('Windows 설정 명령에 실패했어요. 권한·장치 상태를 확인해 주세요.')
        text = result.stdout.decode('utf-8-sig',errors='replace').strip()
        return json.loads(text) if text else None

    def adapters(self):
        result = self._ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; @(Get-NetAdapter -Physical | Where-Object {$_.Status -eq 'Up'} | Select-Object Name,InterfaceGuid,ifIndex) | ConvertTo-Json -Compress")
        rows = result if isinstance(result,list) else [result] if result else []
        if len(rows)>64: raise ValueError('네트워크 어댑터 목록 한도를 초과했어요.')
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('Name'),str) or not row['Name']:
                raise ValueError('네트워크 어댑터 정보를 확인하지 못했어요.')
            row['InterfaceGuid']=str(uuid.UUID(row.get('InterfaceGuid')))
        return rows

    def _adapter(self, guid):
        guid = str(uuid.UUID(guid))
        return "$a=Get-NetAdapter -Physical | Where-Object {[string]$_.InterfaceGuid -eq '"+guid+"'}; if(@($a).Count -ne 1){throw 'adapter unavailable'}; "

    def _tcp_level(self):
        # Netsh's values are invariant; refuse unknown/localized field names rather than guessing.
        return self._ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; $s=(& netsh interface tcp show global | Where-Object {$_ -match 'Receive Window Auto-Tuning Level|수신 창 자동 조정 수준'}); if(@($s).Count -ne 1){throw 'unsupported locale'}; (($s -split ':',2)[1].Trim().ToLowerInvariant()) | ConvertTo-Json -Compress")

    def read(self, kind, target):
        self._windows()
        if kind == 'cpu':
            with self._process(target,affinity=True) as (kernel,handle,_):
                value, system = ctypes.c_size_t(),ctypes.c_size_t()
                if not kernel.GetProcessAffinityMask(handle,ctypes.byref(value),ctypes.byref(system)): raise ctypes.WinError(ctypes.get_last_error())
                return int(value.value)
        if kind == 'autotuning': return self._tcp_level()
        if kind in ('ack','nodelay'):
            import winreg
            self._ps(self._adapter(target))
            key = r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{'+str(uuid.UUID(target)).upper()+'}'
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,key) as handle:
                try: value,typ = winreg.QueryValueEx(handle,'TcpAckFrequency' if kind=='ack' else 'TCPNoDelay')
                except FileNotFoundError: return None
                if typ != winreg.REG_DWORD: raise ValueError('이 레지스트리 값 형식은 지원하지 않아요.')
                return value
        return self._ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "+self._adapter(target)+"Get-NetAdapterRss -Name $a.Name | Select-Object Enabled,BaseProcessorGroup,BaseProcessorNumber,MaxProcessorGroup,MaxProcessorNumber,MaxProcessors,NumberOfReceiveQueues,@{N='Profile';E={[string]$_.Profile}} | ConvertTo-Json -Compress")

    def guarded_write(self, kind, target, value, guard):
        self.write(kind,target,value,guard=guard)

    def write(self, kind, target, value, *, guard=None):
        self._windows()
        self.validate(kind,target,value)
        if kind == 'cpu':
            with self._process(target,write=True) as (kernel,handle,_):
                if not kernel.SetProcessAffinityMask(handle,value): raise ctypes.WinError(ctypes.get_last_error())
            return
        if kind == 'autotuning':
            if guard is not None: guard()
            self._ps("& netsh interface tcp set global autotuninglevel="+value+" | Out-Null; if($LASTEXITCODE -ne 0){throw 'netsh failed'}")
            return
        if kind in ('ack','nodelay'):
            import winreg
            self._ps(self._adapter(target))
            key = r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{'+str(uuid.UUID(target)).upper()+'}'
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,key,0,winreg.KEY_SET_VALUE) as handle:
                name = 'TcpAckFrequency' if kind=='ack' else 'TCPNoDelay'
                if guard is not None: guard()
                if value is None:
                    try: winreg.DeleteValue(handle,name)
                    except FileNotFoundError: pass
                else: winreg.SetValueEx(handle,name,0,winreg.REG_DWORD,value)
        else:
            fields = ' '.join('-'+key+' '+str(value[key]) for key in value if key!='Enabled')
            if guard is not None: guard()
            self._ps(self._adapter(target)+"Set-NetAdapterRss -Name $a.Name "+fields+" -NoRestart; "+
                     ('Enable' if value['Enabled'] else 'Disable')+"-NetAdapterRss -Name $a.Name -NoRestart -Confirm:$false")
        self.restarts.add(str(uuid.UUID(target)))

    def guarded_restart(self, target, guard):
        self.restart_network(target,guard=guard)

    def restart_network(self, target, *, guard=None):
        script=self._adapter(target)+"Restart-NetAdapter -Name $a.Name -Confirm:$false"
        if guard is not None: guard()
        self._ps(script)
        self.restarts.discard(str(uuid.UUID(target)))

    def flush_network(self):
        for target in tuple(self.restarts):
            self._ps(self._adapter(target)+"Restart-NetAdapter -Name $a.Name -Confirm:$false")
            self.restarts.remove(target)

    def rss_plan(self, target, cpus):
        old = self.read('rss',target)
        self.validate('rss',target,old)
        if not cpus or cpus != list(range(min(cpus),max(cpus)+1)) or len(cpus)>old['MaxProcessors']:
            raise ValueError('이 장치는 선택한 백그라운드 CPU만 표현할 수 없어요.')
        return dict(old,Enabled=True,BaseProcessorGroup=0,MaxProcessorGroup=0,
                    BaseProcessorNumber=min(cpus),MaxProcessorNumber=max(cpus),MaxProcessors=len(cpus),Profile='ClosestStatic')
