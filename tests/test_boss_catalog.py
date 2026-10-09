"""번들 보스 패턴 데이터 로더 (기획서 12.4)."""

from mabinogi_addon.tracker.boss_catalog import load_bosses, make_tracker


def test_loads_bundled_bosses():
    bosses = load_bosses()
    assert "lenen_miir" in bosses
    assert bosses["lenen_miir"].name == "레넨의 미이르"
    assert bosses["lenen_miir"].thresholds == (80, 40)
    assert bosses["lenen_miir_hoehan"].thresholds == (80, 65, 50, 35)
    assert bosses["gomok_petak"].thresholds == (85, 35)
    assert bosses["eotgallin_poinche"].name == "엇갈린 운명의 포인셰"
    assert bosses["eotgallin_poinche"].thresholds == (90, 75, 60, 40, 25, 15)


def test_make_tracker_fires():
    bosses = load_bosses()
    t = make_tracker(bosses["gomok_petak"])  # 85, 35
    t.observe(95)
    alerts = t.observe(89)  # 90(=85+5) 통과 → pre
    assert alerts and alerts[0].threshold == 85 and alerts[0].stage == "pre"
    assert alerts[0].text == "고목의 페타크 85% 진입 준비"
