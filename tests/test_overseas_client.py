"""북미(영문 제목) 마비노기 클라이언트 경고(사용자 결정 11-18 — 자동 차단 폐기, 안내 문구만 강화).

차단 없이 앱 실행마다 한 번 홈 띠 + 트레이 알림. 북미 판정은 제목이 정확히 'Mabinogi'(한국은 '마비노기',
실행파일은 둘 다 Client.exe라 제목으로만 구분). 경고가 '애드온을 끄라'는 내용이라 한국 사용자에게 뜨면 안 된다."""
import pytest
from test_navigation import window  # noqa: F401  (픽스처)

from mabinogi_addon import cloud_sync, config
from mabinogi_addon.system.window_watcher import is_game_title, is_overseas_title


@pytest.mark.parametrize("title,overseas", [
    ("Mabinogi", True), ("MABINOGI", True), (" mabinogi ", True),
    ("마비노기", False), ("마비노기 Mabinogi", False), ("Mabinogi 마비노기", False),
    ("", False), (None, False), ("메모장", False),
    # 등록 실행파일이 없는 한국 사용자가 앞에 띄울 수 있는 창 — '포함' 판정이면 경고가 떴다
    ("mabinogi_2026_11_18_123456.jpg - 꿀뷰", False), ("Mabinogi 길드", False),
    ("OBS 30.2 - Profile: Mabinogi", False), ("mabinogi - Client", False),
])
def test_title_decision(title, overseas):
    assert is_overseas_title(title) is overseas


@pytest.mark.parametrize("title,exe,shown", [
    ("Mabinogi", "client.exe", True),               # NA 게임 창
    ("Mabinogi", "", True),                         # 실행파일을 못 읽으면 제목만(게임 판정과 같은 규칙)
    ("Mabinogi", "chrome.exe", False),              # 제목이 딱 'Mabinogi'인 브라우저 — 제외 목록은 게임 아님
    ("Mabinogi - Google Chrome", "chrome.exe", False),
    ("마비노기", "client.exe", False),               # 한국 게임 창
])
def test_with_not_game_exclusions(title, exe, shown):
    assert (is_overseas_title(title) and is_game_title(title, exe)) is shown


def test_warning_text_and_tray_limit(window):  # noqa: F811
    w, _ = window
    assert "애드온을 끄고 플레이해 주세요" in w.OVERSEAS_KO and "close the addon" in w.OVERSEAS_EN
    for text in (w.OVERSEAS_KO, w.OVERSEAS_EN, w.OVERSEAS_TRAY):
        assert "문의" not in text and "Contact" not in text  # 실행을 권하게 되는 '게임 화면 보내기' 권유는 뺌
    assert w.OVERSEAS_TRAY_TITLE == "한국 서버 전용 · Korean server only"
    assert w.OVERSEAS_TRAY.startswith(w.OVERSEAS_KO + "\n")
    assert len(w.OVERSEAS_TRAY) == 210  # Windows 트레이 알림 본문 한도(약 255자) 안


class Tray:
    def __init__(self):
        self.messages = []

    def showMessage(self, title, body, *_):
        self.messages.append((title, body))


def _foreground(mp, w, title, exe="client.exe", active=True):
    mp.setattr(w._watcher, "is_game_active", lambda: active)
    mp.setattr(w._watcher, "foreground_info", lambda: (title, exe))


# 창을 닫기(픽스처 정리) 전에 가짜 트레이·감시를 되돌린다 — 가짜를 단 채 닫으면 다음 창 테스트가 흔들림
def test_once_per_run_even_if_seen_before(window, monkeypatch):  # noqa: F811
    w, _ = window
    with monkeypatch.context() as mp:
        config.save_general_flag("nonKoreanNoticeShown", True)  # 0.52.2 안내를 본 사용자 — 그래도 새 경고는 뜬다
        tray = Tray()
        mp.setattr(w, "_tray", tray)
        _foreground(mp, w, "마비노기")
        assert not w._check_overseas_client() and w.home_page.notice_box.isHidden()  # 한국 — 없음
        _foreground(mp, w, "mabinogi_2026_11_18_123456.jpg - 꿀뷰", exe="")  # 등록 실행파일 없음 + 스크린샷 창
        assert not w._check_overseas_client() and w.home_page.notice_box.isHidden()
        _foreground(mp, w, "Mabinogi", active=False)
        assert not w._check_overseas_client()  # 게임이 앞에 없으면 판단 안 함
        _foreground(mp, w, "Mabinogi")
        assert w._check_overseas_client()
        assert not w.home_page.notice_box.isHidden()
        assert w.home_page.notice_ko.text() == w.OVERSEAS_KO and w.home_page.notice_en.text() == w.OVERSEAS_EN
        assert tray.messages == [(w.OVERSEAS_TRAY_TITLE, w.OVERSEAS_TRAY)]
        assert not w._check_overseas_client() and len(tray.messages) == 1  # 이 실행에서는 1번만
        w.home_page.notice_close.click()
        assert w.home_page.notice_box.isHidden()


def test_shows_again_on_next_run(window, monkeypatch):  # noqa: F811
    """앱을 다시 켜면(새 창) 또 뜬다 — 본 기록을 남기지 않음."""
    w, _ = window
    with monkeypatch.context() as mp:
        config.save_general_flag("nonKoreanNoticeShown", True)
        tray = Tray()
        mp.setattr(w, "_tray", tray)
        _foreground(mp, w, "Mabinogi")
        assert w._check_overseas_client() and len(tray.messages) == 1
        raw = config._read_local_config()
        assert raw["general"]["nonKoreanNoticeShown"] is True  # 예전 값은 그대로 두고 읽지 않음
        w._overseas_done = False  # 새 실행 = 새 창(이 값은 창마다 처음 False)
        assert w._check_overseas_client() and len(tray.messages) == 2


def test_features_keep_running_on_overseas_client(window, monkeypatch):  # noqa: F811
    """차단 없음 — 경고 뒤에도 게임 활성 판단·추적은 그대로."""
    w, _ = window
    with monkeypatch.context() as mp:
        mp.setattr(w, "_tray", Tray())
        _foreground(mp, w, "Mabinogi")
        w._check_overseas_client()
        assert w._watcher.is_game_active() and not w._paused


def test_old_notice_record_still_not_synced():
    """예전 0.52.2가 남긴 general.nonKoreanNoticeShown은 동기화에 올리지 않는다(값은 그대로 둠)."""
    config.save_general_flag("nonKoreanNoticeShown", True)
    raw = config._read_local_config()
    assert "nonKoreanNoticeShown" not in cloud_sync.strip_for_sync(raw).get("general", {})
