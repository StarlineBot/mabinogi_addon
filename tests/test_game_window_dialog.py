"""게임 창 선택 팝업·창 목록 스모크 테스트 (오프스크린).

win32 전용 기능은 맥/리눅스에서 빈 목록으로 폴백해야 하고(앱이 안 깨짐),
팝업은 그 상태에서도 '게임을 먼저 켜세요' 안내를 보여야 한다.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mabinogi_addon.system import window_watcher
from mabinogi_addon.ui.game_window_dialog import GameWindowDialog


@pytest.fixture(scope="module")
def _app():
    return QApplication.instance() or QApplication([])


def test_list_windows_empty_off_win32() -> None:
    if sys.platform != "win32":
        assert window_watcher.list_windows() == []


class _StubWatcher:
    def __init__(self) -> None:
        self.exe = None

    def set_game_exe(self, exe: str | None) -> None:
        self.exe = exe


def test_dialog_builds_and_shows_empty_hint(_app) -> None:
    # 목록을 빈 것으로 강제 → '게임을 먼저 켜세요' 안내가 보여야 한다.
    dlg = GameWindowDialog(_StubWatcher())
    if sys.platform != "win32":
        assert dlg._empty.isVisible() or not dlg._combo.isVisibleTo(dlg)
    dlg.deleteLater()


def test_dialog_accept_saves_selected_exe(_app, monkeypatch) -> None:
    saved = {}
    monkeypatch.setattr(
        window_watcher, "list_windows",
        lambda: [("마비노기", "client.exe"), ("메모장", "notepad.exe")],
    )
    # game_window_dialog 는 import 시점에 list_windows 를 가져오므로 그쪽도 패치.
    import mabinogi_addon.ui.game_window_dialog as gwd

    monkeypatch.setattr(
        gwd, "list_windows",
        lambda: [("마비노기", "client.exe"), ("메모장", "notepad.exe")],
    )
    monkeypatch.setattr(gwd.config, "save_game_exe", lambda exe: saved.update(exe=exe))
    monkeypatch.setattr(gwd.config, "save_general_flag", lambda *a, **k: None)

    watcher = _StubWatcher()
    dlg = GameWindowDialog(watcher)
    # 마비노기 창이 기본 선택돼야 한다.
    assert dlg._combo.currentData() == "client.exe"
    dlg._on_accept()
    assert saved.get("exe") == "client.exe"
    assert watcher.exe == "client.exe"
    dlg.deleteLater()
