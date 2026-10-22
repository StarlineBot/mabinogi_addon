"""Windows Videos Known Folder; respect redirected/localized user folders."""
import ctypes
from pathlib import Path
import sys
import uuid


def videos_folder():
    if sys.platform != 'win32':
        raise OSError('Windows Videos Known Folder is required')
    from ctypes import wintypes
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    ole = ctypes.WinDLL('ole32')
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID('18989b1d-99b5-455b-841c-ab7c74e4ddfc').bytes_le)
    result = ctypes.c_void_p()
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE,
                                          ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    try:
        hr = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(result))
        if hr < 0 or not result.value:
            raise OSError(f'Videos Known Folder lookup failed: {hr:#x}')
        return Path(ctypes.wstring_at(result))
    finally:
        if result.value:
            ole.CoTaskMemFree(result)
