"""The actual embedded Tcl animation: deterministic callbacks, no GUI or disk polling."""

import unicodedata
import tkinter

import pytest

from scripts.startup_splash import animation_script, splash_type
from mabinogi_addon.startup_content import MESSAGES


@pytest.fixture
def animation():
    tcl = tkinter.Tcl()
    tcl.eval("""
        rename after real_after
        set pending {}
        set next_id 0
        set shown {}
        proc after {args} {
            global pending next_id
            if {[lindex $args 0] eq {cancel}} {dict unset pending [lindex $args 1]; return}
            incr next_id
            dict set pending $next_id $args
            return $next_id
        }
        proc startup_show {text} {global shown; lappend shown $text}
        proc fire {} {
            global pending
            set id [lindex [dict keys $pending] 0]
            set item [dict get $pending $id]
            dict unset pending $id
            uplevel #0 [lindex $item 1]
            return [lindex $item 0]
        }
    """)
    return tcl


def texts(tcl):
    return list(tcl.splitlist(tcl.eval("set shown")))


def test_embedded_typing_begins_empty_then_holds_and_replaces(animation):
    animation.eval(animation_script(["가나다", "라마"]))
    assert texts(animation) == [""]
    assert int(animation.eval("fire")) == 60
    assert texts(animation)[-1] in ("가", "라")
    chosen = animation.eval("set startup::previous")
    while int(animation.eval("set startup::index")) < int(
        animation.eval("llength $startup::glyphs")
    ):
        assert int(animation.eval("fire")) == 60
    full = texts(animation)[-1]
    assert full in ("가나다", "라마")
    assert int(animation.eval("fire")) == 2000
    assert texts(animation)[-1] == ""
    assert animation.eval("set startup::previous") != chosen
    assert int(animation.eval("fire")) == 60
    assert texts(animation)[-1] not in ("", full)
    assert int(animation.eval("dict size $pending")) == 1


@pytest.mark.parametrize(
    "status", ["업데이트 확인 중", "새 버전 v0.8.0 받는 중 37%", "업데이트 적용 중"]
)
def test_important_status_invalidates_every_old_callback(animation, status):
    animation.eval(animation_script(MESSAGES))
    stale = animation.eval("set startup::generation")
    animation.setvar("status_text", "@status:" + status)
    assert texts(animation)[-1] == status
    assert int(animation.eval("dict size $pending")) == 0
    before = texts(animation)
    animation.eval("startup::tick " + stale)
    animation.setvar("status_text", "Extracting: PySide6/Qt6Core.dll")
    assert texts(animation) == before
    animation.setvar("status_text", "@resume")
    assert animation.eval("set startup::mode") == "dialogue"
    assert len(texts(animation)) > len(before)


def test_internal_stage_updates_do_not_restart_or_overwrite_dialogue(animation):
    animation.eval(animation_script(MESSAGES))
    animation.eval("fire")
    before = (
        texts(animation),
        animation.eval("set startup::generation"),
        animation.eval("set pending"),
    )
    for text in ("_internal/Qt6.dll", "Unpacking file 3", "initialization"):
        animation.setvar("status_text", text)
    animation.setvar("status_text", "@resume")
    assert (
        texts(animation),
        animation.eval("set startup::generation"),
        animation.eval("set pending"),
    ) == before


@pytest.mark.parametrize("messages", [[], ["", None, "   "]])
def test_empty_content_stays_on_safe_fallback_without_timer(animation, messages):
    animation.eval(animation_script(messages))
    assert texts(animation) == ["시작하는 중"]
    assert int(animation.eval("dict size $pending")) == 0


def test_effect_failure_does_not_raise_or_keep_scheduling(animation):
    animation.eval("proc startup_show {text} {error {display unavailable}}")
    animation.eval(animation_script(MESSAGES))
    assert animation.eval("set startup::mode") == "fallback"
    assert int(animation.eval("dict size $pending")) == 0


def test_closed_animation_cannot_resume_or_update(animation):
    animation.eval(animation_script(MESSAGES))
    token = animation.eval("set startup::generation")
    animation.eval("startup::close")
    before = texts(animation)
    animation.eval("startup::tick " + token)
    animation.setvar("status_text", "@status:늦은 상태")
    animation.setvar("status_text", "@resume")
    assert texts(animation) == before
    assert int(animation.eval("dict size $pending")) == 0


def test_only_root_destruction_cancels_animation(animation):
    animation.eval(animation_script(MESSAGES))
    animation.eval("startup::destroy .root.canvas")
    assert animation.eval("set startup::mode") == "dialogue"
    assert int(animation.eval("dict size $pending")) == 1
    animation.eval("startup::destroy .")
    assert animation.eval("set startup::mode") == "closed"
    assert int(animation.eval("dict size $pending")) == 0


def test_unicode_and_tcl_metacharacters_are_literal_data(animation):
    message = "한글 [set injected 1] {$dollar} 😀"
    animation.eval(animation_script([message]))
    for _ in range(len(unicodedata.normalize("NFC", message))):
        animation.eval("fire")
    assert texts(animation)[-1] == unicodedata.normalize("NFC", message)
    assert animation.eval("info exists injected") == "0"
    assert texts(animation)[1] == "한"


def test_subclass_only_extends_the_spec_local_splash_contract(tmp_path):
    class Base:
        script_name = tmp_path / "splash.tcl"

        def generate_script(self):
            return "proc _ipc_caller\nset status_text\n.root.canvas\nset server_socket\nraise ."

    cls = splash_type(Base, messages=MESSAGES)
    script = cls().generate_script()
    assert script.isascii()
    decoded = bytes.fromhex(script.split("binary decode hex ")[1].split("]")[0]).decode(
        "utf-8"
    )
    assert "startup::begin" in decoded and "startup_probe" not in decoded
    assert decoded.index("startup::begin") < decoded.rindex("raise .")
    assert (
        Base().generate_script()
        == "proc _ipc_caller\nset status_text\n.root.canvas\nset server_socket\nraise ."
    )
    assert Base.script_name.read_text(encoding="utf-8") == script
    Base.generate_script = lambda self: "upstream changed"
    with pytest.raises(RuntimeError, match="contract changed"):
        cls().generate_script()
