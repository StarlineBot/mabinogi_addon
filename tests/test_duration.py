from mabinogi_addon.duration import format_duration


def test_days():
    assert format_duration(5 * 86400 + 100) == "5d"
    assert format_duration(86400) == "1d"


def test_hours():
    assert format_duration(3600 + 46 * 60 + 59) == "1h46m"
    assert format_duration(2 * 3600) == "2h0m"


def test_minutes():
    assert format_duration(3 * 60 + 28) == "3:28"
    assert format_duration(60) == "1:00"


def test_seconds():
    assert format_duration(28) == "28s"
    assert format_duration(0) == "0s"
    assert format_duration(-5) == "0s"  # 음수는 0
