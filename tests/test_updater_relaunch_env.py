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
