"""문의 일원화(문의 자동 진단 명세 6.2·6.3): 회차·상한·ZIP 1개·보낸 사람/회차 ID·새 창 흐름·탭 수집 구역 제작자 전용."""
from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime
from types import SimpleNamespace as NS

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon import inquiry_session as inq
from test_navigation import window  # noqa: F401  (창 픽스처)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _frame(value, h=37, w=200):
    rng = np.random.default_rng(value)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


# ---- 카드·분류 -----------------------------------------------------------------------------
def test_six_cards_and_categories():
    assert inq.CATEGORIES == ("문제 신고", "기능 요청", "기타")  # 6.3 4항: 버그 → 문제 신고
    assert [c.title for c in inq.CARDS] == ["보스 체력바 · 패턴 알림", "내 체력바", "도르카 · 투아림 숫자",
                                            "버프 · 디버프", "자동 찾기 · 영역 지정", "그 밖의 문제 · 잘 모르겠어요"]
    modes = {c.key: c.mode for c in inq.CARDS}
    assert modes == {"boss": "collect", "stat": "collect", "dorcha": "collect", "buff": "snapshot",
                     "autofind": "autofind", "other": "game"}


# ---- 수집 상한·변경 프레임 ------------------------------------------------------------------
def test_add_frame_keeps_only_changed_frames_once_per_second(tmp_path):
    s = inq.Session(inq.CARD_BY_KEY["boss"], root=tmp_path)
    a = _frame(1)
    assert s.add_frame("boss", a, now=0.0) is not None
    assert s.add_frame("boss", _frame(2), now=0.5) is None       # 1초 안
    assert s.add_frame("boss", a.copy(), now=2.0) is None         # 바뀌지 않음
    item = s.add_frame("boss", _frame(3), now=3.0)
    assert item is not None and item.label == "보스 HP바 2" and item.path.exists()


def test_limits_twenty_frames(tmp_path):
    s = inq.Session(inq.CARD_BY_KEY["boss"], root=tmp_path)
    for i in range(30):
        s.add_frame("boss", _frame(i), now=float(i * 2))
    assert len(s.images) == inq.LIMIT_FRAMES and s.full()


def test_removed_items_are_deleted_and_not_reattached(tmp_path):
    s = inq.Session(inq.CARD_BY_KEY["other"], root=tmp_path)
    item = s.add_frame("game", _frame(1), force=True)
    s.remove(item)
    assert not item.path.exists() and s.attachments == [] and item.name in s.removed


# ---- 보낸 사람·회차 ID·ZIP ------------------------------------------------------------------
def test_install_id_is_stable_and_guest_label(monkeypatch):
    config._write_local_config({})
    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: None)
    first = inq.install_id()
    assert inq.install_id() == first and len(first) == 32
    who = inq.sender()
    assert who["label"] == f"guest-{first[:8]}" and who["discord_id"] is None
    who = inq.sender({"id": "42", "name": "레몬"})
    assert who["label"] == "레몬" and who["discord_id"] == "42" and who["install_id"] == first


def test_zip_has_info_body_logs_and_images(tmp_path):
    s = inq.Session(inq.CARD_BY_KEY["boss"], root=tmp_path)
    s.started = datetime(2026, 11, 5, 21, 40)
    s.ended = datetime(2026, 11, 5, 21, 41)
    for i in range(3):
        s.add_frame("boss", _frame(i), now=float(i * 2))
    s.notes.append("체력바 영역 미설정")
    who = {"discord_id": None, "discord_name": None, "install_id": "3f9a2c1e" + "0" * 24, "label": "guest-3f9a2c1e"}
    name, data = s.build_zip(category="문제 신고", who=who, title="보스 문제", content="70%에서 늦게 알림",
                             logs="최근 로그", when=datetime(2026, 11, 5, 21, 42))
    assert name == f"문의_20261105-2142_guest-3f9a2c1e_{s.id[:6]}.zip"
    archive = zipfile.ZipFile(io.BytesIO(data))
    names = set(archive.namelist())
    assert {"info.json", "본문.txt", "logs.txt", "boss_01.png", "boss_02.png", "boss_03.png"} <= names
    info = json.loads(archive.read("info.json"))
    assert info["session_id"] == s.id and info["install_id"] == who["install_id"] and info["card"] == "boss"
    assert info["category"] == "문제 신고" and len(info["attachments"]) == 3 and "체력바 영역 미설정" in info["notes"]
    assert info["collect_started"] == "2026-11-05T21:40:00"
    body = archive.read("본문.txt").decode()
    assert body.splitlines()[0] == f"guest-3f9a2c1e · 회차 {s.id[:6]} · 문제 신고 · 보스 체력바 · 패턴 알림"


def test_zip_name_replaces_unsafe_characters():
    who = {"label": 'a/b:c*?"<>|'}
    assert inq.zip_name(who, "abcdef123", datetime(2026, 1, 2, 3, 4)) == "문의_20260102-0304_a_b_c_______abcdef.zip"


def test_cleanup_stale_only_old_session_folders(tmp_path):
    old = tmp_path / ("a" * 32)
    new = tmp_path / ("b" * 32)
    other = tmp_path / "boss_collect"
    for d in (old, new, other):
        d.mkdir()
    os.utime(old, (0, 0))
    os.utime(other, (0, 0))
    assert inq.cleanup_stale(tmp_path, now=10 ** 9) == 1
    assert not old.exists() and new.exists() and other.exists()


# ---- 전송 형식 -----------------------------------------------------------------------------
def test_send_inquiry_attaches_zip_with_header_line():
    from mabinogi_addon.inquiry import send_inquiry
    captured = {}

    class Resp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        captured.update(data=req.data, timeout=timeout)
        return Resp()
    send_inquiry("https://x", "보스 문제", "내용", category="문제 신고", header="guest-1 · 회차 abc123 · 문제 신고 · 보스",
                 attachment=("문의_x.zip", b"PK\x03\x04zip", "application/zip"), timeout=60, urlopen=fake)
    body = captured["data"]
    assert b"application/zip" in body and b"PK\x03\x04zip" in body and captured["timeout"] == 60
    payload = json.loads(body.split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0])
    assert payload["content"].startswith("guest-1 · 회차 abc123 · 문제 신고 · 보스\n내용")
    assert payload["thread_name"] == "[문제 신고] 보스 문제"


# ---- 새 창 흐름 ----------------------------------------------------------------------------
def test_window_kind_page_and_cards(app, monkeypatch):
    from mabinogi_addon.ui.inquiry_window import InquiryWindow
    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: None)
    w = InquiryWindow()
    try:
        assert (w.width(), w.height()) == (790, 800)
        assert w.category == "문제 신고" and not w.next_btn.isEnabled()  # 카드를 고르기 전에는 시작 안 함
        assert len(w.card_buttons) == 6
        w.card_buttons["other"].click()
        assert w.next_btn.isEnabled() and w.next_btn.text() == "자료 모으기 시작"
        w.kind.buttons["기능 요청"].click()
        assert w.text_box.isVisibleTo(w) and not w.bug_box.isVisibleTo(w) and w.next_btn.text() == "보내기"
        assert "문의 종류" in w.steps.text() and "자료 모으기" not in w.steps.text()
    finally:
        w.shutdown()
        w.deleteLater()


def test_without_data_goes_to_confirm_and_sends_zip_with_same_session_on_retry(app, monkeypatch, tmp_path):
    from mabinogi_addon.ui import inquiry_window as iw
    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: {"id": "7", "name": "테스터"})
    monkeypatch.setattr(config, "get_inquiry_webhook_url", lambda: "https://hook")
    sent = []

    def fake_send(webhook, title, body, **kw):
        sent.append(kw)
        if len(sent) == 1:
            raise RuntimeError("웹훅 응답 코드 500")
    monkeypatch.setattr("mabinogi_addon.inquiry.send_inquiry", fake_send)
    w = iw.InquiryWindow()
    try:
        w.card_buttons["buff"].click()
        w._without_data()
        assert w.stack.currentWidget() is w.page_confirm and w.title_edit.text() == "버프 · 디버프 문제"
        w.body_edit.setPlainText("버프 시간이 틀려요")
        sid = w.session.id
        w._next()
        w._executor.submit(lambda: None).result(timeout=5)
        app.processEvents()
        assert w.next_btn.text() == "다시 보내기" and "보내지 못했어요" in w.status.text()
        w._next()
        w._executor.submit(lambda: None).result(timeout=5)
        app.processEvents()
        assert len(sent) == 2
        for kw in sent:
            name = kw["attachment"][0]
            assert name.endswith(f"_{sid[:6]}.zip") and "테스터" in name  # 다시 보내기 = 같은 회차 ID
            assert kw["header"].startswith(f"테스터 · 회차 {sid[:6]} · 문제 신고 · 버프 · 디버프")
            assert kw["user_id"] == "7"
    finally:
        w.shutdown()
        w.deleteLater()


def test_collect_card_gathers_region_frames_and_finishes(app, monkeypatch):
    from mabinogi_addon.ui import inquiry_window as iw
    monkeypatch.setattr(inq, "region_of", lambda name: {"x": 0, "y": 0, "w": 200, "h": 37} if name == "boss" else None)
    counter = iter(range(1000))
    monkeypatch.setattr(inq, "grab_physical", lambda rect: _frame(next(counter)))
    w = iw.InquiryWindow(watcher=NS(is_game_active=lambda: True))
    try:
        w.card_buttons["boss"].click()
        w._next()  # 자료 모으기 시작
        assert w._collecting and w.stack.currentWidget() is w.page_collect
        for _ in range(5):
            w._next_grab = 0.0
            w._last_tick = None
            w._tick()
            w._executor.submit(lambda: None).result(timeout=5)
            app.processEvents()
        assert len(w.session.images) == 1 or len(w.session.images) >= 1  # 같은 초 안이라 1장 이상
        w.stop_keep.click()  # 여기까지 모으기
        assert not w._collecting and w.stack.currentWidget() is w.page_confirm
        assert w.title_edit.text() == "보스 체력바 · 패턴 알림 문제"
        assert w.thumb_grid.count() == len(w.session.attachments) >= 1
    finally:
        w.shutdown()
        w.deleteLater()


def test_game_one_shot_never_falls_back_to_desktop(app, monkeypatch):
    """그 밖의 문제: 게임이 없으면 이미지 없이(바탕화면 대체 금지 — strict)."""
    from mabinogi_addon.ui import inquiry_window as iw
    from mabinogi_addon.ui import screen_grab
    calls = []
    monkeypatch.setattr(screen_grab, "capture_for_autofind", lambda **kw: calls.append(kw) or (None, 0, 0))
    w = iw.InquiryWindow(watcher=NS(is_game_active=lambda: True))
    try:
        w.card_buttons["other"].click()
        w._next()
        assert w._pending
        w._countdown = 0
        w._last_tick = None
        w._tick()
        assert calls == [{"require_game": True, "strict_game": True}]
        assert w.stack.currentWidget() is w.page_confirm and w.session.images == []
        assert any("게임 화면을 찾지 못했어요" in n for n in w.session.notes)
    finally:
        w.shutdown()
        w.deleteLater()


def test_cancel_and_close_clean_up_session_folder(app, tmp_path):
    from mabinogi_addon.ui import inquiry_window as iw
    w = iw.InquiryWindow()
    w.card_buttons["boss"].click()
    w._without_data()
    folder = w.session.folder
    assert folder.exists()
    w.close()
    assert not folder.exists() and not w.chip.isVisible()


def test_progress_chip_is_overlay_click_through():
    from mabinogi_addon.ui import overlay_capture
    from mabinogi_addon.ui.inquiry_window import InquiryChip
    assert "InquiryChip" in overlay_capture.OVERLAYS
    from PySide6.QtCore import Qt
    QApplication.instance() or QApplication([])
    chip = InquiryChip()
    try:
        assert chip.windowFlags() & Qt.WindowType.WindowTransparentForInput
        assert chip.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    finally:
        chip.deleteLater()


# ---- 탭 수집·진단 구역: 제작자만 ------------------------------------------------------------
@pytest.mark.parametrize("creator", [False, True])
def test_diagnostic_sections_are_creator_only(window, monkeypatch, creator):
    from mabinogi_addon import feature_access
    w, app = window
    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: {"id": "regular", "name": "일반"})
    monkeypatch.setattr(feature_access, "is_creator", lambda: creator)
    w.boss_tab._apply_collect_gate()
    w.stat_bars_tab._apply_login_gate()
    w.tuarim_tab._apply_collect_gate()
    w.settings_tab._refresh_diag()
    assert w.boss_tab.diagnostics_btn.isVisibleTo(w.boss_tab) is creator
    assert w.stat_bars_tab.diagnostics_btn.isVisibleTo(w.stat_bars_tab) is creator
    assert w.resource_tab.diagnostics_btn.isVisibleTo(w.resource_tab) is creator
    assert w.settings_tab.diagnostics_toggle.isVisibleTo(w.settings_tab) is creator
    assert w.stat_bars_tab.collect_chk.isEnabled() is creator
