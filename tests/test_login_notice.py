"""로그인 1.0 예고(계정 명세 4.1, 사용자 결정 11-23): 비로그인 홈 띠·✕ 확인 창·동의 기록·노트 창 맨 위 고정."""
import json

import pytest
from test_navigation import window  # noqa: F401  (픽스처)

from mabinogi_addon import cloud_sync, config, login_notice


def test_pure_rules():
    assert login_notice.show_home_notice(False, None)
    assert not login_notice.show_home_notice(True, None)
    assert not login_notice.show_home_notice(False, "2026-11-23")
    block = login_notice.pinned_notes_block("0.55.4")
    assert block == f"## ❗ 꼭 읽어보세요 ❗\n\n{login_notice.BODY}\n\n"      # 버전 섹션과 같은 규격(인용 아님)
    from mabinogi_addon.ui.release_notes import _parse_sections
    assert _parse_sections(block + "## v0.56.0\n\n노트\n") == [("0.56.0", "노트")]   # 버전 파싱에 안 섞임
    assert login_notice.BODY in login_notice.pinned_notes_block("0.99.9")
    assert login_notice.pinned_notes_block("1.0.0") == "" and login_notice.pinned_notes_block("1.2.3") == ""


def _login(monkeypatch, on):
    user = {"id": "1", "name": "테스터", "tier": "user"} if on else None
    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: user)


def test_home_band_only_when_logged_out_and_follows_login(window, monkeypatch):  # noqa: F811
    w, _app = window
    _login(monkeypatch, False)
    w.refresh_login_notice()
    box = w.home_page.login_box
    assert box.isVisibleTo(w.home_page)
    assert w.home_page.login_title.text() == "❗ 꼭 읽어보세요 ❗" and w.home_page.login_body.text() == login_notice.BODY
    assert w.home_page.login_btn.text() == "디스코드로 로그인"
    _login(monkeypatch, True)
    w.settings_tab.login_changed.emit()                      # 로그인하면 바로 사라짐
    assert not box.isVisibleTo(w.home_page)
    _login(monkeypatch, False)
    w.settings_tab.login_changed.emit()                      # 로그아웃·풀림이면 다시
    assert box.isVisibleTo(w.home_page)


def test_band_above_overseas_notice(window, monkeypatch):  # noqa: F811
    w, _app = window
    _login(monkeypatch, False)
    w.refresh_login_notice()
    w.home_page.show_notice(w.OVERSEAS_KO, w.OVERSEAS_EN)
    lay = w.home_page._content_layout
    order = [lay.itemAt(i).widget() for i in range(lay.count())]
    assert order.index(w.home_page.login_box) < order.index(w.home_page.notice_box)


def test_login_button_opens_account(window, monkeypatch):  # noqa: F811
    w, _app = window
    opened = []
    monkeypatch.setattr(w, "open_account", lambda: opened.append(True))
    w.home_page.login_notice_login.disconnect()
    w.home_page.login_notice_login.connect(w.open_account)
    w.home_page.login_btn.click()
    assert opened == [True]


@pytest.mark.parametrize("choice", ["login", "agree", "cancel"])
def test_close_asks_with_three_buttons(window, monkeypatch, choice):  # noqa: F811
    w, _app = window
    _login(monkeypatch, False)
    w.refresh_login_notice()
    opened = []
    monkeypatch.setattr(w, "open_account", lambda: opened.append(True))
    seen = {}

    def run(box):
        seen["title"], seen["body"] = box.windowTitle(), box.informativeText()
        seen["buttons"] = [b.text() for b in box.buttons()]
        index = {"login": 0, "agree": 1, "cancel": 2}[choice]
        box.buttons()[[b.text() for b in box.buttons()].index(
            [login_notice.LOGIN_BUTTON, login_notice.AGREE_BUTTON, login_notice.CANCEL_BUTTON][index])].click()
    monkeypatch.setattr(w, "_run_login_notice_box", run)
    w.home_page.login_close.click()
    assert seen["title"] == "안내를 다시 보지 않을까요?" and seen["body"] == login_notice.CONFIRM_BODY
    assert sorted(seen["buttons"]) == sorted(["디스코드로 로그인", "다시 보지 않기", "취소"])
    box = w.home_page.login_box
    if choice == "login":
        assert opened == [True] and box.isVisibleTo(w.home_page) and config.load_login_notice_agreed() is None
    elif choice == "agree":
        assert config.load_login_notice_agreed() and not box.isVisibleTo(w.home_page)
        _login(monkeypatch, True)
        w.refresh_login_notice()
        _login(monkeypatch, False)                            # 로그아웃해도 다시 안 뜸
        w.refresh_login_notice()
        assert not box.isVisibleTo(w.home_page)
    else:
        assert box.isVisibleTo(w.home_page) and config.load_login_notice_agreed() is None and not opened


def test_agreed_is_this_pc_value(tmp_path):
    config.save_login_notice_agreed("2026-11-23")
    config.save_general_flag("gridSnap", True)
    raw = config._read_local_config()
    assert "loginNoticeAgreed" not in cloud_sync.strip_for_sync(raw).get("general", {})       # 동기화 빼기
    exported = json.loads(config.config_json_for_export())
    assert "loginNoticeAgreed" not in exported["general"] and exported["general"]["gridSnap"] is True
    incoming = {"general": {"loginNoticeAgreed": "2000-01-01", "gridSnap": False}}
    src = tmp_path / "in.json"
    src.write_text(json.dumps(incoming), encoding="utf-8")
    config.import_config(src)                                                               # 가져오기로 안 덮음
    assert config.load_login_notice_agreed() == "2026-11-23"
    merged = cloud_sync.merge_incoming(incoming, config._read_local_config(), same_resolution=True)   # 동기화 받기도
    assert merged["general"]["loginNoticeAgreed"] == "2026-11-23"


def test_release_notes_window_pins_block_before_1_0():
    from PySide6.QtWidgets import QApplication, QTextBrowser
    QApplication.instance() or QApplication([])
    from mabinogi_addon.ui.release_notes import ReleaseNotesDialog
    dlg = ReleaseNotesDialog("## v0.55.4\n\n노트", "0.55.4")
    browser = dlg.findChild(QTextBrowser)
    text = browser.toPlainText()
    assert text.startswith("❗ 꼭 읽어보세요 ❗") and login_notice.BODY in text and "노트" in text
    doc = browser.document()
    first, version = doc.firstBlock(), doc.findBlock(text.index("v0.55.4"))
    assert first.blockFormat().headingLevel() == version.blockFormat().headingLevel() == 2   # 버전 헤더와 같은 수준
    assert first.blockFormat().indent() == 0 and doc.findBlock(text.index(login_notice.BODY)).blockFormat().indent() == 0
    dlg.close()
    dlg = ReleaseNotesDialog("## v1.0.0\n\n노트", "1.0.0")
    assert "꼭 읽어보세요" not in dlg.findChild(QTextBrowser).toPlainText()
    dlg.close()
