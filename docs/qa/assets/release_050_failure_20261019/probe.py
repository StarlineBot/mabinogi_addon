"""Distinguish test preparation failures from public policy regressions."""

from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from scripts.qa_tuarim_low_range_display import pipeline, sample, hundred  # noqa: E402,F401
from mabinogi_addon import config, feature_access, image_io  # noqa: E402
from mabinogi_addon.ui.main_window import MainWindow  # noqa: E402


@pytest.mark.parametrize("skip", [False, True])
def test_anonymous_guide_and_normal_app_have_distinct_dialogue_policy(monkeypatch, skip):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    config.save_general_flag("skipSetup", skip)
    w = MainWindow()
    w._post_show_done = True
    w.show()
    for timer in w.findChildren(QTimer):
        timer.stop()
    app.processEvents()
    w.creator_dialogue.visibility = lambda *args: True
    try:
        assert (w._pages.currentWidget() is w._tabs) is skip
        assert w.creator_dialogue.request() is skip
        assert w.creator_dialogue.bubble.isVisible() is skip
    finally:
        w._force_quit = True
        w.close()
        app.processEvents()


@pytest.mark.parametrize("case,expected", [("16", 16), ("19", 19), ("100", None)])
def test_same_reader_pipeline_works_after_creator_opt_in(pipeline, monkeypatch, case, expected):
    pump, d = pipeline
    image = sample("v06_7466.png") if case == "16" else hundred()
    if case == "19":
        source = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-18 124011.png")
        assert source is not None
        image = source[85:101, 1265:1307].copy()
    assert not d.percent_requested()
    assert d._percent_control.isHidden()
    with pytest.raises(AssertionError):
        pump(image)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": feature_access.CREATOR_DISCORD_ID})
    d._apply_gate()
    d._percent_control.setChecked(True)
    assert d.percent_requested()
    result = pump(image)
    assert result["overlay"] == expected
    if expected is None:
        assert "--%" in result["label"]
    else:
        assert result["raw"] == result["stable"] == expected
