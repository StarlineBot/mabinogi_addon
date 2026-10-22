"""Windows DLL의 명시적 HWND/PID 실행 식별 캡처 ABI. import/생성만으로 캡처하지 않는다."""
import ctypes as C
from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class Target:
    hwnd: int
    pid: int
    created: int  # GetProcessTimes creation FILETIME: PID/HWND 재사용과 구분

    @property
    def session(self):
        return f'{self.pid}:{self.created}'


def target_identity(hwnd: int, pid: int) -> Target:
    if sys.platform != 'win32':
        raise OSError('Windows required')
    from ctypes import wintypes as W
    k = C.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    k.GetProcessTimes.argtypes = [W.HANDLE, C.POINTER(W.FILETIME), C.POINTER(W.FILETIME),
                                  C.POINTER(W.FILETIME), C.POINTER(W.FILETIME)]
    k.GetProcessTimes.restype = W.BOOL
    k.CloseHandle.argtypes = [W.HANDLE]
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        raise C.WinError(C.get_last_error())
    try:
        values = [W.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(handle, *(C.byref(v) for v in values)):
            raise C.WinError(C.get_last_error())
        return Target(hwnd, pid, (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
    finally:
        k.CloseHandle(handle)


ERROR_NOT_SUPPORTED = 0x80070032  # 입력 상한 초과(네이티브가 입력 크기를 보고)
BB_E_GPU_SCALE = 0x80040201       # GPU 축소 실패(CPU 축소로 대체하지 않음)


def fit_output(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    """네이티브 fit_output과 같은 정수 계산. 상한 이하는 원본 그대로(확대 없음), 축소는 비율 유지·짝수."""
    if width <= max_width and height <= max_height:
        return width, height
    out_w, out_h = max_width, height * max_width // width
    if out_h > max_height:
        out_w, out_h = width * max_height // height, max_height
    return max(2, out_w & ~1), max(2, out_h & ~1)


class NativeTransition(OSError):
    """대상 비활성/크기 변경. 새 활성 epoch에서 재생성해야 한다."""


class NativeCapture:
    """한 worker에서 open/read/close. 최대 프레임·오디오 패킷 버퍼는 호출자가 명시한다."""
    def __init__(self, library: Path, *, max_frame_bytes: int, cursor: bool,
                 audio_rate: int | None = None, audio_channels: int | None = None,
                 max_audio_bytes: int | None = None, activation_timeout_ms: int | None = None,
                 audio_buffer_bytes: int | None = None,
                 max_output: tuple[int, int] | None = None, max_input: tuple[int, int] | None = None):
        if type(max_frame_bytes) is not int or max_frame_bytes <= 0 or type(cursor) is not bool:
            raise ValueError('explicit frame limit and cursor policy required')
        if (max_output is None) != (max_input is None):
            raise ValueError('explicit paired output and input bounds required')
        if max_output is not None:
            if any(type(v) is not int or v < 2 for v in (*max_output, *max_input)) or len(max_output) != 2 \
                    or len(max_input) != 2 or max_input[0] < max_output[0] or max_input[1] < max_output[1]:
                raise ValueError('invalid output/input bounds')
            if max_output[0] * max_output[1] * 4 > max_frame_bytes:
                raise ValueError('output bound exceeds frame buffer')
        self.max_output, self.max_input = max_output, max_input
        if audio_rate is not None and any(type(v) is not int or v <= 0 for v in
                (audio_rate, audio_channels, max_audio_bytes, activation_timeout_ms, audio_buffer_bytes)):
            raise ValueError('explicit audio format, capacity and timeout required')
        self.path = Path(library).absolute()
        self.limit, self.cursor = max_frame_bytes, cursor
        self.audio = (audio_rate, audio_channels, max_audio_bytes, activation_timeout_ms)
        self.audio_buffer_bytes = audio_buffer_bytes
        self._dll = None
        self._video = C.c_void_p()
        self._audio = C.c_void_p()
        self._apartment = None

    @staticmethod
    def _check(hr, operation="capture"):
        if hr & 0xffffffff in (0x80070005, 0x800704D5):
            raise NativeTransition(f'capture target changed: 0x{hr & 0xffffffff:08x}')
        if hr < 0:
            raise OSError(f'blackbox native {operation}: HRESULT 0x{hr & 0xffffffff:08x}')
        return hr

    def open(self, target: Target):
        if self._dll is not None:
            raise RuntimeError('capture already open')
        if sys.platform != 'win32':
            raise OSError('Windows required; no desktop fallback')
        # Load only the explicit absolute build artifact. No DLL search/PATH fallback.
        dll = C.CDLL(str(self.path))
        p, u32, u64, i32 = C.c_void_p, C.c_uint32, C.c_uint64, C.c_int32
        dll.bb_open_fit.argtypes = [p, u32, u64, i32, i32, i32, i32, i32, C.POINTER(p)]
        dll.bb_open_fit.restype = i32
        dll.bb_read.argtypes = [p, p, u64, C.POINTER(i32), C.POINTER(i32), C.POINTER(C.c_int64)]
        dll.bb_read.restype = i32
        dll.bb_close.argtypes = [p]
        dll.bb_close.restype = None
        dll.bb_audio_open.argtypes = [p, u32, u64, u32, u32, u32, C.POINTER(p)]
        dll.bb_audio_open.restype = i32
        dll.bb_audio_read.argtypes = [p, p, u32, C.POINTER(u32), C.POINTER(u64)]
        dll.bb_audio_read.restype = i32
        dll.bb_audio_close.argtypes = [p]
        dll.bb_audio_close.restype = None
        apartment = C.WinDLL('combase')
        apartment.RoInitialize.argtypes = [u32]
        apartment.RoInitialize.restype = i32
        apartment.RoUninitialize.argtypes = []
        apartment.RoUninitialize.restype = None
        self._check(apartment.RoInitialize(1), "COM 초기화")  # RO_INIT_MULTITHREADED
        self._apartment, self._dll = apartment, dll
        try:
            out_w, out_h = self.max_output or (0, 0)
            in_w, in_h = self.max_input or (0, 0)
            self._check(dll.bb_open_fit(target.hwnd, target.pid, target.created, self.cursor,
                                        out_w, out_h, in_w, in_h, C.byref(self._video)), "게임 영상 시작")
            self._buffer = C.create_string_buffer(self.limit)
            rate, channels, capacity, timeout = self.audio
            if rate is not None:
                self._check(dll.bb_audio_open(target.hwnd, target.pid, target.created, rate, channels,
                                             timeout, C.byref(self._audio)), "게임 오디오 시작")
                self._audio_buffer = C.create_string_buffer(capacity)
        except BaseException:
            self.close()
            raise

    def read(self):
        if not self._video.value:
            raise RuntimeError('capture not open')
        w, h, stamp = C.c_int32(), C.c_int32(), C.c_int64()
        hr = self._dll.bb_read(self._video, self._buffer, self.limit,
                               C.byref(w), C.byref(h), C.byref(stamp))
        code = hr & 0xffffffff
        if code == ERROR_NOT_SUPPORTED and self.max_input is not None and w.value > 0 and h.value > 0:
            raise OSError(f'게임 창 {w.value}×{h.value}은 블랙박스 최대 입력 '
                          f'{self.max_input[0]}×{self.max_input[1]}보다 커서 녹화를 중단했어요. 창 크기를 줄여 주세요.')
        if code == BB_E_GPU_SCALE:
            raise OSError('GPU에서 게임 영상을 '
                          f'{self.max_output[0]}×{self.max_output[1]} 안으로 줄이지 못해 녹화를 중단했어요. '
                          '그래픽 드라이버의 영상 처리 기능이 필요해요(CPU 축소로 대신하지 않아요). '
                          f'(HRESULT 0x{code:08x})' if self.max_output else
                          f'blackbox native 게임 영상 읽기: HRESULT 0x{code:08x}')
        if (hr & 0xffffffff == 0x8007007a and w.value > 0 and h.value > 0
                and w.value * h.value * 4 > self.limit):
            raise OSError(f'게임 영상 입력 {w.value}×{h.value}: '
                          f'필요 {w.value * h.value * 4} bytes, 버퍼 한도 {self.limit} bytes '
                          '(HRESULT 0x8007007a). 입력 크기 제한을 초과해 녹화를 중단했어요.')
        self._check(hr, "게임 영상 읽기")
        if hr == 1:
            return None
        size = w.value * h.value * 4
        if w.value <= 0 or h.value <= 0 or size > self.limit:
            raise OSError('invalid native frame bounds')
        return self._buffer.raw[:size], w.value, h.value, stamp.value // 10

    def read_audio(self):
        if not self._audio.value:
            raise RuntimeError('game audio not enabled')
        size, stamp = C.c_uint32(), C.c_uint64()
        hr = self._dll.bb_audio_read(self._audio, self._audio_buffer, self.audio[2],
                                     C.byref(size), C.byref(stamp))
        if hr & 0xffffffff == 0x8007007a and size.value > self.audio[2]:
            raise OSError(f'게임 오디오 패킷: 필요 {size.value} bytes, '
                          f'버퍼 한도 {self.audio[2]} bytes (HRESULT 0x8007007a)')
        self._check(hr, "게임 오디오 읽기")
        if hr == 1:
            return None
        if size.value > self.audio[2]:
            raise OSError('invalid native audio bounds')
        return self._audio_buffer.raw[:size.value], stamp.value // 10

    def close(self):
        try:
            if self._audio.value:
                self._dll.bb_audio_close(self._audio)
            if self._video.value:
                self._dll.bb_close(self._video)
        finally:
            self._audio, self._video = C.c_void_p(), C.c_void_p()
            self._dll = None
            if self._apartment is not None:
                self._apartment.RoUninitialize()
                self._apartment = None
