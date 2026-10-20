"""Independent bounded-callback probe; runs Tcl, not a Windows bootloader."""

from pathlib import Path
import sys
import tkinter

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from scripts.startup_splash import animation_script
from mabinogi_addon.startup_content import MESSAGES


def main():
    tcl = tkinter.Tcl()
    tcl.eval("""
        rename after actual_after
        set pending {}
        set sequence 0
        set shown {}
        proc after {args} {
            global pending sequence
            if {[lindex $args 0] eq {cancel}} {
                dict unset pending [lindex $args 1]
                return
            }
            incr sequence
            dict set pending $sequence $args
            return $sequence
        }
        proc startup_show {text} {set ::shown $text}
        proc fire {} {
            set id [lindex [dict keys $::pending] 0]
            set callback [dict get $::pending $id]
            dict unset ::pending $id
            uplevel #0 [lindex $callback 1]
        }
    """)
    tcl.eval(animation_script(MESSAGES))
    maximum = 0
    completed = set()
    for _ in range(100000):
        count = int(tcl.eval("dict size $pending"))
        assert count == 1, count
        maximum = max(maximum, count)
        tcl.eval("fire")
        shown = tcl.eval("set shown")
        if shown in MESSAGES:
            completed.add(shown)
    assert completed == set(MESSAGES)

    for _ in range(2000):
        stale = tcl.eval("set startup::generation")
        tcl.setvar("status_text", "@status:important status")
        assert tcl.eval("set shown") == "important status"
        assert int(tcl.eval("dict size $pending")) == 0
        tcl.eval("startup::tick " + stale)
        tcl.setvar("status_text", "extracting: ignored")
        assert tcl.eval("set shown") == "important status"
        tcl.setvar("status_text", "@resume")
        assert int(tcl.eval("dict size $pending")) == 1

    tcl.eval("startup::close")
    snapshot = tcl.eval("set shown")
    tcl.setvar("status_text", "@resume")
    tcl.setvar("status_text", "@status:late status")
    tcl.eval("startup::tick " + stale)
    assert int(tcl.eval("dict size $pending")) == 0
    assert tcl.eval("set shown") == snapshot

    tcl.eval(animation_script(["single message"]))
    for _ in range(500):
        assert int(tcl.eval("dict size $pending")) == 1
        tcl.eval("fire")
    tcl.eval("startup::close")
    assert int(tcl.eval("dict size $pending")) == 0
    print("PASS: 100000 callbacks; all 16 messages; 2000 status/resume cycles; "
          "one-message replacement; maximum pending=" + str(maximum) + "; closed pending=0")


if __name__ == "__main__":
    main()
