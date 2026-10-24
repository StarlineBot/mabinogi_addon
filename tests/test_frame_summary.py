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
    data=json.loads(Path(results[0][0]).read_text(encoding="utf-8"))
    assert data['raw_events_saved'] is False and data['schema']==1
    assert data['segments'][0]['low_1pct_fps']==pytest.approx(50)
    assert store.close_ready()


def test_store_limit_is_error_and_preserves_existing_data(tmp_path):
    tmp_path.joinpath('existing.json').write_text('keep', encoding="utf-8")
    store=SummaryStore(tmp_path);store.MAX_FILES=1
    store.submit(summary([.02]*100).report())
    store.thread.join(3)
    result,=store.poll()
    assert result[0] is None and result[1]
    assert tmp_path.joinpath('existing.json').read_text(encoding="utf-8")=='keep'


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
    assert json.loads(Path(published).read_text(encoding="utf-8"))['schema'] == 1
    assert store.close_ready()


def test_same_condition_noise_is_not_reported_as_tradeoff():
    # FPS 7절: 같은 조건의 평균 -0.2FPS 같은 흔들림에는 절충 문구를 띄우지 않는다.
    before=summary([.01,.01,.01,.03]*300).current()
    after=summary([.0101,.0101,.0101,.0301]*300).current()
    result=compare(before,after)
    # 기준 0이던 이전 판정이라면 '평균 하락 + 변동 감소'로 절충이 떴을 조합
    assert -1 < result['average_fps_delta'] < 0 and result['variation_percentage_points_delta'] < 0
    assert result['status']=='within_noise' and '절충' not in result['message']
    assert '잡음 기준 안' in result['message']


def test_long_gaps_are_reported_per_minute_for_unequal_lengths():
    # 약 26초와 52초 구간: 긴 간격 횟수는 다르지만 분당 횟수는 같다.
    short=summary(([.01]*99+[.05])*25).current()
    long=summary(([.01]*99+[.05])*50).current()
    assert long['relative_long_count']==2*short['relative_long_count']
    assert long['relative_long_per_minute']==pytest.approx(short['relative_long_per_minute'])


def test_condition_name_is_kept_in_report_and_segments():
    book=FrameSummary();book.set_condition('  7+1 SMT끔 ·  Vulkan · 제한없음 '+'x'*80)
    book.activate('a',10)
    for n in range(120): book.interval('a',10+(n+1)*.01,.01)
    report=book.report()
    assert report['condition'].startswith('7+1 SMT끔 · Vulkan · 제한없음') and len(report['condition'])==48
    assert report['segments'][0]['condition']==report['condition']
    json.dumps(report,allow_nan=False)


def test_measurement_recomputes_one_percent_low_from_all_intervals():
    # 90초 측정 → 60초 + 30초 구간. 측정 전체 1% low는 구간 1% low의 평균이 아니라 전체 간격으로 계산.
    book=FrameSummary();book.activate('a',0)
    stamp=0
    for n in range(9000):
        value=.05 if n<6000 and n%100==0 else .01
        stamp+=value;book.interval('a',stamp,value)
    book.boundary(stamp+.001,'measurement_stop')
    assert len(book.records)==2
    whole=book.measurement()
    values=sorted(([.05 if n<6000 and n%100==0 else .01 for n in range(9000)]),reverse=True)
    assert whole['valid_intervals']==9000 and whole['tail_count']==90
    assert whole['low_1pct_fps']==pytest.approx(90/math.fsum(values[:90]))
    segment_mean=sum(r['low_1pct_fps'] for r in book.records)/2
    assert whole['low_1pct_fps']!=pytest.approx(segment_mean)
    assert whole['relative_long_count']==sum(r['relative_long_count'] for r in book.records)
    assert whole['relative_long_per_minute']==pytest.approx(whole['relative_long_count']/whole['measured_seconds']*60)
    assert whole['end_reason']=='measurement_complete' and whole['conditions_recorded']==1
    assert book.report()['measurement']==whole


def test_measurement_comparison_uses_measurements_not_fragments():
    def measure(values, condition):
        book=summary(values);book.set_condition(condition)
        book.boundary(1e6,'measurement_stop')
        return book.measurement()
    before=measure([.01,.01,.01,.04]*1500,'A')
    after=measure([.0125]*6000,'B')
    result=compare(before,after)
    assert result['status'] in ('tradeoff','descriptive_only')
    assert result['low_1pct_fps_delta']>0 and result['long_per_minute_delta']<0


def test_condition_summary_groups_segment_values_with_median_and_range(tmp_path):
    from mabinogi_addon.optimization.frame_summary import condition_summary, load_reports
    reports=[]
    for condition, gap in (('기본',.05),('기본',.04),('7+1',.02)):
        book=summary(([.01]*99+[gap])*50);book.set_condition(condition)
        book.boundary(1e6,'measurement_stop')
        reports.append(book.report())
    reports.append(dict(reports[0]))  # 수집 모드 파일과 요약 저장이 같은 구간을 담은 경우
    for n, report in enumerate(reports):
        (tmp_path/f'frames-{n}.json').write_text(json.dumps(report),encoding='utf-8')
    (tmp_path/'frames-x.partial').write_text('{',encoding='utf-8')
    (tmp_path/'broken.json').write_text('{',encoding='utf-8')
    result={item['condition']:item for item in condition_summary(load_reports(tmp_path))}
    assert set(result)=={'기본','7+1'}
    base=result['기본']
    assert base['segments']==2 and base['measurements']==2
    lows=sorted(r['segments'][0]['low_1pct_fps'] for r in reports[:2])
    assert base['segment_low_1pct_fps']['minimum']==pytest.approx(lows[0])
    assert base['segment_low_1pct_fps']['maximum']==pytest.approx(lows[1])
    assert base['segment_low_1pct_fps']['median']==pytest.approx(sum(lows)/2)
    assert base['measurement_low_1pct_fps']['count']==2


def test_condition_summary_is_independent_of_file_order():
    # 0.12.0 QA: 수집 모드는 구간마다 파일(구간 1개 + 그 시점 측정 집계)을 남기고 이름이 무작위라 읽는 순서가 바뀐다.
    from itertools import permutations
    from mabinogi_addon.optimization.frame_summary import condition_summary
    book=FrameSummary();book.activate('a',0);files=[]
    def closed(record):
        report=book.report();report['segments']=[record];files.append(json.loads(json.dumps(report)))
    book.closed_callback=closed
    stamp=0
    for minute,(gap,name) in enumerate(((.05,''),(.03,'7+1'),(.04,'7+1'))):
        book.set_condition(name)
        for n in range(5000):
            value=gap if n%100==0 else .01
            stamp+=value;book.interval('a',stamp,value)
        book.boundary(stamp+.001,'measurement_stop' if minute==2 else 'collection_toggle')
    assert len(files)>=3
    final=book.measurement()['low_1pct_fps']
    shapes=set()
    for order in permutations(files):
        result={g['condition']:g for g in condition_summary(list(order))}
        assert result['7+1']['measurement_low_1pct_fps']['median']==pytest.approx(final)
        shapes.add(tuple((k,g['segments']) for k,g in sorted(result.items())))
    assert len(shapes)==1
    assert dict(next(iter(shapes)))['(조건 이름 없음)']>=1  # 이름 입력 전 구간은 그 구간 기록의 조건으로 묶임


def test_late_batched_delivery_keeps_one_observed_segment_and_condition_summary():
    # 0.13.3: 60FPS 이벤트가 3초씩 묶여 늦게 도착해도 순서·간격이 정상이면 한 구간으로 이어진다.
    from mabinogi_addon.optimization.frame_summary import condition_summary
    book=FrameSummary();book.set_condition('기본')
    stream=FrameStream(7,1_000_000,book)
    stream.feed('Application,ProcessID,SwapChainAddress,QPCTime,msBetweenPresents',100)
    stamp=100.0
    for batch in range(6):                       # 6묶음 × 3초 = 18초
        lines=[]
        for n in range(180):
            stamp+=1/60
            lines.append(f'game,7,0x1,{round(stamp*1_000_000)},{1000/60:.6f}')
        arrival=stamp+3.0                         # 묶음 전체가 3초 늦게 도착
        for line in lines: stream.feed(line,arrival)
    stream.boundary(stamp+3.1,'measurement_stop')
    assert len(book.records)==1
    record=book.records[0]
    assert record['quality']=='observed' and record['end_reason']=='measurement_stop'
    assert record['valid_intervals']>=1000 and book.rejected.get('stale_delivery') is None
    assert '50~100FPS' in stream.delay_report()
    result=condition_summary([book.report()])
    assert result and result[0]['condition']=='기본' and result[0]['segments']==1


def test_events_queued_before_focus_boundary_are_still_dropped():
    book=FrameSummary()
    stream=FrameStream(7,1_000_000,book)
    stream.feed('Application,ProcessID,SwapChainAddress,QPCTime,msBetweenPresents',100)
    stream.boundary(105,'inactive')
    for n in range(50):                          # 경계(105초) 이전 시각의 이벤트가 늦게 도착
        stream.feed(f'game,7,0x1,{round((104+n*.02)*1_000_000)},20',105.5)
    assert book.current() is None and not stream.sources


def test_segment_records_usage_average_and_process_states_and_condition_summary_flags_mix():
    # FPS 명세 9절: 구간마다 CPU(가장 바쁜 코어)·GPU 사용률 평균과 게임 선호도·우선순위를 남기고,
    # 조건별 정리에서 한 조건 안에 선호도·우선순위가 둘 이상이면 섞였다고 표시한다.
    from mabinogi_addon.optimization.frame_summary import FrameSummary, condition_summary
    smt = dict(affinity='코어당 1개(SMT 끔으로 보임 · 논리 CPU 8개)', priority='높음')
    full = dict(affinity='전체(논리 CPU 16개)', priority='보통')
    book = FrameSummary(); book.set_condition('기본'); book.activate('a', 0)
    book.observe(dict(cpu=99.0, gpu=99.0, process=smt))  # 프레임 표본 전: 버림
    t = 0
    for n in range(7000):
        t += .01; book.interval('a', t, .01)
        if n % 100 == 0:
            first_segment = not book.records
            book.observe(dict(cpu=80.0 if first_segment else 60.0, gpu=50.0, process=full if first_segment else smt))
    first = book.records[0]
    assert first['game_cpu_thread_avg_percent'] == 80.0 and first['gpu_avg_percent'] == 50.0
    assert first['process_states'] == [full]
    current = book.current()
    assert current['game_cpu_thread_avg_percent'] == 60.0 and current['process_states'] == [smt]
    book.boundary(t + .001, 'measurement_stop')
    assert book.measurement()['process_states'] == [full, smt]
    groups = condition_summary([book.report()])
    assert groups[0]['process_mixed'] and groups[0]['process_states'] == [full, smt]
    assert groups[0]['game_cpu_percent']['minimum'] == 60.0 and groups[0]['cpu_busiest_percent'] is None and groups[0]['gpu_percent']['median'] == 50.0


def test_affinity_and_priority_descriptions():
    from mabinogi_addon.system.perf_metrics import describe_affinity, describe_priority
    cores = tuple((2 * i, 2 * i + 1) for i in range(8))  # 8코어 16스레드
    every = (1 << 16) - 1
    assert describe_affinity(every, every, cores) == '전체(논리 CPU 16개)'
    even = sum(1 << (2 * i) for i in range(8))  # 라쏘 'SMT 끔'(짝수 CPU)
    assert describe_affinity(even, every, cores) == '코어당 1개(SMT 끔으로 보임 · 논리 CPU 8개)'
    assert describe_affinity(0b1111, every, cores) == '논리 CPU 4개(물리 코어 2개)'
    assert describe_affinity(even, every) == '논리 CPU 8개/16개'
    assert describe_priority(0x80) == '높음' and describe_priority(0x20) == '보통'
    assert describe_priority(0x1234).startswith('알 수 없음')


def test_old_core_based_cpu_reports_stay_separate_from_game_cpu():
    # FPS 명세 10.4: 0.16.0 자료의 '가장 바쁜 코어'와 새 '게임 CPU(가장 바쁜 스레드)'를 섞어 비교하지 않는다.
    from mabinogi_addon.optimization.frame_summary import condition_summary
    def report(session, field, value):
        record = dict(index=1, end_reason='window_complete', quality='observed', low_1pct_fps=50.0,
                      relative_long_per_minute=10.0, measured_seconds=60.0, condition='기본', **{field: value})
        return dict(session=session, condition='기본', segments=[record])
    groups = condition_summary([report('a', 'cpu_busiest_avg_percent', 71.0),
                                report('b', 'game_cpu_thread_avg_percent', 98.0)])
    assert groups[0]['cpu_busiest_percent']['median'] == 71.0
    assert groups[0]['game_cpu_percent']['median'] == 98.0
