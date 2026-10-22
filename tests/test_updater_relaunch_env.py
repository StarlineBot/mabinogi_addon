"""재실행 환경에서 PyInstaller 내부 변수를 제거하는지(_MEI 재추출 보장)."""

from __future__ import annotations

from mabinogi_addon.system import updater


def test_relaunch_env_strips_pyinstaller_vars(monkeypatch) -> None:
    monkeypatch.setenv("_MEIPASS2", r"C:\Temp\_MEIold")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\Temp\_MEIold")
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", r"C:\app.exe")
    monkeypatch.setenv("PATH", "keepme")
    env = updater._relaunch_env()
    assert "_MEIPASS2" not in env
    assert not any(k.startswith("_PYI") for k in env)
    assert env.get("PATH") == "keepme"  # 일반 변수는 유지


# --- 0.11.4: 관리자 권한 exe 재실행(ShellExecuteEx runas) -------------------------------------
import ctypes
import os
import sys

import pytest


def _replaced(tmp_path):
    exe = tmp_path / "mabinogi-addon.exe"
    exe.write_bytes(b"old")
    new = tmp_path / "download.exe"
    new.write_bytes(b"new")
    return exe, new


@pytest.mark.parametrize("admin, popen_error, expected", [
    (False, None, ["runas"]),              # 일반 권한 부모 → 바로 UAC 승격 실행
    (True, 740, ["popen", "runas"]),       # 관리자 판정이어도 740이면 승격 실행
    (True, None, ["popen"]),               # 관리자 → 권한을 이어받아 그대로 실행
])
def test_relaunch_elevates_when_not_admin_or_elevation_required(monkeypatch, tmp_path, admin, popen_error, expected):
    import subprocess
    exe, new = _replaced(tmp_path)
    calls = []
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(updater, "_is_admin", lambda: admin)
    def popen(*a, **k):
        calls.append("popen")
        if popen_error:
            err = OSError("elevation required"); err.winerror = popen_error; raise err
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(updater, "_launch_elevated", lambda path: calls.append("runas"))
    updater.apply_update(new)
    assert calls == expected and exe.read_bytes() == b"new"


def test_relaunch_failure_after_install_is_reported_as_restart_needed(monkeypatch, tmp_path):
    exe, new = _replaced(tmp_path)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(updater, "_is_admin", lambda: False)
    def cancelled(path):
        raise OSError(1223, "The operation was canceled by the user")
    monkeypatch.setattr(updater, "_launch_elevated", cancelled)
    with pytest.raises(updater.RelaunchError, match="새 버전을 자동으로 시작하지 못했어요"):
        updater.apply_update(new)
    assert exe.read_bytes() == b"new"  # 설치는 끝났다 → 사용자가 다시 실행하면 새 버전


def test_launch_elevated_uses_runas_and_strips_pyinstaller_env(monkeypatch, tmp_path):
    seen = {}
    class Shell:
        class ShellExecuteExW:
            argtypes = restype = None
            def __new__(cls, info):
                data = info._obj
                seen.update(verb=data.lpVerb, file=data.lpFile, env=dict(os.environ))
                return 1
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **k: Shell, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)
    monkeypatch.setenv("_MEIPASS2", "x"); monkeypatch.setenv("_PYI_ARCHIVE_FILE", "y"); monkeypatch.setenv("KEEP", "1")
    updater._launch_elevated(tmp_path / "app.exe")
    assert seen["verb"] == "runas" and seen["file"] == str(tmp_path / "app.exe")
    assert "_MEIPASS2" not in seen["env"] and not any(k.startswith("_PYI") for k in seen["env"])
    assert seen["env"]["KEEP"] == "1"
