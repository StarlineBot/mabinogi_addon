"""유한 구간의 정확한 slowest-1%-mean 집계. 원본 이벤트는 디스크에 쓰지 않는다."""
import json
import math
import statistics
from uuid import uuid4


class FrameSummary:
    MAX_SAMPLES = 16384
    MAX_SEGMENTS = 128
    MAX_EVENTS = 512
    WINDOW_SECONDS = 60.0

    def __init__(self):
        self.id = uuid4().hex
        self.records = []
        self.events = []
        self.rejected = {}
        self.anomalies = []
        self.samples = []
        self.context = {}
        self.source = None
        self.origin = None
        self.full = False
        self.last_reason = 'waiting'
        self.revision = 0
        self.closed_callback = None

    def relative(self, stamp):
        if self.origin is None:
            self.origin = stamp
        return round(stamp - self.origin, 6)

    def reject(self, reason, stamp, duration=None):
        self.rejected[reason] = self.rejected.get(reason, 0) + 1
        if len(self.anomalies) < 8:
            self.anomalies.append(dict(reason=reason, at_seconds=self.relative(stamp), interval_seconds=duration))

    def boundary(self, stamp, reason):
        if not self.full and (self.samples or reason != self.last_reason):
            if len(self.events) >= self.MAX_EVENTS:
                self.full = True
            else:
                self.events.append(dict(at_seconds=self.relative(stamp), reason=reason))
        if self.samples:
            record = self.current()
            record.update(end_reason=reason, boundary_seconds=self.relative(stamp))
            self.records.append(record)
            self.samples = []
            self.revision += 1
            if len(self.records) >= self.MAX_SEGMENTS:
                self.full = True
            if self.closed_callback:
                self.closed_callback(record)
        self.source = None
        self.last_reason = reason

    def set_context(self, stamp, context):
        value = json.loads(json.dumps(context, allow_nan=False))
        if value != self.context:
            self.boundary(stamp, 'optimization_or_target_change')
            self.context = value

    def activate(self, source, stamp):
        if source != self.source:
            self.boundary(stamp, 'swapchain_change' if source else 'ambiguous_or_missing_swapchain')
            self.source = source
            return False
        return source is not None

    def interval(self, source, stamp, duration):
        if self.full or source is None:
            return
        if not math.isfinite(stamp) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('finite positive frame interval required')
        if source != self.source:
            self.activate(source, stamp)
            return
        if self.context.get('observation') == 'transition_unconfirmed':
            return
        if self.samples and stamp <= self.samples[-1][0]:
            self.boundary(stamp, 'out_of_order')
            return
        self.relative(stamp - duration)
        self.samples.append((stamp, duration))
        self.revision += 1
        if len(self.samples) >= self.MAX_SAMPLES or stamp - self.samples[0][0] >= self.WINDOW_SECONDS:
            self.boundary(stamp, 'sample_capacity' if len(self.samples) >= self.MAX_SAMPLES else 'window_complete')
            self.source = source

    def current(self):
        if not self.samples:
            return None
        intervals = [duration for _, duration in self.samples]
        ordered = sorted(intervals)
        count = len(ordered)
        total = math.fsum(ordered)
        mean = total / count
        tail_count = math.ceil(count / 100)
        median = statistics.median(ordered)
        long = [(stamp, duration) for stamp, duration in self.samples if duration > 2 * median]
        start = self.samples[0][0] - intervals[0]
        windows = max(0, math.floor(self.samples[-1][0] - start + 1e-9))
        bins = {}
        for stamp, _ in self.samples:
            offset = stamp - start
            if 0 < offset <= windows + 1e-9:
                index = min(windows - 1, max(0, math.ceil(offset - 1e-9) - 1))
                bins[index] = bins.get(index, 0) + 1

        return dict(index=len(self.records) + 1, source=self.source, context=self.context,
            start_seconds=self.relative(self.samples[0][0] - intervals[0]),
            end_seconds=self.relative(self.samples[-1][0]), valid_intervals=count,
            measured_seconds=total, average_fps=count / total,
            low_1pct_fps=tail_count / math.fsum(ordered[-tail_count:]) if count >= 100 else None,
            tail_count=tail_count if count >= 100 else 0,
            slowest_tail_mean_ms=math.fsum(ordered[-tail_count:])/tail_count*1000 if count>=100 else None,
            max_1s_fps=max(bins.values(), default=0) if windows else None, completed_1s_windows=windows,
            max_definition='maximum event count in complete consecutive (start,start+1s] windows; partial windows excluded',

            quality='observed' if count >= 100 else 'insufficient_samples',
            median_ms=median * 1000, max_ms=ordered[-1] * 1000,
            variation_percent=math.sqrt(math.fsum((value / mean - 1) ** 2 for value in ordered) / count) * 100,
            relative_long_count=len(long), relative_long_seconds=math.fsum(d for _, d in long),
            longest=[dict(at_seconds=self.relative(t), milliseconds=d*1000)
                     for t, d in sorted(self.samples, key=lambda sample: sample[1], reverse=True)[:8]],
            end_reason='collecting')

    def report(self):
        current = self.current()
        return dict(schema=1, session=self.id, metric='game submitted Present intervals',
            definition='1% low = 1 / mean(largest ceil(N/100) intervals); N>=100; not P99',
            relative_long_definition='interval > 2 * segment median; descriptive, not a performance threshold',
            limits=dict(segment_seconds=self.WINDOW_SECONDS, samples=self.MAX_SAMPLES, segments=self.MAX_SEGMENTS, events=self.MAX_EVENTS),
            raw_events_saved=False, transitions=self.events, rejected_counts=self.rejected, anomaly_examples=self.anomalies, full=self.full, last_reason=self.last_reason,
            comparison='Different target, scene, optimization state or interrupted segments are not proof of improvement.',
            segments=self.records + ([current] if current else []))


def compare(previous, current):
    """성능 수준과 변동을 분리한 기술 통계. 원인/최적화 성공을 판정하지 않는다."""
    bad = ('collector_error', 'out_of_order_or_missing_event', 'stale_delivery', 'stale_no_events')
    if (not previous or not current or any(r['quality'] != 'observed' or r['max_1s_fps'] is None
            or r['end_reason'] in bad for r in (previous, current))):
        return dict(status='insufficient', message='비교 보류 · 유효 표본/완전한 1초 창과 수집 품질을 확인하세요.')
    average_delta = current['average_fps'] - previous['average_fps']
    maximum_delta = current['max_1s_fps'] - previous['max_1s_fps']
    variability_delta = current['variation_percent'] - previous['variation_percent']
    long_rate_delta = (current['relative_long_count'] / current['valid_intervals']
                      - previous['relative_long_count'] / previous['valid_intervals'])
    tradeoff = ((average_delta < -1e-9 or maximum_delta < 0)
                and (variability_delta < -1e-9 or long_rate_delta < -1e-9))
    return dict(status='tradeoff' if tradeoff else 'descriptive_only',
        average_fps_delta=average_delta, max_1s_fps_delta=maximum_delta,
        low_1pct_fps_delta=current['low_1pct_fps'] - previous['low_1pct_fps'],
        variation_percentage_points_delta=variability_delta, long_fraction_delta=long_rate_delta,
        same_recorded_context=previous['context'] == current['context'] and previous['source'] == current['source'],
        message=('성능 수준 하락과 변동 감소가 함께 관측됐어요(절충). ' if tradeoff else '') +
                '최적화 성공 판정이 아니에요. 같은 장면·조건·측정 길이에서 다시 비교하세요.')


REASONS = {
    'collecting':'집계 중', 'window_complete':'60초 구간 완료', 'sample_capacity':'표본 상한',
    'optimization_state_observed':'최적화 확인 상태 변경', 'optimization_or_target_change':'설정·대상 변경',
    'optimization_start_request':'최적화 시작 요청', 'optimization_stop_request':'CPU 원복 요청',
    'network_restore_request':'네트워크 원복 요청', 'optimization_transition_unconfirmed':'설정 변경 중·확인 대기',
    'manual_swapchain_selection':'렌더링 대상 선택', 'swapchain_change':'렌더링 대상 변경',
    'ambiguous_or_missing_swapchain':'렌더링 대상 복수·미확인', 'out_of_order_or_missing_event':'역순·누락 감지',
    'stale_delivery':'늦은 이벤트 수신', 'collector_header_restart':'수집기 형식 재시작',
    'game_identity_change':'게임 실행 변경', 'game_exit':'게임 종료', 'collector_error':'수집 오류',
    'focus_target_or_clock_gap':'활성 상태·창·시계 공백 변경', 'inactive':'게임 비활성',
    'context_boundary':'수집 조건 변경', 'measurement_stop':'측정 중단', 'collection_toggle':'수집 모드 변경',
}
