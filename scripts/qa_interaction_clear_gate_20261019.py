"""Reproduce the stale clear-button fixture that blocks the release regression gate."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_navigation import window  # noqa: E402,F401
from test_resource_integration import runtime  # noqa: E402,F401
from test_resource_common_settings import common  # noqa: E402,F401
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402
from mabinogi_addon import config  # noqa: E402
from mabinogi_addon.ui import region_registration as registration  # noqa: E402


def test_existing_fixture_clear_must_cancel_pending_detection(common, monkeypatch):
    w, view, _, approvals, _ = common
    raw = config._read_local_config()
    raw.setdefault("dorcha", {})["box"] = dict(w.dorcha_tab._region)
    config._write_local_config(raw)
    assert w.dorcha_tab._region is not None
    assert not w.dorcha_tab.clear_region_btn.isEnabled(), "Expected the current stale fixture state"
    monkeypatch.setattr(registration, "confirm_clear", lambda *args: QMessageBox.StandardButton.Yes)
    QTimer.singleShot(0, w.dorcha_tab.clear_region_btn.click)
    result = view.find_regions()
    assert result == {}, (
        "Release regression gate: fixture assigns _region without the registration UI refresh; "
        "disabled QPushButton.click() emits nothing, so cancellation never occurs. "
        f"Observed applied regions: {result}; approvals: {approvals}"
    )
