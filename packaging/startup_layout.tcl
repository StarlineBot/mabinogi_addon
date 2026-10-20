# Fixed slots on the background: the logo and caption are baked once into the PNG.
# No second toplevel is created. DPI initialization happens before the event loop maps it.
wm title . {섯다라인 애드온 · 시작}
set startup_base_width [image width splash_image]
set startup_base_height [image height splash_image]
# Initial probe supports the standard Windows quarter-step DPI settings.
set startup_scale [expr {max(1.0, round(([tk scaling]/(96.0/72.0))*4)/4.0)}]
set startup_n [expr {int(round($startup_scale*4))}]
set startup_d 4
set a $startup_n
set b $startup_d
while {$b != 0} {set remainder [expr {$a % $b}]; set a $b; set b $remainder}
set startup_n [expr {$startup_n/$a}]
set startup_d [expr {$startup_d/$a}]
image create photo startup_scaled
startup_scaled copy splash_image -zoom $startup_n -subsample $startup_d
.root.canvas itemconfigure 1 -image startup_scaled
set startup_width [image width startup_scaled]
set startup_height [image height startup_scaled]
.root.canvas coords 1 [expr {$startup_width/2.0}] [expr {$startup_height/2.0}]
.root.canvas configure -width $startup_width -height $startup_height
font create startupFont -family {Malgun Gothic} -size [expr {-int(round(13*$startup_scale))}]
.root.canvas create text [expr {220*$startup_scale}] [expr {198*$startup_scale}] \
    -fill {#e5e7eb} -justify center -font startupFont -tag startup_text \
    -anchor n -width [expr {392*$startup_scale}] -text {}
set x_position [expr {int($display_x+0.5*($display_width-$startup_width))}]
set y_position [expr {int($display_y+0.5*($display_height-$startup_height))}]
wm geometry . ${startup_width}x${startup_height}+${x_position}+${y_position}
proc startup_show {text} {.root.canvas itemconfigure startup_text -text $text}
bind . <Destroy> {catch {startup::destroy %W}}
