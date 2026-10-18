"""Keep the independent null-section reproduction in the regression suite."""

from scripts.qa_common_resource_null_section_20261018 import (
    common, window, runtime,
    test_common_registration_recovers_a_null_section,
    test_common_clear_can_remove_the_other_registered_source,
)

from copy import deepcopy
import pytest
from PySide6.QtWidgets import QMessageBox
from mabinogi_addon import config
from mabinogi_addon.ui import region_registration as reg


@pytest.mark.parametrize("key", ["dorcha", "tuarim"])
@pytest.mark.parametrize("value", ["missing", None, [], "broken", 42])
def test_registration_then_clear_recovers_malformed_sections(common, monkeypatch, key, value):
    _, view, *_ = common
    raw = config._read_local_config()
    other = "tuarim" if key == "dorcha" else "dorcha"
    saved_other = deepcopy(raw.get(other))
    if value == "missing":
        raw.pop(key, None)
    else:
        raw[key] = value
    config._write_local_config(raw)
    view._controllers()[key]._region = None
    applied = view.find_regions(keys=(key,))
    assert set(applied) == {key}
    assert config._read_local_config()[key]["box"]
    assert config._read_local_config().get(other) == saved_other
    # Clear must also normalize a malformed section while clearing its healthy peer.
    raw = config._read_local_config()
    raw[key] = value if value != "missing" else None
    config._write_local_config(raw)
    monkeypatch.setattr(reg, "confirm_clear", lambda *args: QMessageBox.StandardButton.Yes)
    view._clear_regions()
    assert all(config._read_local_config()[name]["box"] is None for name in (key, other))
