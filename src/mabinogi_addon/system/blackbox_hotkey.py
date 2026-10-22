"""지정 단축키만 관찰한다. 키 로그·입력 소비·입력 생성은 하지 않는다."""
import ctypes as C
from collections import deque
from threading import Event, Thread
from time import perf_counter_ns


class Chord:
    """설정 키/수식 키의 눌림 상태만 유지하며 자동 반복과 주입 입력을 제외한다."""
    MODIFIERS = {0xA4: 1, 0xA5: 1, 0x12: 1, 0xA2: 2, 0xA3: 2, 0x11: 2,
                 0xA0: 4, 0xA1: 4, 0x10: 4, 0x5B: 8, 0x5C: 8}

    def __init__(self, modifiers, vk):
        self.modifiers, self.vk = modifiers, vk
        self.down = set()

    def feed(self, vk, message, flags):
        if flags & 0x12 or message not in (0x100, 0x101, 0x104, 0x105):
            return False
        if vk != self.vk and vk not in self.MODIFIERS:
            return False
        if message in (0x101, 0x105):
            self.down.discard(vk)
            return False
        repeat = vk in self.down
        self.down.add(vk)
        mask = 0
        for key in self.down:
            mask |= self.MODIFIERS.get(key, 0)
        return vk == self.vk and not repeat and mask == self.modifiers


class WinHookAPI:
    def __init__(self):
        from ctypes import wintypes as W
        self.user = C.WinDLL('user32', use_last_error=True)
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.callback_type = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, W.WPARAM, W.LPARAM)
        class Key(C.Structure):
            _fields_ = [('vkCode', W.DWORD), ('scanCode', W.DWORD), ('flags', W.DWORD),
                        ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]
        self.Key, self.MSG = Key, W.MSG
        declarations = {
            'SetWindowsHookExW': ([C.c_int, self.callback_type, W.HINSTANCE, W.DWORD], W.HANDLE),
            'CallNextHookEx': ([W.HANDLE, C.c_int, W.WPARAM, W.LPARAM], C.c_ssize_t),
            'UnhookWindowsHookEx': ([W.HANDLE], W.BOOL),
            'PeekMessageW': ([C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL),
            'GetMessageW': ([C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT], C.c_int),
            'TranslateMessage': ([C.POINTER(W.MSG)], W.BOOL),
            'DispatchMessageW': ([C.POINTER(W.MSG)], C.c_ssize_t),
            'PostThreadMessageW': ([W.DWORD, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
            'GetForegroundWindow': ([], W.HWND),
        }
        for name, (args, result) in declarations.items():
            fn = getattr(self.user, name)
            fn.argtypes, fn.restype = args, result
        self.kernel.GetCurrentThreadId.argtypes = []
        self.kernel.GetCurrentThreadId.restype = W.DWORD
        self.kernel.GetModuleHandleW.argtypes = [W.LPCWSTR]
        self.kernel.GetModuleHandleW.restype = W.HMODULE

    def prepare(self):
        self.msg = self.MSG()
        self.user.PeekMessageW(C.byref(self.msg), None, 0, 0, 0)
        return self.kernel.GetCurrentThreadId()

    def install(self, observe):
        self.callback_error = None
        def callback(code, message, address):
            try:
                if code == 0:
                    key = C.cast(address, C.POINTER(self.Key)).contents
                    observe(key.vkCode, message, key.flags)
            except Exception as exc:
                # No exception may cross the OS callback or suppress input.
                self.callback_error = exc
            return self.user.CallNextHookEx(None, code, message, address)
        self.callback = self.callback_type(callback)
        handle = self.user.SetWindowsHookExW(13, self.callback, self.kernel.GetModuleHandleW(None), 0)
        if not handle:
            raise OSError(f'단축키 관찰 시작 실패 (SetWindowsHookExW): {C.get_last_error()}')
        return handle

    def foreground(self):
        return int(self.user.GetForegroundWindow() or 0)

    def pump(self):
        result = self.user.GetMessageW(C.byref(self.msg), None, 0, 0)
        if self.callback_error is not None:
            raise OSError(f'단축키 관찰 처리 실패: {self.callback_error}')
        if result == -1:
            raise OSError(f'단축키 메시지 수신 실패 (GetMessageW): {C.get_last_error()}')
        if result:
            self.user.TranslateMessage(C.byref(self.msg))
            self.user.DispatchMessageW(C.byref(self.msg))
        return bool(result)

    def quit(self, thread_id):
        if not self.user.PostThreadMessageW(thread_id, 0x12, 0, 0):
            raise OSError(f'단축키 관찰 종료 요청 실패 (PostThreadMessageW): {C.get_last_error()}')

    def uninstall(self, handle):
        if not self.user.UnhookWindowsHookEx(handle):
            raise OSError(f'단축키 관찰 해제 실패 (UnhookWindowsHookEx): {C.get_last_error()}')


class HotkeyObserver:
    def __init__(self, modifiers, vk, *, api_factory=WinHookAPI):
        self.chord = Chord(modifiers, vk)
        self.epoch = self.chord_epoch = 0
        self.pending = deque(maxlen=2)
        self.overflow = None
        self.error = None
        self.cleanup_error = None
        self.ready, self.stopping = Event(), Event()
        self.api_factory = api_factory
        self.thread = Thread(target=self._run, name='blackbox-hotkey', daemon=True)
        self.thread.start()
        if not self.ready.wait(5):
            self.stopping.set()
            raise OSError('단축키 관찰 시작 응답 시간 초과')
        if self.error:
            self.thread.join(5)
            raise self.error

    def _observe(self, vk, message, flags):
        # Only this hook thread mutates Chord. GUI invalidation advances an epoch
        # instead of sharing a lock with the latency-sensitive OS callback.
        epoch = self.epoch
        if self.chord_epoch != epoch:
            self.chord.down.clear()
            self.chord_epoch = epoch
        if self.chord.feed(vk, message, flags) and not self.stopping.is_set():
            timestamp = perf_counter_ns() // 1000
            hwnd = self.api.foreground()
            if hwnd:
                if len(self.pending) == self.pending.maxlen:
                    self.overflow = epoch
                else:
                    self.pending.append((epoch, timestamp, hwnd))

    def _run(self):
        handle = None
        try:
            self.api = self.api_factory()
            self.thread_id = self.api.prepare()
            if self.stopping.is_set():
                return
            handle = self.api.install(self._observe)
            self.ready.set()
            while not self.stopping.is_set():
                if not self.api.pump():
                    if not self.stopping.is_set():
                        raise OSError('단축키 관찰 메시지 루프가 예기치 않게 종료됐어요.')
                    break
        except Exception as exc:
            self.error = exc
        finally:
            if handle:
                try:
                    self.api.uninstall(handle)
                except Exception as exc:
                    self.cleanup_error = exc
                    self.error = exc
            self.ready.set()

    def consume(self):
        callback_error = getattr(self.api, 'callback_error', None)
        if callback_error is not None:
            raise OSError(f'단축키 관찰 처리 실패: {callback_error}')
        if self.error:
            raise self.error
        while self.pending:
            epoch, timestamp, hwnd = self.pending.popleft()
            if epoch == self.epoch:
                return timestamp, hwnd
        if self.overflow == self.epoch:
            self.overflow = None
            raise OSError('단축키 요청 대기 한도 초과: 일부 요청을 접수하지 못했어요.')
        return None

    def discard(self):
        # A callback already in flight can still append an old-epoch event;
        # consume rejects it even if the append occurs after clear().
        self.epoch += 1
        self.pending.clear()
        self.overflow = None

    def close(self):
        self.stopping.set()
        self.discard()
        if self.thread.is_alive() and self.ready.is_set():
            self.api.quit(self.thread_id)
        self.thread.join(5)
        if self.thread.is_alive():
            raise OSError('단축키 관찰 스레드 종료 시간 초과')
        if self.cleanup_error:
            raise self.cleanup_error
