"""합성 구간만 사용하는 개발 검사. Windows 녹화/재생 성공의 증거가 아니다."""

from dataclasses import replace

import pytest

from mabinogi_addon.blackbox import BufferFullError, ReplayBuffer, Segment


SECOND = 1_000_000
MINUTE = 60 * SECOND


def buffer(**options):
    # 버퍼 동작 검사는 명세 AC20(6분+4분=10분) 예시 기준 10분 보관으로 한다. 제품 기본 5분은 test_blackbox_public에서 검사.
    return ReplayBuffer('app1-game1', **(dict(max_bytes=1000, max_segments=100,
                                            max_saves=2, retention_us=10 * MINUTE) | options))


def segment(start, end, *, size=10, source=None, session='app1-game1', fmt='1080p60'):
    return Segment(session, source or f'chunk-{start}', start * SECOND,
                   end * SECOND, size, fmt)


def test_six_minutes_pause_five_minutes_then_four_minutes():
    replay = buffer()
    replay.append(segment(0, 360))
    replay.append(segment(660, 900))
    plan = replay.request_save(900 * SECOND)
    assert replay.available_us == plan.duration_us == 10 * MINUTE
    assert [(s.offset_us, s.duration_us) for s in plan.slices] == [
        (0, 6 * MINUTE), (0, 4 * MINUTE)]
    # Long inactive time alone never ages out valid recording time.
    assert replay.request_save(9000 * SECOND).slices == plan.slices


def test_short_recording_does_not_invent_history():
    replay = buffer()
    replay.append(segment(0, 180))
    assert replay.request_save(180 * SECOND).duration_us == 3 * MINUTE


def test_boundary_trim_and_request_endpoint_are_frozen():
    replay = buffer()
    first, second = segment(0, 360), segment(360, 720)
    replay.append(first)
    replay.append(second)
    plan = replay.request_save(720 * SECOND)
    assert [(s.offset_us, s.duration_us) for s in plan.slices] == [
        (2 * MINUTE, 4 * MINUTE), (0, 6 * MINUTE)]
    replay.append(segment(720, 1320))
    assert plan.request_us == 720 * SECOND
    assert plan.slices[-1].segment == second
    assert replay.retained_bytes == 30  # old originals pinned during export
    assert replay.release_save(plan) == (first, second)
    assert replay.retained_bytes == 10


def test_capacity_shortens_available_video_without_deleting_saved_files(tmp_path):
    saved = tmp_path / 'saved.mp4'
    saved.write_bytes(b'already exported')
    replay = buffer(max_bytes=15)
    old = segment(0, 180)
    replay.append(old)
    assert replay.append(segment(180, 240)) == (old,)
    assert replay.available_us == MINUTE
    assert replay.request_save(240 * SECOND).duration_us == MINUTE
    assert saved.read_bytes() == b'already exported'


def test_protected_capacity_failure_is_atomic_and_can_retry_after_release():
    replay = buffer(max_bytes=20)
    first, second, third = segment(0, 10), segment(10, 20), segment(20, 30)
    replay.append(first)
    replay.append(second)
    plan = replay.request_save(20 * SECOND)
    with pytest.raises(BufferFullError):
        replay.append(third)
    assert replay.retained_bytes == 20
    assert replay.available_us == 20 * SECOND
    assert plan.slices[-1].segment == second
    replay.release_save(plan)
    assert replay.append(third) == (first,)


def test_oversize_segment_preserves_previous_buffer():
    replay = buffer(max_bytes=20)
    replay.append(segment(0, 10))
    with pytest.raises(BufferFullError):
        replay.append(segment(10, 20, size=21))
    assert replay.available_us == 10 * SECOND
    assert replay.retained_bytes == 10


def test_count_budget_bounds_tiny_segments():
    replay = buffer(max_segments=2)
    for i in range(1000):
        replay.append(segment(i, i + 1, size=1))
        assert replay.retained_bytes <= 2
    assert replay.available_us == 2 * SECOND


def test_duplicate_requests_have_independent_pins_and_bounded_count():
    replay = buffer()
    old = segment(0, 600)
    replay.append(old)
    first, second = replay.request_save(600 * SECOND), replay.request_save(600 * SECOND)
    with pytest.raises(BufferFullError, match='request limit'):
        replay.request_save(600 * SECOND)
    replay.append(segment(600, 1200))
    assert replay.release_save(first) == ()
    assert replay.retained_bytes == 20
    assert replay.release_save(second) == (old,)
    with pytest.raises(ValueError):
        replay.release_save(second)


def test_unknown_equal_plan_cannot_release_owned_plan():
    replay = buffer()
    replay.append(segment(0, 10))
    plan = replay.request_save(10 * SECOND)
    with pytest.raises(ValueError):
        replay.release_save(replace(plan))
    with pytest.raises(BufferFullError):
        replay.clear()
    assert replay.retained_bytes == 10
    replay.release_save(plan)
    assert len(replay.clear()) == 1
    assert replay.clear() == ()


def test_retention_change_preserves_export_and_does_not_restore_evicted_history():
    replay = buffer()
    first, second = segment(0, 300), segment(300, 600)
    replay.append(first)
    replay.append(second)
    plan = replay.request_save(600 * SECOND)
    assert replay.set_retention(2 * MINUTE) == ()
    assert replay.available_us == 2 * MINUTE
    assert plan.duration_us == 10 * MINUTE
    assert replay.release_save(plan) == (first,)
    replay.set_retention(10 * MINUTE)
    assert replay.available_us == 5 * MINUTE


def test_empty_and_unvalidated_mixed_formats_are_not_successful_exports():
    replay = buffer()
    with pytest.raises(ValueError, match='no valid video'):
        replay.request_save(0)
    replay.append(segment(0, 10))
    replay.append(segment(10, 20, fmt='720p30'))
    with pytest.raises(ValueError, match='mixed formats'):
        replay.request_save(20 * SECOND)
    assert len(replay.clear()) == 2  # rejected request left no pins


@pytest.mark.parametrize('bad', [segment(10, 30), segment(0, 10),
    segment(20, 30, session='app1-game2'), segment(20, 30, session='app2-game1'),
    segment(20, 30, source='chunk-0')])
def test_late_overlapping_reused_source_or_other_session_is_rejected(bad):
    replay = buffer()
    replay.append(segment(0, 20))
    with pytest.raises(ValueError):
        replay.append(bad)
    assert replay.available_us == 20 * SECOND


def test_request_cannot_silently_include_future_video():
    replay = buffer()
    replay.append(segment(0, 20))
    with pytest.raises(ValueError):
        replay.request_save(10 * SECOND)


@pytest.mark.parametrize('field', ['max_bytes', 'max_segments', 'max_saves', 'retention_us'])
@pytest.mark.parametrize('value', [0, -1, True, float('nan'), float('inf'), 1.5])
def test_invalid_limits_rejected(field, value):
    with pytest.raises(ValueError):
        buffer(**{field: value})


@pytest.mark.parametrize('changes', [dict(start_us=-1), dict(start_us=True),
    dict(end_us=0), dict(end_us=float('nan')), dict(size_bytes=0),
    dict(session=''), dict(source=''), dict(format_key='')])
def test_invalid_segment_metadata_rejected(changes):
    with pytest.raises(ValueError):
        replace(segment(0, 10), **changes)


def test_repeated_export_release_retention_and_clear_remain_bounded():
    replay = buffer(max_bytes=20, max_segments=2, retention_us=SECOND)
    for i in range(1000):
        replay.append(segment(i, i + 1))
        plan = replay.request_save((i + 1) * SECOND)
        replay.release_save(plan)
        assert replay.available_us == SECOND
        assert replay.retained_bytes == 10
    assert len(replay.clear()) == 1
    assert replay.retained_bytes == replay.available_us == 0
