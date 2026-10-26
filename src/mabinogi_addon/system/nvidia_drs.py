"""NVIDIA 드라이버 프로필의 '최대 프레임 속도'(그래픽 효율 최적화, 최적화 명세 13.6). Windows 전용 경계.

NVIDIA 공식 드라이버 설정 API(NVAPI DRS)로 게임 실행 파일 프로필의 최대 프레임 속도(FRL_FPS)를 읽고 쓴다.
- 값: None = 프로필에 설정 없음(드라이버 기본 = 제한 없음), 0 = 끔, 그 밖의 정수 = FPS 상한.
- 게임 프로필이 없으면 앱 이름의 프로필을 만들어 실행 파일을 넣는다(원복 때 앱이 만든 프로필이면 통째로 지운다).
- 수직 동기화 등 다른 설정은 건드리지 않는다.

`FrameLimit`은 DRS 기본 동작(`_Nvapi`)만 받아 쓰는 논리 층이라 맥·리눅스에서 가짜 API로 테스트한다.
"""
from __future__ import annotations

import sys

FRL_FPS_ID = 0x10835002  # NvApiDriverSettings.h: Frame Rate Limiter(최대 프레임 속도)
OWN_PROFILE = 'Starline Mabinogi Addon'  # 게임 프로필이 없을 때 앱이 만드는 프로필 이름

NVAPI_OK = 0
NVAPI_SETTING_NOT_FOUND = -160
NVAPI_PROFILE_NOT_FOUND = -163
NVAPI_EXECUTABLE_NOT_FOUND = -166
NVAPI_INCOMPATIBLE_STRUCT_VERSION = -9


class GamePathUnknown(LookupError):
    """게임 실행 파일 전체 경로를 아직 모른다(한 번도 실행 중인 게임을 보지 못함). 게임을 보면 다시 시도한다."""


class NvapiError(OSError):
    def __init__(self, operation, status, message=''):
        self.status = status
        super().__init__(f'{operation}: NVAPI {status}' + (f' ({message})' if message else ''))


class FrameLimit:
    """게임 실행 파일 프로필의 최대 프레임 속도 읽기·쓰기(논리). api는 `_Nvapi`와 같은 메서드를 가진 객체."""

    def __init__(self, api):
        self.api = api

    def read(self, names):
        """names: 찾아볼 실행 파일 이름(전체 경로 우선). 프로필이 없거나 설정이 없으면 None."""
        with self.api.session() as session:
            profile = self._find(session, names)
            if profile is None:
                return None
            return self.api.get_setting(session, profile, FRL_FPS_ID)

    def write(self, names, value):
        """value가 None이면 설정을 지운다(앱이 만든 프로필이면 프로필째). 쓴 뒤 저장한다."""
        if value is not None and (type(value) is not int or not 0 <= value <= 1023):
            raise ValueError('최대 프레임 값을 확인해 주세요.')
        with self.api.session() as session:
            profile = self._find(session, names)
            if value is None:
                if profile is None:
                    return
                if self.api.profile_name(session, profile) == OWN_PROFILE:
                    self.api.delete_profile(session, profile)
                else:
                    self.api.delete_setting(session, profile, FRL_FPS_ID)
            else:
                if profile is None:
                    profile = self.api.find_profile(session, OWN_PROFILE) or self.api.create_profile(session, OWN_PROFILE)
                    # 전체 경로로 등록(0.23.0 QA: 이름만이면 사전 정의 'Client.exe'와 겹치고 같은 이름의 다른 게임에도 걸림)
                    self.api.add_application(session, profile, names[0])
                self.api.set_setting(session, profile, FRL_FPS_ID, value)
            self.api.save(session)

    def _find(self, session, names):
        for name in names:
            profile = self.api.find_application(session, name)
            if profile is not None:
                return profile
        return None



# ---- Windows NVAPI(ctypes) -------------------------------------------------------------------

_IDS = dict(
    Initialize=0x0150E828, GetErrorMessage=0x6C2D048C, EnumPhysicalGPUs=0xE5AC921F, GPU_GetFullName=0xCEEE8E9F,
    DRS_CreateSession=0x0694D52E, DRS_DestroySession=0xDAD9CFF8, DRS_LoadSettings=0x375DBD6B,
    DRS_SaveSettings=0xFCBC7E14, DRS_FindApplicationByName=0xEEE566B2, DRS_FindProfileByName=0x7E4A9A0B,
    DRS_CreateProfile=0xCC176068, DRS_DeleteProfile=0x17093206, DRS_CreateApplication=0x4347A9DE,
    DRS_GetProfileInfo=0x61CD6FD6, DRS_GetSetting=0x73BF8338, DRS_SetSetting=0x577DD202,
    DRS_DeleteProfileSetting=0xE4A26362,
)


class _Nvapi:
    """nvapi64.dll의 DRS 기본 동작. 구조체는 NVAPI 헤더(R5xx)의 V1 배치를 따른다."""

    def __init__(self):
        if sys.platform != 'win32':
            raise OSError('Windows에서만 사용할 수 있어요.')
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        try:
            dll = ctypes.WinDLL('nvapi64.dll')
        except OSError as exc:
            raise OSError('NVIDIA 드라이버(nvapi64.dll)를 찾지 못했어요.') from exc
        query = dll.nvapi_QueryInterface
        query.restype = ctypes.c_void_p
        query.argtypes = [ctypes.c_uint]
        self._query = query
        self._fns = {}
        status = self._fn('Initialize', [])()
        if status != NVAPI_OK:
            raise NvapiError('초기화', status, self._message(status))
        u16 = ctypes.c_uint16
        unicode = u16 * 2048

        class Value(ctypes.Union):
            _fields_ = [('u32', ctypes.c_uint32), ('raw', ctypes.c_uint8 * 4100)]

        class Setting(ctypes.Structure):
            _fields_ = [('version', ctypes.c_uint32), ('settingName', unicode), ('settingId', ctypes.c_uint32),
                        ('settingType', ctypes.c_uint32), ('settingLocation', ctypes.c_uint32),
                        ('isCurrentPredefined', ctypes.c_uint32), ('isPredefinedValid', ctypes.c_uint32),
                        ('predefined', Value), ('current', Value)]

        class Profile(ctypes.Structure):
            _fields_ = [('version', ctypes.c_uint32), ('profileName', unicode), ('gpuSupport', ctypes.c_uint32),
                        ('isPredefined', ctypes.c_uint32), ('numOfApps', ctypes.c_uint32), ('numOfSettings', ctypes.c_uint32)]

        class Application(ctypes.Structure):  # V1: 버전·사전정의·앱 이름·표시 이름·런처
            _fields_ = [('version', ctypes.c_uint32), ('isPredefined', ctypes.c_uint32), ('appName', unicode),
                        ('userFriendlyName', unicode), ('launcher', unicode)]

        self.Setting, self.Profile, self.Application, self.unicode = Setting, Profile, Application, unicode

    @staticmethod
    def _version(struct, number=1):
        import ctypes
        return ctypes.sizeof(struct) | (number << 16)

    def _fn(self, name, argtypes):
        if name not in self._fns:
            address = self._query(_IDS[name])
            if not address:
                raise OSError(f'NVAPI 함수를 찾지 못했어요({name}).')
            self._fns[name] = self.ctypes.CFUNCTYPE(self.ctypes.c_int, *argtypes)(address)
        return self._fns[name]

    def _message(self, status):
        try:
            text = self.ctypes.create_string_buffer(64)
            self._fn('GetErrorMessage', [self.ctypes.c_int, self.ctypes.c_char_p])(status, text)
            return text.value.decode('ascii', 'replace')
        except Exception:
            return ''

    def _check(self, operation, status, *allowed):
        if status != NVAPI_OK and status not in allowed:
            raise NvapiError(operation, status, self._message(status))
        return status

    def _text(self, value):
        buffer = self.unicode()
        for i, ch in enumerate(str(value)[:2047]):
            buffer[i] = ord(ch)
        return buffer

    def gpu_names(self):
        c = self.ctypes
        handles, count = (c.c_void_p * 64)(), c.c_uint32()
        self._check('그래픽카드 목록', self._fn('EnumPhysicalGPUs', [c.c_void_p, c.POINTER(c.c_uint32)])(handles, c.byref(count)))
        names = []
        for i in range(count.value):
            name = c.create_string_buffer(64)
            if self._fn('GPU_GetFullName', [c.c_void_p, c.c_char_p])(handles[i], name) == NVAPI_OK:
                names.append(name.value.decode('ascii', 'replace'))
        return names

    def session(self):
        api = self

        class _Session:
            def __enter__(self_):
                c = api.ctypes
                handle = c.c_void_p()
                api._check('설정 세션', api._fn('DRS_CreateSession', [c.POINTER(c.c_void_p)])(c.byref(handle)))
                self_.handle = handle
                try:
                    api._check('설정 불러오기', api._fn('DRS_LoadSettings', [c.c_void_p])(handle))
                except Exception:
                    api._fn('DRS_DestroySession', [c.c_void_p])(handle)
                    raise
                return handle

            def __exit__(self_, *exc):
                api._fn('DRS_DestroySession', [api.ctypes.c_void_p])(self_.handle)
                return False

        return _Session()

    def find_application(self, session, name):
        c = self.ctypes
        profile, app = c.c_void_p(), self.Application()
        app.version = self._version(self.Application)
        status = self._fn('DRS_FindApplicationByName', [c.c_void_p, c.POINTER(self.unicode), c.POINTER(c.c_void_p),
                                                         c.POINTER(self.Application)])(
            session, c.byref(self._text(name)), c.byref(profile), c.byref(app))
        if self._check('프로필 찾기', status, NVAPI_EXECUTABLE_NOT_FOUND, NVAPI_PROFILE_NOT_FOUND) != NVAPI_OK:
            return None
        return profile

    def find_profile(self, session, name):
        c = self.ctypes
        profile = c.c_void_p()
        status = self._fn('DRS_FindProfileByName', [c.c_void_p, c.POINTER(self.unicode), c.POINTER(c.c_void_p)])(
            session, c.byref(self._text(name)), c.byref(profile))
        return None if self._check('프로필 찾기', status, NVAPI_PROFILE_NOT_FOUND) != NVAPI_OK else profile

    def profile_name(self, session, profile):
        c = self.ctypes
        info = self.Profile()
        info.version = self._version(self.Profile)
        self._check('프로필 정보', self._fn('DRS_GetProfileInfo', [c.c_void_p, c.c_void_p, c.POINTER(self.Profile)])(
            session, profile, c.byref(info)))
        return ''.join(chr(ch) for ch in info.profileName).split('\x00', 1)[0]

    def create_profile(self, session, name):
        c = self.ctypes
        info, profile = self.Profile(), c.c_void_p()
        info.version = self._version(self.Profile)
        info.profileName = self._text(name)
        self._check('프로필 만들기', self._fn('DRS_CreateProfile', [c.c_void_p, c.POINTER(self.Profile), c.POINTER(c.c_void_p)])(
            session, c.byref(info), c.byref(profile)))
        return profile

    def delete_profile(self, session, profile):
        c = self.ctypes
        self._check('프로필 지우기', self._fn('DRS_DeleteProfile', [c.c_void_p, c.c_void_p])(session, profile))

    def add_application(self, session, profile, name):
        c = self.ctypes
        app = self.Application()
        app.version = self._version(self.Application)
        app.appName = self._text(name)
        self._check('실행 파일 등록', self._fn('DRS_CreateApplication', [c.c_void_p, c.c_void_p, c.POINTER(self.Application)])(
            session, profile, c.byref(app)))

    def get_setting(self, session, profile, setting_id):
        c = self.ctypes
        setting = self.Setting()
        setting.version = self._version(self.Setting)
        status = self._fn('DRS_GetSetting', [c.c_void_p, c.c_void_p, c.c_uint32, c.POINTER(self.Setting)])(
            session, profile, setting_id, c.byref(setting))
        if self._check('설정 읽기', status, NVAPI_SETTING_NOT_FOUND) != NVAPI_OK:
            return None
        return int(setting.current.u32)

    def set_setting(self, session, profile, setting_id, value):
        c = self.ctypes
        setting = self.Setting()
        setting.version = self._version(self.Setting)
        setting.settingId, setting.settingType = setting_id, 0  # NVDRS_DWORD_TYPE
        setting.current.u32 = value
        self._check('설정 쓰기', self._fn('DRS_SetSetting', [c.c_void_p, c.c_void_p, c.POINTER(self.Setting)])(
            session, profile, c.byref(setting)))

    def delete_setting(self, session, profile, setting_id):
        c = self.ctypes
        status = self._fn('DRS_DeleteProfileSetting', [c.c_void_p, c.c_void_p, c.c_uint32])(session, profile, setting_id)
        self._check('설정 지우기', status, NVAPI_SETTING_NOT_FOUND)

    def save(self, session):
        self._check('설정 저장', self._fn('DRS_SaveSettings', [self.ctypes.c_void_p])(session))


_api = None


def api():
    """한 번 초기화한 NVAPI(없으면 OSError)."""
    global _api
    if _api is None:
        _api = _Nvapi()
    return _api


def nvidia_gpu():
    """NVIDIA 그래픽카드 이름(여러 개면 첫 번째) 또는 None(NVIDIA 아님·드라이버 없음)."""
    if sys.platform != 'win32':
        return None
    try:
        names = api().gpu_names()
    except Exception:
        return None
    return names[0] if names else None
