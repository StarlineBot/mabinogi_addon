"""해외(영문 제목) 마비노기 클라이언트 안내(사용자 결정 11-18) — 차단 없이 처음 볼 때 한 번 홈 띠 + 트레이 알림.

NA 클라이언트는 창 제목 'Mabinogi', 한국은 '마비노기'(실행파일은 둘 다 Client.exe라 제목으로만 구분)."""
import pytest
from test_navigation import window  # noqa: F401  (픽스처)

from mabinogi_addon import cloud_sync, config
from mabinogi_addon.system import overseas_guard as og
from mabinogi_addon.system.window_watcher import is_game_title, is_overseas_title


@pytest.mark.parametrize("title,overseas", [
    ("Mabinogi", True), ("MABINOGI", True), ("mabinogi - Client", True),
    ("마비노기", False), ("마비노기 Mabinogi", False), ("Mabinogi 마비노기", False),
    ("", False), (None, False), ("메모장", False),
])
def test_title_decision(title, overseas):
    assert is_overseas_title(title) is overseas


@pytest.mark.parametrize("title,exe,shown", [
    ("Mabinogi", "client.exe", True),               # NA 게임 창
    ("Mabinogi", "", True),                         # 실행파일을 못 읽으면 제목만(게임 판정과 같은 규칙)
    ("Mabinogi - Google Chrome", "chrome.exe", False),  # 브라우저 제외 목록은 게임이 아님 → 안내 없음
    ("Mabinogi wiki", "explorer.exe", False),
    ("마비노기", "client.exe", False),               # 한국 게임 창
])
def test_with_not_game_exclusions(title, exe, shown):
    assert (is_overseas_title(title) and is_game_title(title, exe)) is shown


class Tray:
    def __init__(self):
        self.messages = []

    def showMessage(self, title, body, *_):
        self.messages.append((title, body))


@pytest.fixture(autouse=True)
def _reset_guard():
    og.reset_for_tests()
    yield
    og.reset_for_tests()


def _windows(*rows):
    """창 목록(제목·창 클래스·pid — 프로세스는 열지 않음)을 가짜로 훑는다."""
    og.scan(lambda: list(rows))


# 창을 닫기(픽스처 정리) 전에 가짜 트레이를 되돌린다 — 가짜를 단 채 닫으면 다음 창 테스트가 흔들림
def test_overseas_client_notice_once(window, monkeypatch):  # noqa: F811
    w, _ = window
    with monkeypatch.context() as mp:
        tray = Tray()
        mp.setattr(w, "_tray", tray)
        _windows((103, "마비노기", "Mabinogi", 7777), (102, "Mabinogi - YouTube - Chrome", "Chrome_WidgetWin_1", 5555))
        assert not w._check_overseas_client() and w.home_page.notice_box.isHidden()  # 한국 + 'Mabinogi' 유튜브 탭 — 없음
        _windows((101, "Mabinogi", "Mabinogi", 4242))
        assert w._check_overseas_client()
        assert not w.home_page.notice_box.isHidden()
        assert w.home_page.notice_ko.text() == w.OVERSEAS_KO and w.home_page.notice_en.text() == w.OVERSEAS_EN
        assert "최적화·FPS·블랙박스" in w.OVERSEAS_KO and "(optimization, FPS, blackbox) are turned off" in w.OVERSEAS_EN
        assert tray.messages == [(w.OVERSEAS_TRAY_TITLE, w.OVERSEAS_TRAY)]
        assert len(w.OVERSEAS_TRAY) <= 255  # Windows 트레이 알림 본문 한도
        assert "껐어요" in w.OVERSEAS_TRAY and "turned off" in w.OVERSEAS_TRAY
        assert config.load_general_flag("nonKoreanNoticeShown") is True
        assert not w._check_overseas_client() and len(tray.messages) == 1  # 이 실행에서 다시 안 함
        w.home_page.notice_close.click()
        assert w.home_page.notice_box.isHidden()


def test_seen_before_no_notice_again(window, monkeypatch):  # noqa: F811
    w, _ = window
    with monkeypatch.context() as mp:
        config.save_general_flag("nonKoreanNoticeShown", True)  # 예전 실행에서 봄
        tray = Tray()
        mp.setattr(w, "_tray", tray)
        _windows((101, "Mabinogi", "Mabinogi", 4242))
        assert not w._check_overseas_client()
        assert w.home_page.notice_box.isHidden() and tray.messages == []
        assert og.active()  # 안내는 안 해도 보호(프로세스 안 열기)는 그대로


def test_screen_reading_keeps_running_on_overseas_client(window, monkeypatch):  # noqa: F811
    """판독은 그대로 — 안내 뒤에도 게임 활성 판단·추적(일시정지 아님)은 그대로."""
    w, _ = window
    with monkeypatch.context() as mp:
        mp.setattr(w, "_tray", Tray())
        _windows((101, "Mabinogi", "Mabinogi", 4242))
        w._check_overseas_client()
        assert w._watcher.is_game_active() and not w._paused


def test_notice_record_not_synced():
    config.save_general_flag("nonKoreanNoticeShown", True)
    raw = config._read_local_config()
    assert "nonKoreanNoticeShown" not in cloud_sync.strip_for_sync(raw).get("general", {})
    merged = cloud_sync.merge_incoming({"general": {"nonKoreanNoticeShown": False}}, raw, same_resolution=True)
    assert merged["general"]["nonKoreanNoticeShown"] is True  # 받을 때도 이 PC 값 그대로
    fresh = cloud_sync.merge_incoming({"general": {"nonKoreanNoticeShown": True}}, {}, same_resolution=True)
    assert "nonKoreanNoticeShown" not in fresh.get("general", {})  # 다른 PC에서 본 기록은 따라오지 않음
