"""A tolerated null section must not block common resource recovery commands."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest
from PySide6.QtWidgets import QMessageBox

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_resource_common_settings import common, window  # noqa: E402,F401
from test_resource_integration import runtime  # noqa: E402,F401
from mabinogi_addon import config  # noqa: E402
from mabinogi_addon.ui import region_registration as reg  # noqa: E402


@pytest.mark.parametrize("missing", [None, "dorcha", "tuarim"])
def test_common_registration_recovers_a_null_section(common, missing):
    w, view, _, approvals, notices = common
    raw = config._read_local_config()
    if missing is not None:
        raw[missing] = None
        config._write_local_config(raw)
        controller = view._controllers()[missing]
        controller._region = None
        if missing == "dorcha":
            controller._cfg["box"] = None
        # Existing readers already define a null section as unregistered.
        loader = config.load_dorcha if missing == "dorcha" else config.load_tuarim
        assert loader()["box"] is None
    applied = view.find_regions()
    assert len(approvals) == 1
    assert set(applied) == {"dorcha", "tuarim"}, (applied, notices)
    assert all(config._read_local_config()[key]["box"] for key in applied)


@pytest.mark.parametrize("missing", [None, "dorcha", "tuarim"])
def test_common_clear_can_remove_the_other_registered_source(common, monkeypatch, missing):
    _, view, *_ = common
    raw = config._read_local_config()
    for key, controller in view._controllers().items():
        raw.setdefault(key, {})["box"] = deepcopy(controller._region)
    if missing is not None:
        raw[missing] = None
    config._write_local_config(raw)
    if missing is not None:
        view._controllers()[missing]._region = None
    monkeypatch.setattr(reg, "confirm_clear", lambda *args: QMessageBox.StandardButton.Yes)
    view._clear_regions()
    other = "tuarim" if missing == "dorcha" else "dorcha"
    assert config._read_local_config()[other]["box"] is None
    assert all(c._region is None for c in view._controllers().values())
