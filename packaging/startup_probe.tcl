# Instrumentation is compiled only into the manual proof executable, never production.
set startup_probe_events {}
set startup_probe_stage unpack
rename startup_show startup_show_original
proc startup_show {text} {
    startup_show_original $text
    global startup_probe_events startup_probe_stage
    if {[winfo ismapped .] && [llength $startup_probe_events] < 512} {
        lappend startup_probe_events [list [clock milliseconds] $startup_probe_stage \
            [wm frame .] [wm geometry .] [.root.canvas itemcget startup_text -text]]
    }
}
proc startup_probe_control {_n _i _o} {
    global status_text startup_probe_stage startup_probe_events env startup_messages startup_scale
    if {$status_text eq {@probe:app}} {set startup_probe_stage app}
    if {$status_text eq {@probe:check}} {
        lappend startup_probe_events [list [clock milliseconds] checkpoint \
            [wm frame .] [wm geometry .] [.root.canvas itemcget startup_text -text]]
    }
    if {$status_text eq {@probe:flush}} {
        if {![info exists env(MABINOGI_SPLASH_PROBE_REPORT)]} {error {probe output not configured}}
        set output [open $env(MABINOGI_SPLASH_PROBE_REPORT) w]
        fconfigure $output -encoding utf-8 -translation lf
        foreach event $startup_probe_events {
            puts $output [join $event \t]
        }
        close $output
        # Measure the actual bundled Korean font and all complete messages on this
        # canvas. Restore before returning to the event loop, so nothing flashes.
        set saved [.root.canvas itemcget startup_text -text]
        set bounds [open "$env(MABINOGI_SPLASH_PROBE_REPORT).bounds.tsv" w]
        fconfigure $bounds -encoding utf-8 -translation lf
        foreach glyphs $startup_messages {
            set message [join $glyphs {}]
            .root.canvas itemconfigure startup_text -text $message
            puts $bounds [join [linsert [.root.canvas bbox startup_text] 0 $message] \t]
        }
        close $bounds
        .root.canvas itemconfigure startup_text -text $saved
    }
}
trace add variable status_text write startup_probe_control
proc startup_probe_mapped {widget} {
    global startup_probe_stage startup_probe_events
    if {$widget eq {.}} {
        lappend startup_probe_events [list [clock milliseconds] $startup_probe_stage \
            [wm frame .] [wm geometry .] [.root.canvas itemcget startup_text -text]]
    }
}
bind . <Map> {startup_probe_mapped %W}
