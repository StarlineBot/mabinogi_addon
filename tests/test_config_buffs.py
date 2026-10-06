from mabinogi_addon.config import (
    AlertConfig,
    BuffSettings,
    load_buff_settings,
    save_buff_settings,
)


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
    assert loaded[0].show_duration is True
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
