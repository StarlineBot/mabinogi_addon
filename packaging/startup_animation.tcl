# This interpreter runs in PyInstaller's splash thread before Python starts.
# startup_messages is an immutable list of NFC character lists generated at build time.
namespace eval startup {
    variable mode dialogue
    variable generation 0
    variable job {}
    variable index 0
    variable glyphs {}
    variable previous -1
}
proc startup::cancel {} {
    variable generation
    variable job
    incr generation
    if {$job ne {}} {catch {after cancel $job}}
    set job {}
}
proc startup::safe_show {text} {
    if {[catch {startup_show $text}]} {
        cancel
        variable mode
        set mode fallback
        catch {startup_show {시작하는 중}}
    }
}
proc startup::choose {} {
    variable previous
    variable glyphs
    variable index
    variable mode
    global startup_messages
    set count [llength $startup_messages]
    if {$count == 0} {
        set mode fallback
        safe_show {시작하는 중}
        return
    }
    set next [expr {int(rand()*$count)}]
    if {$count > 1 && $next == $previous} {set next [expr {($next+1)%$count}]}
    set previous $next
    set glyphs [lindex $startup_messages $next]
    set index 0
    safe_show {}
}
proc startup::tick {token} {
    variable mode
    variable generation
    variable job
    variable glyphs
    variable index
    global startup_interval startup_hold
    if {$token != $generation || $mode ne {dialogue}} {return}
    set job {}
    if {$index >= [llength $glyphs]} {
        choose
        if {$mode ne {dialogue}} {return}
        set job [after $startup_interval [list startup::tick $generation]]
        return
    }
    incr index
    safe_show [join [lrange $glyphs 0 [expr {$index-1}]] {}]
    if {$mode ne {dialogue}} {return}
    set delay [expr {$index == [llength $glyphs] ? $startup_hold : $startup_interval}]
    set job [after $delay [list startup::tick $generation]]
}
proc startup::resume {} {
    variable mode
    variable generation
    if {$mode eq {closed} || $mode eq {fallback} || $mode eq {dialogue}} {return}
    cancel
    set mode dialogue
    choose
    if {$mode eq {dialogue}} {tick $generation}
}
proc startup::status {text} {
    variable mode
    if {$mode eq {closed}} {return}
    cancel
    set mode status
    safe_show $text
}
proc startup::close {} {
    variable mode
    cancel
    set mode closed
}
proc startup::destroy {widget} {
    if {$widget eq {.}} {close}
}
proc startup::control {_name _index _op} {
    global status_text
    # Bootloader extraction paths and unmarked internal messages are ignored.
    if {[string first {@status:} $status_text] == 0} {
        status [string range $status_text 8 end]
    } elseif {$status_text eq {@resume}} {
        resume
    }
}
proc startup::begin {} {
    variable mode
    variable generation
    variable job
    global startup_interval
    choose
    if {$mode eq {dialogue}} {set job [after $startup_interval [list startup::tick $generation]]}
}
trace add variable status_text write startup::control
startup::begin
