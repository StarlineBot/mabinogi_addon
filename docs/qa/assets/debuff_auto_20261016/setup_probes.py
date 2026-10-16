"""Independent supplied-settings readiness matrix; run explicitly with pytest."""

from copy import deepcopy
from itertools import product

from mabinogi_addon import config, setup_state


def test_supplied_settings_matrix(monkeypatch):
    box = dict(x=-100, y=10, w=520, h=88)

    def unexpected_read(*args, **kwargs):
        raise AssertionError("must use supplied settings")

    monkeypatch.setattr(config, "_read_local_config", unexpected_read)
    combinations = product(
        ("missing", True, False, 0, 1, "false", None),
        ("off", "band", "percent", "bad"),
        (False, True),
        (False, True),
    )
    checked = 0
    for flag, legacy, roi, hp in combinations:
        general = {"debuffGateMode": legacy}
        if flag != "missing":
            general["debuffAutoGate"] = flag
        raw = {
            "general": general,
            "debuffTracker": {"enabled": True, "captureRegion": box if roi else None},
            "bossPattern": {"enabled": False, "box": box if hp else None},
        }
        before = deepcopy(raw)
        expected = [] if roi else ["debuff"]
        if flag is False and legacy == "percent" and not hp:
            expected.append("boss")
        assert setup_state.missing("debuff", raw) == expected, raw
        assert setup_state.pending(raw, automatic_only=True, feature_keys=("debuff",)) == expected, raw
        assert raw == before
        checked += 1
    assert checked == 112
