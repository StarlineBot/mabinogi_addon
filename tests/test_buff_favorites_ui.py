"""버프 즐겨찾기 칸 읽기 화면(기획서 3.1.1).

0.33.0 명세 변경(2026-10-31 사용자 결정 — 전체 공개): 0.26.0의 '버프 읽는 영역 · 알파(제작자)' 선택과 buffFavoritesMode를 없애고
모든 사용자가 구분선 위·아래를 함께 읽는다. 선택·제작자 전환 테스트는 '선택이 없고 항상 즐겨찾기 안내·인식 줄'로 바꿨다.
"""
from types import SimpleNamespace

from mabinogi_addon import config, feature_access
from mabinogi_addon.detect.favorites import FavoriteRow
from mabinogi_addon.ui.buff_tab import REGION_GUIDE
from test_navigation import window  # noqa: F401  (픽스처)


def test_no_read_mode_choice_and_favorites_guide_for_everyone(window, monkeypatch):
    w = window[0]
    tab = w.buff_tab
    monkeypatch.setattr(config, "load_discord_user", lambda *a: {"id": "ordinary"})  # 제작자가 아니어도
    assert not hasattr(tab, "read_mode_box") and not hasattr(tab, "favorites_mode")
    assert not hasattr(feature_access, "buff_favorites_mode")
    assert tab.region_guide.text() == REGION_GUIDE and "즐겨찾기 칸 포함" in REGION_GUIDE
    assert tab.favorites_info.isVisibleTo(tab)


def test_tracking_always_reads_favorites_with_saved_separator(window, monkeypatch):
    from mabinogi_addon.ui import main_window
    from mabinogi_addon.ui.buff_controller import BuffController
    w = window[0]
    monkeypatch.setattr(main_window, "create_live_source", lambda *a, **k: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(BuffController, "start", lambda self, *a, **k: None)
    monkeypatch.setattr(BuffController, "stop", lambda self, *a, **k: None)
    raw = config._read_local_config()
    raw.setdefault("buffTracker", {}).update(enabled=True, captureRegion={"x": 10, "y": 20, "w": 300, "h": 900})
    raw.setdefault("general", {}).setdefault("setupSelection", {})["buff"] = True
    config._write_local_config(raw)
    config.save_favorites_separator(180)
    w._start_buff_tracking()
    reader = w._engine.favorites
    assert reader is not None and reader.separator == 180  # 첫 프레임부터 지난 실행의 구분선
    reader.separator = 196  # 실행 중 선이 옮겨지면 상태 폴링이 저장
    w._remember_favorites_separator()
    assert config.load_favorites_separator() == 196
    config.save_capture_region(10, 30, 300, 900)  # 영역을 다시 지정하면 저장한 선은 무효
    assert config.load_favorites_separator() is None
    w.buff_controller = None
    w._engine = None


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


def test_top_edge_picker_asks_for_panel_top_by_default(window):
    from mabinogi_addon.ui.top_edge_selector import TopEdgeSelector
    assert TopEdgeSelector(0, 300, 100)._favorites is True  # 첫 안내 자동설정도 상태목록창 맨 위
