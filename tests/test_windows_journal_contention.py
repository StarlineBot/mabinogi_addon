"""Real Windows delete-sharing contention; mock results cannot replace this gate."""
import sys
import threading
from types import SimpleNamespace
import pytest

pytestmark=[pytest.mark.windows_integration,pytest.mark.skipif(sys.platform!='win32',reason='Windows file sharing semantics')]


@pytest.mark.parametrize('release_during_retry',[True,False])
def test_reader_without_delete_sharing_blocks_real_replace(tmp_path,monkeypatch,release_during_retry):
    import ctypes
    from test_support import progress
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    monkeypatch.setenv('MABINOGI_TEST_DIAGNOSTICS',str(tmp_path))
    monkeypatch.setattr(progress.Journal,'arm',lambda self:None)
    journal=progress.Journal(SimpleNamespace())
    handle=kernel.CreateFileW(str(journal.path),0x80000000,1|2,None,3,0x80,None)
    assert handle not in (None,ctypes.c_void_p(-1).value),ctypes.get_last_error()
    released=threading.Event();timer=None;denials=[];replace=progress._REPLACE
    def release():
        kernel.CloseHandle(handle);released.set()
    def observed(source,target):
        try: return replace(source,target)
        except PermissionError as error:
            denials.append(error.winerror)
            raise
    monkeypatch.setattr(progress,'_REPLACE',observed)
    try:
        if release_during_retry:
            timer=threading.Timer(.08,release);timer.start()
        journal.emit(outcome='passed')
        assert denials and set(denials)<={5,32}
        if release_during_retry:
            assert not journal.failed and '"outcome": "passed"' in journal.path.read_text(encoding='utf-8')
        else:
            assert journal.failed and list(tmp_path.glob('*.error'))
    finally:
        if timer is not None: timer.join(timeout=2)
        if not released.is_set(): release()
        journal.raw.close()
