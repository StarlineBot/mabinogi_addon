"""Fresh component instances verify policy independently of the repaired pipeline."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from mabinogi_addon import config, feature_access, image_io  # noqa: E402
from mabinogi_addon.ui.dorcha_tab import DorchaTab  # noqa: E402
from mabinogi_addon.ui.tuarim_tab import TuarimTab  # noqa: E402
from mabinogi_addon.ui.resource_tab import ResourceTab  # noqa: E402
from scripts.qa_tuarim_low_range_display import sample, hundred  # noqa: E402


@pytest.mark.parametrize("role", ["anonymous", "ordinary", "creator"])
@pytest.mark.parametrize("value", [16, 19, None])
def test_real_input_requires_explicit_creator_display_but_keeps_values(monkeypatch, role, value):
    app = QApplication.instance() or QApplication([])
    user = None if role == "anonymous" else {"id": (
        feature_access.CREATOR_DISCORD_ID if role == "creator" else "ordinary")}
    monkeypatch.setattr(config, "load_discord_user", lambda: user)
    image = sample("v06_7466.png") if value == 16 else hundred()
    if value == 19:
        source = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-18 124011.png")
        assert source is not None
        image = source[85:101, 1265:1307].copy()
    watcher = SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False)
    t, d = TuarimTab(watcher), DorchaTab(watcher)
    panel = ResourceTab(d, t)
    captures = []
    monkeypatch.setattr(t, "_grab_rect", lambda *args: captures.append(args) or image)
    monkeypatch.setattr(t, "_play", lambda *args: pytest.fail("Display must not enable alerts"))
    t._timer.stop()
    d._timer.stop()
    try:
        t.enable.setChecked(False)
        d.enable.setChecked(False)
        t._region = dict(x=0, y=0, w=image.shape[1], h=image.shape[0])
        assert d._alpha_ready and not panel.percent_chk.isChecked()
        assert config._read_local_config()["dorcha"]["tuarimAlphaReset"] == 1
        assert not d.percent_requested()
        if role != "creator":
            panel.percent_chk.setChecked(True)
            for _ in range(3):
                t._tick_enabled()
            assert not captures
            assert not d.percent_requested()
            assert panel.percent_chk.isHidden()
            assert d._overlay is None or not d._overlay.isVisible()
            user = {"id": feature_access.CREATOR_DISCORD_ID}
            d._apply_gate()
        panel.percent_chk.setChecked(True)
        assert d.percent_requested()
        for _ in range(3):
            t._tick_enabled()
        assert len(captures) == 3
        assert d._overlay is not None and d._overlay.isVisible()
        assert t._last_value == t._stable_value == d._overlay.percent == value
        if value is None:
            assert "--%" in d.value_label.text()
    finally:
        panel.shutdown()
        t.shutdown()
        d.shutdown()
        panel.close()
        panel.deleteLater()
        app.processEvents()
