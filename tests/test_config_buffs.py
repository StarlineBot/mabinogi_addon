from mabinogi_addon.config import (
    AlertConfig,
    BuffSettings,
    load_buff_settings,
    load_memo,
    load_overlay_scales,
    load_overlay_state,
    save_buff_settings,
    save_memo,
    save_overlay_scales,
    save_overlay_state,
)


def test_overlay_scales_round_trip(tmp_path):
    path = tmp_path / "config.local.json"
    assert load_overlay_scales(path) == (150, 100)  # 기본값
    save_overlay_scales(200, 120, path)
    assert load_overlay_scales(path) == (200, 120)


def test_game_exe_round_trip(tmp_path):
    from mabinogi_addon.config import load_game_exe, save_game_exe

    path = tmp_path / "config.local.json"
    assert load_game_exe(path) is None
    save_game_exe("Client.exe", path)
    assert load_game_exe(path) == "client.exe"  # 소문자 정규화


def test_memo_round_trip(tmp_path):
    path = tmp_path / "config.local.json"
    assert load_memo(path) == {}
    save_memo("메모\n내용", True, 20, path)
    assert load_memo(path) == {"text": "메모\n내용", "locked": True, "fontSize": 20}


def test_overlay_state_round_trip(tmp_path):
    path = tmp_path / "config.local.json"
    assert load_overlay_state("buffTracker", path) is None
    save_overlay_state(321, 654, True, "buffTracker", path)
    assert load_overlay_state("buffTracker", path) == {
        "x": 321,
        "y": 654,
        "locked": True,
    }


def test_round_trip(tmp_path):
    path = tmp_path / "config.local.json"
    items = [
        BuffSettings(id="vivace", show_duration=True),
        BuffSettings(
            id="magic_speed",
            show_duration=False,
            hidden=True,
            alert=AlertConfig(enabled=False, before_sec=10, blink=False, sound=False),
        ),
    ]
    save_buff_settings(items, path)
    loaded = load_buff_settings(path)

    assert [s.id for s in loaded] == ["vivace", "magic_speed"]  # 순서 보존
    assert loaded[1].hidden is True
    assert loaded[1].show_duration is False
    assert loaded[1].alert.before_sec == 10
    assert loaded[1].alert.enabled is False


def test_defaults_for_missing_fields(tmp_path):
    path = tmp_path / "config.local.json"
    path.write_text('{"buffTracker": {"buffs": [{"id": "x"}]}}', encoding="utf-8")
    loaded = load_buff_settings(path)
    assert loaded[0].id == "x"
    # 기본값: 오버레이 표시만 ON, 지속시간·종료알림은 OFF
    assert loaded[0].hidden is False
    assert loaded[0].show_duration is False
    assert loaded[0].alert.enabled is False
    assert loaded[0].alert.before_sec == 30


def test_missing_file_is_empty(tmp_path):
    assert load_buff_settings(tmp_path / "nope.json") == []


def test_save_preserves_other_sections(tmp_path):
    path = tmp_path / "config.local.json"
    path.write_text('{"party": {"keywords": ["글렌"]}}', encoding="utf-8")
    save_buff_settings([BuffSettings(id="vivace")], path)
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["party"]["keywords"] == ["글렌"]  # 다른 섹션 보존
    assert data["buffTracker"]["buffs"][0]["id"] == "vivace"
