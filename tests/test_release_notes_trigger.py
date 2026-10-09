"""업데이트 노트가 '언제 뜨는지' 회귀 테스트(_maybe_show_release_notes).

과거 버그: start()가 window.show()보다 먼저 불려 isVisible=False → 노트가 매번 스킵됐다.
이제 창이 보이는 상태에서 조건이 맞으면 다이얼로그가 뜨고, 아니면 안 뜬다.
(실제 앱은 show() 뒤에 실행되도록 start()에서 이벤트 루프로 미뤄 호출한다.)
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

import mabinogi_addon.version as ver
from mabinogi_addon import config
from mabinogi_addon.ui import release_notes as rn


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    _app()
    from mabinogi_addon.ui.main_window import MainWindow

    w = MainWindow()
    w.show()  # 실제 앱처럼 '보이는' 상태(과거 버그의 핵심 조건)
    yield w
    w.close()


def _stub_dialog(monkeypatch) -> dict:
    calls: dict = {}

    class _Stub:
        def __init__(self, md, v, parent=None):
            calls["md"] = md
            calls["v"] = v

        def exec(self):
            calls["exec"] = True
            return 0

    monkeypatch.setattr(rn, "ReleaseNotesDialog", _Stub)
    return calls


def test_shows_for_existing_user_on_new_version(win, monkeypatch):
    monkeypatch.setattr(ver, "__version__", "0.3.21")
    monkeypatch.setattr(config, "load_last_seen_version", lambda *a, **k: None)
    saved: dict = {}
    monkeypatch.setattr(
        config, "save_last_seen_version", lambda v, *a, **k: saved.update(v=v)
    )
    # 기존 사용자(투어 이미 봄) → 노트 경로
    monkeypatch.setattr(
        config,
        "load_general_flag",
        lambda key, default=False, *a, **k: True if key == "tourShown" else default,
    )
    calls = _stub_dialog(monkeypatch)

    win._maybe_show_release_notes()

    assert calls.get("exec") is True
    assert calls.get("v") == "0.3.21"
    assert saved.get("v") == "0.3.21"  # 본 버전 기록


def test_no_notes_when_already_seen(win, monkeypatch):
    monkeypatch.setattr(ver, "__version__", "0.3.21")
    monkeypatch.setattr(config, "load_last_seen_version", lambda *a, **k: "0.3.21")
    calls = _stub_dialog(monkeypatch)

    win._maybe_show_release_notes()

    assert "exec" not in calls  # 같은 버전 → 안 뜸


def test_shows_regardless_of_tour_flag(win, monkeypatch):
    # 투어 플래그(tourShown)와 무관하게 버전만 바뀌면 노트가 뜬다(게이트 제거).
    monkeypatch.setattr(ver, "__version__", "0.3.21")
    monkeypatch.setattr(config, "load_last_seen_version", lambda *a, **k: None)
    monkeypatch.setattr(config, "save_last_seen_version", lambda *a, **k: None)
    monkeypatch.setattr(config, "load_general_flag", lambda *a, **k: False)
    calls = _stub_dialog(monkeypatch)

    win._maybe_show_release_notes()

    assert calls.get("exec") is True


def test_dev_build_skips(win, monkeypatch):
    monkeypatch.setattr(ver, "__version__", "0.0.0")
    calls = _stub_dialog(monkeypatch)

    win._maybe_show_release_notes()

    assert "exec" not in calls


def test_showevent_fires_first_shown_once(monkeypatch):
    _app()
    from mabinogi_addon.ui.main_window import MainWindow

    w = MainWindow()
    w._booting = False  # 실앱에선 start()가 show() 전에 끝내는 상태
    n = {"c": 0}
    monkeypatch.setattr(w, "_on_first_shown", lambda: n.__setitem__("c", n["c"] + 1))
    w.show()
    QApplication.processEvents()
    w.hide()
    w.show()  # 복원 — 재실행되면 안 됨
    QApplication.processEvents()
    w.close()
    assert n["c"] == 1  # 창이 여러 번 보여도 1회만
