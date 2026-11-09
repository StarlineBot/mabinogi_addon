"""첫 사용 안내 v3(docs/first-use-v3-spec.md 2·4절) — 3장, 홈과 같은 스위치 값, 찾기 상태, 게임 창 자동 연결, 새 설치에만."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication

from mabinogi_addon import autofind_regions, config
from mabinogi_addon.ui.first_use import FirstUseGuide, game_windows, status_text

GAME = ("마비노기 모바일", "MabinogiMobile.exe")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _guide(state=None, windows=(), game=None):
    store = {"exe": game}
    g = FirstUseGuide(state_fn=lambda: state or {}, windows_fn=lambda: list(windows), game_fn=lambda: store["exe"])
    g.game_connected.connect(lambda exe: store.__setitem__("exe", exe))
    return g, store


def test_three_pages_copy_and_buttons(app):
    g, _ = _guide()
    g.go(0)
    assert not g.later_btn.isHidden() and g.back_btn.isHidden() and g.next_btn.text() == "다음"
    g.go(1)
    assert set(g.rows) == {"buff", "debuff", "boss", "halo", "tuarim", "stat_bars", "dorcha", "skillbar",
                           "opt", "fps", "cursor", "blackbox"}  # 12개(D4 '그 밖에' 4개 포함)
    assert not g.rows["buff"].status.isHidden() and g.rows["opt"].status.isHidden()  # 찾기 상태는 화면을 읽는 8개만
    g.go(2)
    assert g.next_btn.text() == "앱 둘러보기 시작" and not g.skip_tour_btn.isHidden()
    assert g.ready_list.text() == "아직 켠 기능이 없어요 — 홈에서 언제든 켤 수 있어요"
    done = []
    g.finished.connect(done.append)
    g.skip_tour_btn.click()
    g.next_btn.click()
    assert done == [False, True]


def test_switches_follow_home_values_and_report_toggles(app):
    state = {"buff": (True, "found"), "boss": (False, "wait"), "halo": (False, "wait"), "tuarim": (False, "hidden"), "opt": (True, None)}
    g, _ = _guide(state)
    toggles = []
    g.feature_toggled.connect(lambda k, on: toggles.append((k, on)))
    g.go(1)
    assert g.rows["buff"].switch.isChecked() and g.rows["opt"].switch.isChecked() and not g.rows["boss"].switch.isChecked()
    assert "위치 찾음" in g.rows["buff"].status.text() and "보스 나오면 찾아요" in g.rows["boss"].status.text()
    assert "전투 시간 보이면 찾아요" in g.rows["halo"].status.text() and "게임에 접속하면 찾아요" in g.rows["tuarim"].status.text()
    g.rows["boss"].switch.click()
    assert toggles == [("boss", True)]
    g.go(2)
    assert g.ready_list.text() == "켠 기능: 버프 · 게임 최적화"


def test_status_text_never_says_missing_while_ui_hidden():
    assert status_text("buff", "hidden") == ("게임에 접속하면 찾아요", "muted")
    assert status_text("stat_bars", "found") == ("위치 찾음", "ok")
    assert status_text("debuff", "missing")[0] == "보스 나오면 찾아요"
    assert status_text("buff", None) is None


def test_game_window_auto_connect_only_when_single(app):
    assert game_windows([GAME, ("메모장", "notepad.exe")]) == [GAME]
    g, store = _guide(windows=[GAME, ("메모장", "notepad.exe")])
    g.start()
    assert store["exe"] == GAME[1] and "마비노기 창을 찾았어요" in g.game_status.text()
    g.stop()
    many, store2 = _guide(windows=[GAME, ("Mabinogi 2", "Mabinogi2.exe")])
    many.start()
    assert store2["exe"] is None and not many.game_pick_row.isHidden() and many.game_pick.count() == 2
    many.game_pick.setCurrentIndex(1)
    many.game_pick_btn.click()
    assert store2["exe"] == "Mabinogi2.exe"
    many.stop()
    none, store3 = _guide(windows=[])
    none.start()
    assert store3["exe"] is None and "마비노기를 켜 주세요" in none.game_status.text()
    none.stop()


@pytest.mark.autofind_default
def test_new_install_shows_first_use_and_finishing_marks_done(app, monkeypatch):
    """새 설치에만 띄우고, 2단계 스위치 = 홈 값(버프 켜면 사용 값 저장), 끝내면 다시 저절로 뜨지 않는다."""
    from types import SimpleNamespace

    from mabinogi_addon.ui import main_window
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "테스트"})
    monkeypatch.setattr(main_window, "create_live_source", lambda *a, **k: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(main_window.MainWindow, "_start_buff_tracking", lambda self: None)
    monkeypatch.setattr(main_window.MainWindow, "_start_debuff_tracking", lambda self: None)
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen, "availableGeometry", lambda self: QRect(0, 0, 1600, 1100))
    w = main_window.MainWindow()  # 설정 파일 없음 = 새 설치
    try:
        for timer in w.findChildren(QTimer):
            timer.stop()
        assert config._read_local_config()["general"]["firstUse"] == "pending"
        assert w._pages.currentWidget() is w.first_use
        w._open_guide()
        w.first_use.go(1)
        assert not w.first_use.rows["buff"].switch.isChecked()  # 새 사용자 기본 꺼짐
        w.first_use.rows["buff"].switch.click()
        assert autofind_regions.use_on("buff") and config._read_local_config()["autofindV2"]["use"]["buff"] is True
        w.first_use.go(2)
        w.first_use.skip_tour_btn.click()
        assert config._read_local_config()["general"]["firstUse"] == "done"
        assert w._pages.currentWidget() is w._tabs and w.home_visible()
        from mabinogi_addon import setup_state
        assert not setup_state.needs_start_screen()
    finally:
        w._force_quit = True
        w.close()
        app.processEvents()


@pytest.mark.parametrize("page", [0, 1, 2])
def test_pages_fit_default_window_without_scroll(app, page):
    """790×864 기본 창(머리 줄 제외 안내 영역 약 790×744)에 세 장 모두 넘치지 않는다 — CI 글꼴(Noto CJK + DejaVu)로도 확인."""
    state = {k: (True, "found") for k in ("buff", "debuff", "boss", "halo", "tuarim", "stat_bars", "dorcha", "skillbar")}
    g, _ = _guide(state, windows=[GAME, ("Mabinogi 2", "Mabinogi2.exe")])
    g.resize(790, 744)
    g.show()
    g.start()
    g.go(page)
    app.processEvents()
    hint = g.minimumSizeHint()
    assert hint.width() <= 790 and hint.height() <= 744, hint
    assert g.layout().sizeHint().height() <= 744 - 8
    g.stop()
    g.close()
