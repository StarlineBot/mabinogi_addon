"""기본(번들) 항목 '지움' 기록(removedDefaults) 테스트."""

from mabinogi_addon import config


def test_add_and_load_removed(tmp_path):
    p = tmp_path / "config.local.json"
    assert config.load_removed_defaults("buffTracker", p) == set()

    config.add_removed_default("snow_storm", "buffTracker", p)
    config.add_removed_default("star", "buffTracker", p)
    assert config.load_removed_defaults("buffTracker", p) == {"snow_storm", "star"}
    # 중복 추가는 멱등
    config.add_removed_default("star", "buffTracker", p)
    assert config.load_removed_defaults("buffTracker", p) == {"snow_storm", "star"}


def test_sections_are_independent(tmp_path):
    p = tmp_path / "config.local.json"
    config.add_removed_default("vivace", "buffTracker", p)
    config.add_removed_default("모모", "debuffTracker", p)
    assert config.load_removed_defaults("buffTracker", p) == {"vivace"}
    assert config.load_removed_defaults("debuffTracker", p) == {"모모"}


def test_removed_does_not_clobber_other_keys(tmp_path):
    p = tmp_path / "config.local.json"
    config.save_capture_region(1, 2, 3, 4, "buffTracker", p)
    config.add_removed_default("star", "buffTracker", p)
    # 같은 섹션의 captureRegion이 보존돼야 함
    assert config.load_capture_region("buffTracker", p) == {"x": 1, "y": 2, "w": 3, "h": 4}
    assert config.load_removed_defaults("buffTracker", p) == {"star"}


def test_export_import_excludes_secrets(tmp_path):
    from mabinogi_addon import config

    cfg = tmp_path / "config.local.json"
    config._write_local_config(  # 설정 + 비밀값
        {"partyKeywords": ["브리"],
         "nexonApiKey": "SECRET", "inquiryWebhookUrl": "https://hook"},
        cfg,
    )
    out = tmp_path / "export.json"
    config.export_config(out, cfg)
    import json
    exported = json.loads(out.read_text(encoding="utf-8"))
    assert "nexonApiKey" not in exported and "inquiryWebhookUrl" not in exported
    assert exported["partyKeywords"] == ["브리"]


def test_import_merges_and_keeps_secrets(tmp_path):
    import json

    from mabinogi_addon import config

    cfg = tmp_path / "config.local.json"
    config._write_local_config({"nexonApiKey": "KEEP", "partyKeywords": ["old"]}, cfg)
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"partyKeywords": ["new"], "nexonApiKey": "X"}), encoding="utf-8")
    config.import_config(src, cfg)
    data = config._read_local_config(cfg)
    assert data["partyKeywords"] == ["new"]  # 가져온 값 반영
    assert data["nexonApiKey"] == "KEEP"  # 비밀값은 기존 유지


def test_import_rejects_non_dict(tmp_path):
    import pytest

    from mabinogi_addon import config

    bad = tmp_path / "bad.json"
    bad.write_text("[1,2,3]", encoding="utf-8")
    with pytest.raises(ValueError):
        config.import_config(bad, tmp_path / "config.local.json")
