"""버프 읽는 영역 선택(0.26.0, 사용자 결정 2026-10-28): 즐겨찾기 영역은 제작자 알파, 기본은 지금 목록 방식."""
from types import SimpleNamespace

from mabinogi_addon import config, feature_access
from mabinogi_addon.detect.favorites import FavoriteRow
from mabinogi_addon.ui.buff_tab import REGION_GUIDE, REGION_GUIDE_FAVORITES
from test_navigation import window  # noqa: F401  (픽스처)


def _creator(monkeypatch, tab, on=True):
    user = {"id": feature_access.CREATOR_DISCORD_ID} if on else {"id": "ordinary"}
    monkeypatch.setattr(config, "load_discord_user", lambda *a: user)
    tab.refresh_read_mode(recheck=True)


def test_read_mode_is_creator_only_and_defaults_to_list(window, monkeypatch):
    tab = window[0].buff_tab
    _creator(monkeypatch, tab, on=False)
    assert tab.read_mode_box.isHidden() and not tab.favorites_mode()
    assert tab.region_guide.text() == REGION_GUIDE and tab.favorites_info.isHidden()
    _creator(monkeypatch, tab)
    assert not tab.read_mode_box.isHidden()
    assert tab.read_list_radio.isChecked() and not tab.favorites_mode()  # 기본: 비즐겨찾기 영역(지금 방식)


def test_choosing_favorites_saves_and_restarts_tracking(window, monkeypatch):
    w = window[0]
    tab = w.buff_tab
    _creator(monkeypatch, tab)
    restarts = []
    monkeypatch.setattr(w, "_start_buff_tracking", lambda: restarts.append(tab.favorites_mode()))
    w.buff_controller = object()  # 추적 중일 때만 다시 건다(_on_catalog_changed)
    try:
        tab.read_favorites_radio.setChecked(True)
        assert config.load_general_flag("buffFavoritesMode") and tab.favorites_mode() and restarts == [True]
        assert tab.region_guide.text() == REGION_GUIDE_FAVORITES and not tab.favorites_info.isHidden()
        _creator(monkeypatch, tab, on=False)  # 로그아웃하면 저장값이 있어도 지금 방식으로
        w._buff_read_mode_login_changed()
        assert not tab.favorites_mode() and tab.read_mode_box.isHidden()
    finally:
        w.buff_controller = None
        config.save_general_flag("buffFavoritesMode", False)


def test_recognition_line_and_lost_status(window, monkeypatch):
    w = window[0]
    reader = SimpleNamespace(separator=None, rows={}, on={}, row_count=0, lost=False)
    w._engine = SimpleNamespace(favorites=reader, anchor_seen=True)
    try:
        assert w._favorites_info()[0] == "즐겨찾기 칸 없음 — 구분선이 없으면 전체를 목록으로 읽어요"
        reader.separator, reader.row_count = 200, 7
        reader.rows = {"premium_battle": FavoriteRow("premium_battle", 4, 30, 16),
                       "vivace": FavoriteRow("vivace", 4, 6, 16)}
        reader.on = {"premium_battle": True}
        text = w._favorites_info()[0]
        assert text.startswith("즐겨찾기 칸 7줄 · 등록한 버프 2개: ")
        assert text.index("(꺼짐)") < text.index("(켜짐)")  # 위 줄부터
        assert text.endswith(" — 구분선 아래는 목록으로 읽어요")
        reader.lost = True
        monkeypatch.setattr(config, "load_capture_region", lambda *a: {"x": 0, "y": 0, "w": 10, "h": 10})
        monkeypatch.setattr(w._watcher, "is_game_active", lambda: True)
        w.buff_controller = SimpleNamespace(item_count=0)
        assert w._buff_status()[0] == "즐겨찾기 칸을 찾지 못했어요 · 영역을 다시 지정해 주세요"
    finally:
        w._engine = None
        w.buff_controller = None


def test_top_edge_picker_wording_follows_read_mode(window):
    from mabinogi_addon.ui.top_edge_selector import TopEdgeSelector
    assert TopEdgeSelector(0, 300, 100)._favorites is False
    assert TopEdgeSelector(0, 300, 100, favorites=True)._favorites is True
