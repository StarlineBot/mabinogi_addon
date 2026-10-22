import json
import math
import time
from pathlib import Path
import pytest
from mabinogi_addon.optimization.frame_summary import FrameSummary, compare
from mabinogi_addon.optimization.frames import FrameStream
from mabinogi_addon.optimization.frame_summary_store import SummaryStore


def summary(values):
    result=FrameSummary();result.activate('0x1',10)
    stamp=10
    for value in values:
        stamp+=value;result.interval('0x1',stamp,value)
    return result


def test_exact_slowest_one_percent_not_percentile():
    book=summary([.01]*198+[.05,.1])
    r=book.current()
    assert r['valid_intervals']==200 and r['tail_count']==2
    assert r['low_1pct_fps']==pytest.approx(1/.075)
    assert r['average_fps']==pytest.approx(200/2.13)
    assert r['relative_long_count']==2 and r['max_ms']==100
    assert len(r['longest'])==8


def test_maximum_uses_complete_one_second_windows_not_single_fast_frame():
    r=summary([.01]*200).current()
    assert r['max_1s_fps']==100 and r['completed_1s_windows']==2
    r=summary([.0001]+[.02]*100).current()
    assert r['max_1s_fps'] < 100 and r['max_1s_fps'] != 10000
    assert summary([.02]*20).current()['max_1s_fps'] is None
    assert summary([.02]*99).current()['low_1pct_fps'] is None


def test_cpu_limit_can_be_slower_but_steadier_and_is_tradeoff():
    before=summary([.01,.01,.01,.03]*100).current()
    after=summary([.025]*400).current()
    result=compare(before,after)
    assert result['status']=='tradeoff'
    assert result['average_fps_delta']<0 and result['max_1s_fps_delta']<0
    assert result['variation_percentage_points_delta']<0
    assert '성공 판정이 아니에요' in result['message']


def test_memory_bounds_and_time_boundaries_keep_all_summaries():
    book=FrameSummary();book.MAX_SAMPLES=100;book.MAX_SEGMENTS=2
    book.activate('a',10)
    for n in range(400): book.interval('a',10+(n+1)*.01,.01)
    assert book.full and len(book.records)==2 and not book.samples
    assert sum(r['valid_intervals'] for r in book.records)==200


def test_long_interval_does_not_allocate_per_second_or_disappear():
    book=summary([.02]*100+[100000.])
    r=book.records[-1]
    assert r['max_ms']==100000000 and r['relative_long_count']==1
    assert r['max_1s_fps']==50


def test_stream_missing_reversal_focus_and_ambiguous_sources_split():
    book=FrameSummary();stream=FrameStream(7,1000000,book)
    stream.feed('Application,ProcessID,SwapChainAddress,QPCTime,msBetweenPresents',100)
    def feed(stamp, interval=20,source='0x1'):
        stream.feed(f'game,7,{source},{round(stamp*1000000)},{interval}',stamp)
    for n in range(102):feed(100+n*.02)
    assert book.current()['valid_intervals']==101
    feed(102.1,20)
    assert book.records[-1]['end_reason']=='out_of_order_or_missing_event'
    assert book.current() is None
    feed(102.12);feed(102.14)
    stream.boundary(103,'alt_tab')
    assert book.records[-1]['valid_intervals']==2
    feed(103.1);feed(103.12)
    feed(103.13,20,'0x2')
    assert book.source is None
    assert book.records[-1]['end_reason']=='ambiguous_or_missing_swapchain'


def test_summary_store_atomic_json_no_raw_frames_or_overwrites(tmp_path):
    store=SummaryStore(tmp_path/'records')
    report=summary([.02]*100).report()
    store.submit(report);store.submit(report)
    deadline=time.monotonic()+3;results=[]
    while time.monotonic()<deadline:
        results+=store.poll()
        if len(results)==2:break
        time.sleep(.005)
    assert len(results)==2 and all(error is None for _,error in results)
    assert results[0][0]!=results[1][0]
    data=json.loads(Path(results[0][0]).read_text())
    assert data['raw_events_saved'] is False and data['schema']==1
    assert data['segments'][0]['low_1pct_fps']==pytest.approx(50)
    assert store.close_ready()


def test_store_limit_is_error_and_preserves_existing_data(tmp_path):
    tmp_path.joinpath('existing.json').write_text('keep')
    store=SummaryStore(tmp_path);store.MAX_FILES=1
    store.submit(summary([.02]*100).report())
    store.thread.join(3)
    result,=store.poll()
    assert result[0] is None and result[1]
    assert tmp_path.joinpath('existing.json').read_text()=='keep'


def test_published_file_survives_cleanup_failure_and_close_waits_for_result(tmp_path, monkeypatch):
    original_unlink = Path.unlink
    def fail_partial(path, *args, **kwargs):
        if path.suffix == '.partial':
            raise OSError('synthetic cleanup failure')
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail_partial)
    store = SummaryStore(tmp_path)
    store.submit(summary([.02] * 100).report())
    store.thread.join(3)
    assert not store.thread.is_alive()
    assert not store.close_ready()
    (published, warning), = store.poll()
    assert published and Path(published).is_file()
    assert '정리 실패' in warning
    assert json.loads(Path(published).read_text())['schema'] == 1
    assert store.close_ready()
