"""Windows alpha boundaries: process identity, topology and selected network settings.

No operation elevates, installs a service, kills another app or changes game data.
"""
from contextlib import contextmanager
from pathlib import PureWindowsPath
import base64
import ctypes
import hashlib
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

class WindowsCommandError(OSError):
    """Bounded, non-identifying diagnostics; never expose shell text or scripts."""
    def __init__(self, operation, code, stderr=b'', category=None):
        raw=stderr[:65536]
        encoding='utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-16le' if b'\x00' in raw[:80] else 'utf-8-sig'
        text=raw.decode(encoding,errors='replace')
        categories={'PermissionDenied':'권한 부족', 'ObjectNotFound':'장치·명령 없음',
                    'NotImplemented':'미지원', 'InvalidOperation':'지원 상태 확인 필요',
                    'AdapterMissing':'선택 장치 없음', 'AdapterAmbiguous':'장치 식별 중복', 'CommandMissing':'명령·모듈 없음', 'InvalidArgument':'잘못된 인자',
                    'InvalidData':'잘못된 응답', 'ResourceUnavailable':'장치 사용 불가',
                    'ReadError':'읽기 실패', 'WriteError':'쓰기 실패', 'DeviceError':'장치 오류',
                    'NotEnabled':'비활성 상태', 'ParserError':'명령 구문 오류'}
        if category is None:
            if 'MABI_OPT_ADAPTER:missing' in text: category='AdapterMissing'
            elif 'MABI_OPT_ADAPTER:ambiguous' in text: category='AdapterAmbiguous'
            elif 'MABI_OPT_COMMAND:missing' in text: category='CommandMissing'
        if category is None:
            for key in categories:
                if key in text: category=key; break
        if category is None:
            lower=text.lower()
            if 'access is denied' in lower or 'unauthorizedaccess' in lower: category='PermissionDenied'
            elif 'adapter unavailable' in lower: category='ObjectNotFound'
            elif 'not supported' in lower: category='NotImplemented'
        self.operation,self.category,self.returncode=operation,category or 'CommandFailed',code
        native=re.search(r'MABI_OPT_NATIVE:(-?\d{1,10})',text)
        self.nativecode=int(native.group(1)) if native else None
        hresult=re.search(r'MABI_OPT_HRESULT:(-?\d{1,10})',text)
        self.hresult=int(hresult.group(1)) if hresult else None
        self.evidence=hashlib.sha256(raw).hexdigest()[:12] if raw else 'empty'
        label=categories.get(self.category,{'Timeout':'시간 초과','OutputInvalid':'응답 형식 오류',
            'LaunchFailed':'명령 실행 실패'}.get(self.category,'명령 실패'))
        super().__init__(code,f'{operation}: {label} (분류 {self.category}, 반환 코드 {code}, 네이티브 {self.nativecode}, HRESULT {self.hresult}, 진단 {self.evidence})')


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
        kernel.GetActiveProcessorGroupCount.argtypes = []
        kernel.GetActiveProcessorGroupCount.restype = wintypes.WORD
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

    def _ps(self, script, operation='Windows 명령'):
        self._windows()
        executable = os.path.join(os.environ.get('SystemRoot','C:\\Windows'),'System32','WindowsPowerShell','v1.0','powershell.exe')
        # Emit only an invariant error category; Python never publishes raw shell output.
        script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                  "$OutputEncoding=[Text.Encoding]::UTF8; try { "+script+
                  " } catch { if($_.Exception -is [System.Management.Automation.CommandNotFoundException]){[Console]::Error.WriteLine('MABI_OPT_COMMAND:missing')}; [Console]::Error.WriteLine('MABI_OPT_ERROR:'+ [string]$_.CategoryInfo.Category); [Console]::Error.WriteLine('MABI_OPT_HRESULT:'+ $_.Exception.HResult); exit 1 }")
        encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
        try:
            result = subprocess.run([executable,'-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,creationflags=0x08000000)
        except subprocess.TimeoutExpired as exc:
            raise WindowsCommandError(operation,-1,category='Timeout') from None
        except OSError as exc:
            raise WindowsCommandError(operation,exc.errno or -1,category='LaunchFailed') from None
        if result.returncode:
            raise WindowsCommandError(operation,result.returncode,result.stderr)
        if len(result.stdout)>1024*1024:
            raise WindowsCommandError(operation,0,category='OutputInvalid')
        try:
            text = result.stdout.decode('utf-8-sig').strip()
            return json.loads(text) if text else None
        except (UnicodeError,ValueError):
            raise WindowsCommandError(operation,0,category='OutputInvalid') from None

    def adapters(self):
        result = self._ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; @(Get-NetAdapter -Physical | Where-Object {$_.Status -eq 'Up'} | Select-Object Name,InterfaceGuid,ifIndex) | ConvertTo-Json -Compress", '환경 조회/어댑터')
        rows = result if isinstance(result,list) else [result] if result else []
        if len(rows)>64: raise ValueError('네트워크 어댑터 목록 한도를 초과했어요.')
        seen=set()
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('Name'),str) or not row['Name']:
                raise ValueError('네트워크 어댑터 정보를 확인하지 못했어요.')
            row['InterfaceGuid']=str(uuid.UUID(row.get('InterfaceGuid')))
            if row['InterfaceGuid'] in seen: raise ValueError('네트워크 장치 식별자가 중복됐어요.')
            seen.add(row['InterfaceGuid'])
        return rows

    def _adapter(self, guid):
        guid = str(uuid.UUID(guid))
        return ("$wanted=[guid]'"+guid+"'; $a=@(Get-NetAdapter -Physical | Where-Object {"
                "$parsed=[guid]::Empty; [guid]::TryParse([string]$_.InterfaceGuid,[ref]$parsed) -and $parsed -eq $wanted}); "
                "if($a.Count -ne 1){[Console]::Error.WriteLine('MABI_OPT_ADAPTER:'+$(if($a.Count -eq 0){'missing'}else{'ambiguous'})); Write-Error -Message 'adapter unavailable' -Category ObjectNotFound -ErrorAction Stop}; $a=$a[0]; ")

    def _tcp_level(self):
        # Netsh's values are invariant; refuse unknown/localized field names rather than guessing.
        return self._ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; $s=(& netsh interface tcp show global | Where-Object {$_ -match 'Receive Window Auto-Tuning Level|수신 창 자동 조정 수준'}); if(@($s).Count -ne 1){Write-Error -Message 'unsupported locale' -Category NotImplemented -ErrorAction Stop}; (($s -split ':',2)[1].Trim().ToLowerInvariant()) | ConvertTo-Json -Compress", '조회/autotuning')

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
            self._ps(self._adapter(target), '장치 확인/'+kind)
            key = r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{'+str(uuid.UUID(target)).upper()+'}'
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,key) as handle:
                    try: value,typ = winreg.QueryValueEx(handle,'TcpAckFrequency' if kind=='ack' else 'TCPNoDelay')
                    except FileNotFoundError: return None
                    if typ != winreg.REG_DWORD: raise ValueError('이 레지스트리 값 형식은 지원하지 않아요.')
                    return value
            except OSError as exc:
                raise WindowsCommandError('조회/'+kind,getattr(exc,'winerror',None) or exc.errno or -1,
                    category='PermissionDenied' if isinstance(exc,PermissionError) else 'ObjectNotFound' if isinstance(exc,FileNotFoundError) else 'CommandFailed') from None
        value = self._ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "+self._adapter(target)+"Get-NetAdapterRss -Name $a.Name | Select-Object Enabled,BaseProcessorGroup,BaseProcessorNumber,MaxProcessorGroup,MaxProcessorNumber,MaxProcessors,NumberOfReceiveQueues,@{N='Profile';E={[string]$_.Profile}} | ConvertTo-Json -Compress", '조회/rss')
        groups = ('BaseProcessorGroup','MaxProcessorGroup')
        if isinstance(value,dict) and any(key in value and value[key] is None for key in groups):
            # A single active group makes an unreported group unambiguously zero.
            if self._kernel().GetActiveProcessorGroupCount() != 1:
                raise ValueError('RSS 프로세서 그룹을 확인하지 못했어요.')
            value = dict(value)
            for key in groups:
                if key in value and value[key] is None: value[key] = 0
        self.validate('rss',target,value)
        return value

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
            self._ps("& netsh interface tcp set global autotuninglevel="+value+" | Out-Null; if($LASTEXITCODE -ne 0){[Console]::Error.WriteLine('MABI_OPT_NATIVE:'+$LASTEXITCODE); throw 'netsh failed'}", '적용·원복/autotuning')
            return
        if kind in ('ack','nodelay'):
            import winreg
            self._ps(self._adapter(target), '장치 확인/'+kind)
            key = r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{'+str(uuid.UUID(target)).upper()+'}'
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,key,0,winreg.KEY_SET_VALUE) as handle:
                    name = 'TcpAckFrequency' if kind=='ack' else 'TCPNoDelay'
                    if guard is not None: guard()
                    if value is None:
                        try: winreg.DeleteValue(handle,name)
                        except FileNotFoundError: pass
                    else: winreg.SetValueEx(handle,name,0,winreg.REG_DWORD,value)
            except OSError as exc:
                raise WindowsCommandError('적용·원복/'+kind,getattr(exc,'winerror',None) or exc.errno or -1,
                    category='PermissionDenied' if isinstance(exc,PermissionError) else 'ObjectNotFound' if isinstance(exc,FileNotFoundError) else 'CommandFailed') from None
        else:
            fields = ' '.join('-'+key+' '+str(value[key]) for key in value if key!='Enabled')
            if guard is not None: guard()
            self._ps(self._adapter(target)+"Set-NetAdapterRss -Name $a.Name "+fields+" -NoRestart; "+
                     ('Enable' if value['Enabled'] else 'Disable')+"-NetAdapterRss -Name $a.Name -NoRestart -Confirm:$false", '적용·원복/rss')
        self.restarts.add(str(uuid.UUID(target)))

    def guarded_restart(self, target, guard):
        self.restart_network(target,guard=guard)

    def restart_network(self, target, *, guard=None):
        script=self._adapter(target)+"Restart-NetAdapter -Name $a.Name -Confirm:$false"
        if guard is not None: guard()
        self._ps(script, '재연결/어댑터')
        self.restarts.discard(str(uuid.UUID(target)))

    def flush_network(self):
        for target in tuple(self.restarts):
            self.restart_network(target)

    def rss_plan(self, target, cores):
        """백그라운드 물리 코어에 RSS를 둔다. cores: 코어별 논리 CPU 묶음(정수면 코어당 1개).

        Windows RSS는 SMT 형제를 쓰지 않고 물리 코어당 대표 논리 CPU 하나만 쓴다. 형제까지 넣은
        범위(예: 14~15/2개)를 쓰면 어댑터 재시작 때 장치가 14/1로 줄여, 앱 기록(적용값)과도
        원본과도 달라져 원복이 보류됐다. 처음부터 대표 CPU 기준 값을 써 정규화와 일치시킨다."""
        old = self.read('rss',target)
        self.validate('rss',target,old)
        groups = [tuple(sorted(c)) if isinstance(c,(tuple,list)) else (c,) for c in (cores or ())]
        cpus = sorted(n for g in groups for n in g)
        if (not groups or any(not g or any(type(n) is not int for n in g) for g in groups)
                or cpus != list(range(min(cpus),max(cpus)+1)) or len(groups)>old['MaxProcessors']):
            raise ValueError('이 장치는 선택한 백그라운드 CPU만 표현할 수 없어요.')
        leads = sorted(g[0] for g in groups)
        return dict(old,Enabled=True,BaseProcessorGroup=0,MaxProcessorGroup=0,
                    BaseProcessorNumber=leads[0],MaxProcessorNumber=leads[-1],MaxProcessors=len(groups),Profile='ClosestStatic')
