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
