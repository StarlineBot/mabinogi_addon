"""Keep approved coordinates, but do not trust stale numeric pixels on restart."""

from test_support.regressions.dorcha_restart import (
    moved,
    test_restart_must_reacquire_visible_moved_resource,
    test_one_shot_autofind_approval_recovers_the_same_input,
)
