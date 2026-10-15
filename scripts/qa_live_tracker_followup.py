"""Independent bounded-alert and revised startup-policy probes."""

from copy import deepcopy

import pytest

from mabinogi_addon import config, setup_state
from mabinogi_addon.tracker.buff_state import BuffStateMachine, Event
from mabinogi_addon.ui.main_window import MainWindow
from scripts.qa_setup_first_user import app, isolated, close
from scripts.qa_setup_v2 import scene


@pytest.mark.parametrize("offset", [0.037, 12345.678])
@pytest.mark.parametrize("second", [False, True])
@pytest.mark.parametrize("kind", ["missing-reading", "changing-candidate"])
def test_alert_hold_deadline_is_bounded_at_fractional_monotonic_times(offset, second, kind):
    machine = BuffStateMachine(appear_frames=1, alert_before=30, alert_before2=10)
    machine.observe(detected=True, reading=40, now=offset)
    machine.observe(detected=True, reading=39.95, now=offset + 0.05)
    if second:
        assert machine.observe(detected=True, reading=29.99, now=offset + 10.01) is Event.ALERT
        assert not machine.check_second_alert(offset + 10.01)
    start = offset + (30.005 if second else 10.005)
    for index, delta in enumerate([0, 0.051, 0.113, 0.199999, 0.200001]):
        reading = 100 + index * 30 if not index or kind == "changing-candidate" else None
        event = machine.observe(detected=True, reading=reading, now=start + delta)
        secondary = machine.check_second_alert(start + delta)
        assert (event is Event.ALERT) is (not second and index == 4)
        assert secondary is (second and index == 4)
    assert machine.observe(detected=True, reading=None, now=start + 0.3) is not Event.ALERT
    assert not machine.check_second_alert(start + 0.3)


@pytest.mark.parametrize("logged_in, skip", [(True, False), (True, True), (False, False)])
def test_completed_settings_and_old_view_history_obey_revised_start_policy(scene, app, monkeypatch, logged_in, skip):
    _, account, _, _, _, _, _ = scene
    account["logged_in"] = logged_in
    raw = config._read_local_config()
    raw.setdefault("general", {}).update(gameExe="Client.exe", skipSetup=skip,
                                         tourShown=True, firstUseGuideShown=True)
    raw["buffTracker"].update(enabled=True, captureRegion={"x": 10, "y": 20, "w": 200, "h": 500})
    config._write_local_config(raw)
    assert setup_state.pending() == []
    window = MainWindow()
    monkeypatch.setattr(window.party_tab, "start_polling", lambda: None)
    order = []
    def notes():
        assert not window.setup_guide.active
        order.append("notes")
    monkeypatch.setattr(window, "_maybe_show_release_notes", notes)
    try:
        window.start()
        before = deepcopy(config._read_local_config())
        window.show()
        app.processEvents()
        assert order == ["notes"]
        expected = logged_in and not skip
        assert (window._pages.currentWidget() is window.setup_guide) is expected
        assert window.setup_guide.active is expected
        assert window._pages.currentWidget() is not window.setup_page
        assert config._read_local_config() == before
        window._leave_setup()
        window._tabs.setCurrentIndex(window._tabs.count() - 1)
        assert window.settings_tab.setup_btn is window.settings_tab.guide_btn
        assert window.settings_tab.guide_btn.isHidden() is (not logged_in)
        if logged_in:
            window.settings_tab.guide_btn.click()
            app.processEvents()
            assert window._pages.currentWidget() is window.setup_guide
            assert window.setup_guide.stage == 0
            assert window.setup_guide.skip.isChecked() is skip
            assert config._read_local_config() == before
    finally:
        close(window)
        app.processEvents()
