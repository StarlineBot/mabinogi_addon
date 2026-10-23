import pytest

from mabinogi_addon.tracker.halo import EVENTS,HaloTracker


def sync(clock,raw=900,start=0):
    clock.arm()
    assert clock.observe(raw,start,target=(1,2)).phase=='confirming'
    assert clock.observe(raw,start+.5,target=(1,2)).phase=='confirming'
    return clock.observe(raw-1,start+1,target=(1,2))


def test_schedule_and_early_first_warning():
    # 14:53 13:50 12:47 11:44 10:41 09:38 08:35 | 07:33 06:30 05:27 04:24 03:21 02:18 01:15 00:12 (7→8회차만 62초)
    assert EVENTS==(893,830,767,704,641,578,515,453,390,327,264,201,138,75,12)
    assert [a-b for a,b in zip(EVENTS,EVENTS[1:])]==[63]*6+[62]+[63]*7
    clock=HaloTracker()
    assert sync(clock).until_halo==6
    assert clock.observe(898,2).warning==1
    assert clock.observe(898,2.5).warning is None


def test_middle_sync_skips_past_alarms_and_shows_next():
    clock=HaloTracker()
    state=sync(clock,882)
    assert state.remaining==881 and state.until_halo==51
    assert 1 in clock.fired
    assert clock.observe(880,2).warning is None


def test_complete_battle_fires_each_warning_once_without_accumulated_drift():
    clock=HaloTracker()
    sync(clock)
    warnings=[]
    for tick in range(4,1801):
        now=tick/2
        state=clock.observe(900-int(now),now)
        if state.warning:
            warnings.append((state.warning,now))
    assert warnings==[(k,900-(event+5)) for k,event in enumerate(EVENTS,1)]
    # 2026-10-23 보정: 8회차 경고는 07:38(남은 458초), 9회차는 06:35(395초)에 한 번씩
    assert [w for w in warnings if w[0] in (8,9)]==[(8,900-458),(9,900-395)]
    assert not clock.armed


@pytest.mark.parametrize('reason',['focus','missing','sleep'])
def test_missing_warning_is_not_replayed_on_recovery(reason):
    clock=HaloTracker()
    sync(clock)
    if reason=='sleep':
        assert clock.observe(890,10).phase=='uncertain'
        start=10.5
    else:
        for now in (1.5,2,2.5,3,4,5):
            clock.observe(None if reason=='missing' else 900-int(now),now,eligible=reason!='focus')
        start=5.5
    for now in (start,start+.5,start+1,start+1.5):
        assert clock.observe(900-int(now),now).warning is None
    assert 1 in clock.fired


def test_jump_back_requires_new_battle_arming():
    clock=HaloTracker()
    sync(clock,800)
    assert clock.observe(900,2).phase=='uncertain'
    assert clock.observe(900,2.5).phase=='uncertain'
    assert clock.observe(899,3).phase=='stopped'
    assert not clock.armed


def test_single_upward_misread_preserves_battle_and_fired_rounds():
    clock=HaloTracker()
    sync(clock)
    assert clock.observe(898,2).warning==1
    anchor=clock.anchor
    assert clock.observe(900,8).phase=='uncertain'
    assert clock.anchor==anchor and 1 in clock.fired and clock.armed
    for now,raw in ((8.5,892),(9,891),(9.5,891)):
        assert clock.observe(raw,now).warning is None
    assert clock.armed and 1 in clock.fired


def test_new_target_and_clock_reversal_stop_old_session():
    clock=HaloTracker()
    sync(clock)
    assert clock.observe(899,1.5,target=(2,3)).phase=='stopped'
    sync(clock)
    assert clock.observe(900,-1).phase=='stopped'


def test_small_drift_requires_confirmation_and_never_rewinds_fired_alarm():
    clock=HaloTracker()
    sync(clock)
    assert clock.observe(898,2).warning==1
    for now,raw in ((3,894),(3.5,894),(4,893)):
        assert clock.observe(raw,now).warning is None
    assert 1 in clock.fired
def test_frozen_timer_never_synchronizes():
    tracker = HaloTracker()
    tracker.arm()
    for tick in range(30):
        state = tracker.observe(881, tick / 2, target=(1, 2))
        assert state.phase == 'confirming'
        assert state.warning is None
    assert tracker.anchor is None

