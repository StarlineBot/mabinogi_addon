from copy import deepcopy

import numpy as np
import pytest

from test_navigation import window
from mabinogi_addon import config,setup_state
from mabinogi_addon.ui import region_registration as reg


@pytest.mark.parametrize("logged_in", [False, True])
@pytest.mark.parametrize("found",[("dorcha","tuarim"),("dorcha",),("tuarim",)])
def test_setup_two_selected_resources_share_one_request_and_preserve_options(window,monkeypatch,found,logged_in):
    w,app = window
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id":"test"} if logged_in else None)
    raw = config._read_local_config()
    raw.setdefault("general",{})["gameExe"] = "client.exe"
    config._write_local_config(raw)
    for key in ("dorcha","tuarim"): setup_state.save_selection(key,True)
    before = deepcopy(config._read_local_config())
    calls = []
    def find(*,keys,capture,allowed):
        calls.append(keys)
        assert allowed()
        boxes = {key:(10,20,28,23) if key=="dorcha" else (36,48,42,16) for key in found}
        assert reg.save_boxes(w.resource_tab,boxes)
        w.resource_tab.last_status = "applied"
        return boxes
    monkeypatch.setattr(w.resource_tab,"find_regions",find)
    w._setup_flow.run(page=w.setup_page,feature_keys=("dorcha","tuarim"))
    assert calls == [("dorcha","tuarim")]
    after = config._read_local_config()
    for key in ("dorcha","tuarim"):
        expected = deepcopy(before.get(key,{}))
        if key in found: expected["box"] = dict(zip(("x","y","w","h"),(10,20,28,23) if key=="dorcha" else (36,48,42,16)))
        assert after.get(key,{}) == expected


def test_setup_percent_only_keeps_existing_dorcha_registration(window,monkeypatch):
    w,app = window
    raw = config._read_local_config()
    raw.setdefault("general",{})["gameExe"] = "client.exe"
    raw["dorcha"] = dict(box=dict(x=300,y=400,w=28,h=23),enabled=False)
    config._write_local_config(raw)
    setup_state.save_selection("tuarim",True)
    before = deepcopy(config._read_local_config()["dorcha"])
    monkeypatch.setattr(w._setup_flow,"_detect",lambda feature,*args:(20,30,42,16) if feature=="tuarim" else pytest.fail("unrequested detector"))
    monkeypatch.setattr(w._setup_flow,"_approve",lambda key,box:box)
    from mabinogi_addon.ui import setup_flow
    monkeypatch.setattr(setup_flow,"capture_for_autofind",lambda **kwargs:(np.zeros((100,100,3),np.uint8),0,0))
    w._setup_flow.run(page=w.setup_page,feature_keys=("tuarim",))
    assert config._read_local_config()["dorcha"] == before
    assert config._read_local_config()["tuarim"]["box"] == dict(x=20,y=30,w=42,h=16)
