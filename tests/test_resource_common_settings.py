from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from PySide6.QtCore import QTimer,QCoreApplication,QEvent,QRect
from PySide6.QtWidgets import QMessageBox,QApplication,QWidget,QVBoxLayout

from test_resource_integration import runtime
from mabinogi_addon import config
from mabinogi_addon.ui import resource_tab,region_registration as reg
from mabinogi_addon.detect import resource_pair


@pytest.fixture
def window(monkeypatch):
    from types import SimpleNamespace
    from mabinogi_addon.ui.dorcha_tab import DorchaTab
    from mabinogi_addon.ui.tuarim_tab import TuarimTab
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication,"quit",lambda:None)
    monkeypatch.setattr(config,"load_discord_user",lambda:{"id":"test","name":"테스트"})
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen,"availableGeometry",lambda self:QRect(0,0,1600,1100))
    monkeypatch.setattr(screen,"geometry",lambda self:QRect(0,0,1600,1100))
    watcher = SimpleNamespace(is_game_active=lambda:False,is_self_active=lambda:False)
    if os.environ.get("MABINOGI_COMMON_MAIN_TEST") == "1":
        from mabinogi_addon.ui.main_window import MainWindow
        w = MainWindow()
        w._post_show_done = True
        w._leave_setup()
        w._booting = False
    else:
        w = QWidget()
        w.dorcha_tab = DorchaTab(watcher)
        w.tuarim_tab = TuarimTab(watcher)
        w.resource_tab = resource_tab.ResourceTab(w.dorcha_tab,w.tuarim_tab)
        QVBoxLayout(w).addWidget(w.resource_tab)
    w.show()
    for timer in w.findChildren(QTimer): timer.stop()
    app.processEvents()
    try:
        yield w,app
    finally:
        w.resource_tab.shutdown()
        w.dorcha_tab.shutdown()
        w.tuarim_tab.shutdown()
        w._force_quit = True
        w.close()
        if w.resource_tab._future is not None:
            w.resource_tab._future.result(timeout=5)
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.fixture
def common(runtime,monkeypatch):
    window,state,pump = runtime
    view = window.resource_tab
    notices = []
    monkeypatch.setattr(reg,"warn",lambda *args:notices.append(args))
    monkeypatch.setattr(resource_tab,"notice",lambda *args:notices.append(args))
    monkeypatch.setattr(resource_tab,"to_logical",lambda *box:box)
    monkeypatch.setattr(resource_tab,"capture_for_autofind",lambda **kwargs:(np.zeros((90,120,3),np.uint8),-100,20))
    candidates = {"dorcha":[14,23,28,23],"tuarim":[40,51,42,16]}
    def locate(frame,assets,trace,**kwargs):
        trace["regions"] = deepcopy(candidates)
        return (14,23,68,44) if candidates else None
    monkeypatch.setattr(resource_pair,"locate_resources",locate)
    approvals = []
    def approve(title):
        approvals.append(title)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(view,"_approve",approve)
    return window,view,candidates,approvals,notices


def test_common_approval_is_one_atomic_write_and_preserves_options(common,monkeypatch):
    w,view,candidates,approvals,_ = common
    before = deepcopy(config._read_local_config())
    writes = []
    writer = config._write_local_config
    monkeypatch.setattr(config,"_write_local_config",lambda raw,*args,**kwargs:(writes.append(deepcopy(raw)),writer(raw,*args,**kwargs))[1])
    applied = view.find_regions()
    assert applied == {"dorcha":(-86,43,28,23),"tuarim":(-60,71,42,16)}
    assert len(approvals) == len(writes) == 1
    expected = deepcopy(before)
    for key,box in applied.items(): expected.setdefault(key,{})["box"] = dict(zip(("x","y","w","h"),box))
    assert config._read_local_config() == expected
    assert w.dorcha_tab._region == expected["dorcha"]["box"]
    assert w.tuarim_tab._region == expected["tuarim"]["box"]


@pytest.mark.parametrize("found",["dorcha","tuarim"])
def test_partial_success_preserves_the_other_source(common,found):
    w,view,candidates,approvals,_ = common
    del candidates["tuarim" if found=="dorcha" else "dorcha"]
    before = deepcopy(config._read_local_config())
    applied = view.find_regions()
    assert set(applied) == {found}
    assert "만 찾음" in approvals[0]
    other = "tuarim" if found=="dorcha" else "dorcha"
    assert config._read_local_config().get(other) == before.get(other)


@pytest.mark.parametrize("failure",["cancel","permission","none"])
def test_common_failures_do_not_change_settings_or_memory(common,monkeypatch,failure):
    w,view,candidates,_,notices = common
    before = deepcopy(config._read_local_config())
    memory = deepcopy((w.dorcha_tab._region,w.tuarim_tab._region))
    writer = config._write_local_config
    if failure=="cancel": monkeypatch.setattr(view,"_approve",lambda title:QMessageBox.StandardButton.No)
    if failure=="none": candidates.clear()
    if failure=="permission":
        def denied(*args,**kwargs): raise PermissionError("read only")
        monkeypatch.setattr(config,"_write_local_config",denied)
    assert view.find_regions() == {}
    assert config._read_local_config() == before
    assert (w.dorcha_tab._region,w.tuarim_tab._region) == memory
    assert not view._busy
    monkeypatch.setattr(config,"_write_local_config",writer)


def test_requesting_only_percent_never_writes_dorcha(common):
    w,view,*_ = common
    before = deepcopy(config._read_local_config().get("dorcha"))
    assert set(view.find_regions(keys=("tuarim",))) == {"tuarim"}
    assert config._read_local_config().get("dorcha") == before


@pytest.mark.parametrize("failure",["cancel","permission",None])
def test_clear_common_is_atomic_and_preserves_all_options(common,monkeypatch,failure):
    w,view,*_ = common
    raw = config._read_local_config()
    for key,c in view._controllers().items(): raw.setdefault(key,{})["box"] = deepcopy(c._region)
    config._write_local_config(raw)
    before = deepcopy(raw)
    writer = config._write_local_config
    monkeypatch.setattr(reg,"confirm_clear",lambda *args:QMessageBox.StandardButton.No if failure=="cancel" else QMessageBox.StandardButton.Yes)
    if failure=="permission":
        def denied(*args,**kwargs): raise PermissionError("read only")
        monkeypatch.setattr(config,"_write_local_config",denied)
    view._clear_regions()
    expected = deepcopy(before)
    if failure is None:
        expected["dorcha"]["box"] = expected["tuarim"]["box"] = None
        assert w.dorcha_tab._region is w.tuarim_tab._region is None
    else:
        assert w.dorcha_tab._region and w.tuarim_tab._region
    assert config._read_local_config() == expected
    monkeypatch.setattr(config,"_write_local_config",writer)


def test_cleared_region_cannot_be_restored_by_pending_detection(common,monkeypatch):
    w,view,_,approvals,_ = common
    assert config.load_dorcha()["box"] == w.dorcha_tab._region
    assert w.dorcha_tab.clear_region_btn.isEnabled()
    monkeypatch.setattr(reg,"confirm_clear",lambda *args:QMessageBox.StandardButton.Yes)
    QTimer.singleShot(0,w.dorcha_tab.clear_region_btn.click)
    assert view.find_regions() == {}
    assert config._read_local_config()["dorcha"]["box"] is None
    assert w.dorcha_tab._region is None
    assert not w.dorcha_tab.clear_region_btn.isEnabled()
    assert not approvals


def test_nested_common_request_is_rejected_and_ui_keeps_pumping(common):
    _,view,_,approvals,_ = common
    nested = []
    QTimer.singleShot(0,lambda:nested.append(view.find_regions()))
    assert len(view.find_regions()) == 2
    assert nested == [{}]
    assert len(approvals) == 1


def test_shutdown_while_detecting_never_approves(common):
    _,view,_,approvals,_ = common
    QTimer.singleShot(0,view.shutdown)
    assert view.find_regions() == {}
    assert not approvals
    assert not view.dorcha._timer.isActive() or view.dorcha._shutting_down


def test_logout_during_approval_still_registers_public_regions(common,monkeypatch):
    _,view,*_ = common
    before = deepcopy(config._read_local_config())
    def approve(title):
        monkeypatch.setattr(config,"load_discord_user",lambda:None)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(view,"_approve",approve)
    applied=view.find_regions()
    assert applied == {"dorcha":(-86,43,28,23),"tuarim":(-60,71,42,16)}
    expected=deepcopy(before)
    for key,box in applied.items(): expected.setdefault(key,{})['box']=dict(zip(('x','y','w','h'),box))
    assert config._read_local_config() == expected


def test_public_manual_registers_both_resources_without_login(common,monkeypatch):
    _,view,*_ = common
    monkeypatch.setattr(config,"load_discord_user",lambda:None)
    monkeypatch.setattr(resource_tab,"to_physical",lambda box:tuple(box[k] for k in ("x","y","w","h")))
    monkeypatch.setattr(resource_tab,"capture_for_autofind",lambda **kwargs:(np.zeros((150,160,3),np.uint8),0,0))
    before = deepcopy(config._read_local_config().get("dorcha"))
    view._manual_region(10,20,90,70)
    expected = deepcopy(before)
    expected["box"] = dict(x=24,y=43,w=28,h=23)
    assert config._read_local_config().get("dorcha") == expected
    assert config._read_local_config()["tuarim"]["box"] == dict(x=50,y=71,w=42,h=16)


def test_current_region_changed_during_approval_is_preserved(common,monkeypatch):
    _,view,*_ = common
    def approve(title):
        config.save_tuarim({"box":dict(x=300,y=400,w=42,h=16)})
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(view,"_approve",approve)
    assert view.find_regions() == {}
    assert config._read_local_config()["tuarim"]["box"] == dict(x=300,y=400,w=42,h=16)


@pytest.mark.parametrize("case",[
    "test_common_approval_is_one_atomic_write_and_preserves_options",
    "test_partial_success_preserves_the_other_source[dorcha]",
    "test_partial_success_preserves_the_other_source[tuarim]",
    "test_common_failures_do_not_change_settings_or_memory[cancel]",
    "test_common_failures_do_not_change_settings_or_memory[permission]",
    "test_common_failures_do_not_change_settings_or_memory[none]",
    "test_requesting_only_percent_never_writes_dorcha",
    "test_clear_common_is_atomic_and_preserves_all_options[cancel]",
    "test_clear_common_is_atomic_and_preserves_all_options[permission]",
    "test_clear_common_is_atomic_and_preserves_all_options[None]",
    "test_cleared_region_cannot_be_restored_by_pending_detection",
    "test_nested_common_request_is_rejected_and_ui_keeps_pumping",
    "test_shutdown_while_detecting_never_approves",
])
def test_same_contract_in_a_fresh_main_process(case):
    env = dict(os.environ,MABINOGI_COMMON_MAIN_TEST="1",QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable,"-m","pytest",str(Path(__file__).resolve())+"::"+case,
        "-q","--tb=short"],cwd=Path(__file__).resolve().parents[1],env=env,
        capture_output=True,text=True,timeout=40)
    assert result.returncode == 0,result.stdout+result.stderr
