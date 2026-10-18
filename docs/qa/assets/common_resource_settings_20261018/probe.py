"""Actual image/model through shared approval and coordinate persistence."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_resource_common_settings import common, window  # noqa: E402,F401
from test_resource_integration import runtime  # noqa: E402,F401
from mabinogi_addon import config, image_io  # noqa: E402
from mabinogi_addon.detect import resource_pair  # noqa: E402
from mabinogi_addon.detect.dorcha_reader import read_dorcha  # noqa: E402
from mabinogi_addon.detect.tuarim_reader import read_percent  # noqa: E402
from mabinogi_addon.ui import resource_tab  # noqa: E402

REAL_LOCATE = resource_pair.locate_resources


@pytest.mark.parametrize("partial", [False, True])
def test_real_input_and_detectors_reach_shared_approval(common, monkeypatch, partial):
    w, view, _, approvals, _ = common
    source = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-18 124011.png")
    assert source is not None
    panel = source[34:109, 1225:1332].copy()
    if partial:
        panel[39:52, 53:80] = 0
    monkeypatch.setattr(resource_pair, "locate_resources", REAL_LOCATE)
    monkeypatch.setattr(resource_tab, "capture_for_autofind", lambda **kwargs: (panel, -300, 40))
    before = deepcopy(config._read_local_config())
    applied = view.find_regions()
    expected = {"dorcha": (-286, 63, 28, 23)}
    if not partial:
        expected["tuarim"] = (-260, 91, 42, 16)
    assert applied == expected and len(approvals) == 1
    wanted = deepcopy(before)
    for key, box in expected.items():
        wanted.setdefault(key, {})["box"] = dict(zip(("x", "y", "w", "h"), box))
        assert view._controllers()[key]._region == wanted[key]["box"]
    assert config._read_local_config() == wanted
    assert read_dorcha(panel[23:46, 14:42]) == 7
    if not partial:
        assert read_percent(panel[51:67, 40:82]) == 19
