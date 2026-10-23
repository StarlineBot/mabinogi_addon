"""유한 구간의 정확한 slowest-1%-mean 집계. 원본 이벤트는 디스크에 쓰지 않는다."""
import json
import math
import statistics
from array import array
from uuid import uuid4

import numpy as np

CONDITION_MAX = 48  # 측정 조건 이름 최대 길이(예: '7+1 SMT끔 · Vulkan · 제한없음')


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
        self.condition = ''
        # 측정 1회 전체의 정확한 1% low를 위해 완료 구간의 간격을 측정 동안만 메모리에 둔다(8바이트×최대
        # 128구간×16,384 = 16MiB 상한, 디스크에 쓰지 않음). 측정 집계는 구간이 닫힐 때만 다시 계산한다.
        self._closed_intervals = array('d')
        self._measurement = None

    def set_condition(self, text):
        self.condition = ' '.join(str(text or '').split())[:CONDITION_MAX]

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
            self._closed_intervals.extend(duration for _, duration in self.samples)
            self._measurement = None
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
            relative_long_per_minute=len(long) / total * 60,  # 구간 길이가 달라도 비교할 수 있게 분당 횟수
            condition=self.condition,
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
            condition=self.condition, measurement=self.measurement(),
            measurement_definition='all completed segments of one start-stop measurement; 1% low recomputed from all intervals, '
                                   'long gaps summed from per-segment median rule',
            segments=self.records + ([current] if current else []))

    def measurement(self):
        """측정 1회(시작~중단)의 완료 구간 전체 집계. 구간 1% low 평균이 아니라 전체 간격으로 다시 계산한다."""
        if self._measurement is not None or not self.records:
            return self._measurement
        values = np.frombuffer(self._closed_intervals, dtype=np.float64)
        count = len(values)
        total = float(math.fsum(values))
        tail_count = math.ceil(count / 100)
        tail = np.partition(values, count - tail_count)[count - tail_count:] if count >= 100 else None
        long_count = sum(r['relative_long_count'] for r in self.records)
        contexts = []
        for record in self.records:
            if (record['context'], record['source']) not in contexts:
                contexts.append((record['context'], record['source']))
        maxima = [r['max_1s_fps'] for r in self.records if r['max_1s_fps'] is not None]
        interrupted = [r['end_reason'] for r in self.records if r['end_reason'] in INTERRUPTED]
        self._measurement = dict(condition=self.condition, segments=len(self.records), valid_intervals=count,
            measured_seconds=total, average_fps=count / total,
            low_1pct_fps=tail_count / float(math.fsum(tail)) if tail is not None else None,
            tail_count=tail_count if tail is not None else 0,
            variation_percent=float(np.std(values) / np.mean(values) * 100),
            relative_long_count=long_count, relative_long_per_minute=long_count / total * 60,
            max_1s_fps=max(maxima) if maxima else None,
            quality='observed' if count >= 100 and maxima else 'insufficient_samples',
            conditions_recorded=len(contexts), interrupted_segments=len(interrupted),
            end_reason=interrupted[0] if interrupted else 'measurement_complete',
            context=contexts[0][0], source=contexts[0][1] if len(contexts) == 1 else None)
        return self._measurement


INTERRUPTED = ('collector_error', 'out_of_order_or_missing_event', 'stale_delivery', 'stale_no_events')

# 잡음 기준(명세 FPS 7절, 개발 제시값). 같은 조건 반복 측정의 흔들림을 '절충'으로 부르지 않기 위한
# 최소 차이이며 성능 합격선이 아니다. 실험 결과로 조정할 수 있다.
NOISE = dict(average_fps_abs=1.0, average_fps_rel=0.02, max_fps_abs=2.0, max_fps_rel=0.02,
             low_fps_abs=1.0, low_fps_rel=0.05, variation_pp=1.0, long_per_minute_abs=3.0, long_per_minute_rel=0.25)


def _long_per_minute(record):
    if record.get('relative_long_per_minute') is not None:
        return record['relative_long_per_minute']
    return record['relative_long_count'] / record['measured_seconds'] * 60  # 이전 형식 요약


def compare(previous, current):
    """성능 수준과 변동을 분리한 기술 통계. 원인/최적화 성공을 판정하지 않는다."""
    if (not previous or not current or any(r['quality'] != 'observed' or r['max_1s_fps'] is None
            or r['end_reason'] in INTERRUPTED for r in (previous, current))):
        return dict(status='insufficient', message='비교 보류 · 유효 표본/완전한 1초 창과 수집 품질을 확인하세요.')
    n = NOISE
    average_delta = current['average_fps'] - previous['average_fps']
    maximum_delta = current['max_1s_fps'] - previous['max_1s_fps']
    low_delta = current['low_1pct_fps'] - previous['low_1pct_fps']
    variability_delta = current['variation_percent'] - previous['variation_percent']
    long_rate_delta = (current['relative_long_count'] / current['valid_intervals']
                      - previous['relative_long_count'] / previous['valid_intervals'])
    long_minute_delta = _long_per_minute(current) - _long_per_minute(previous)
    # 각 지표의 잡음 기준: 이 범위 안의 차이는 '변화'로 세지 않는다.
    average_noise = max(n['average_fps_abs'], n['average_fps_rel'] * previous['average_fps'])
    maximum_noise = max(n['max_fps_abs'], n['max_fps_rel'] * previous['max_1s_fps'])
    low_noise = max(n['low_fps_abs'], n['low_fps_rel'] * previous['low_1pct_fps'])
    long_noise = max(n['long_per_minute_abs'], n['long_per_minute_rel'] * _long_per_minute(previous))
    level_down = average_delta < -average_noise or maximum_delta < -maximum_noise
    steadier = variability_delta < -n['variation_pp'] or long_minute_delta < -long_noise
    tradeoff = level_down and steadier
    within_noise = (abs(average_delta) <= average_noise and abs(maximum_delta) <= maximum_noise
                    and abs(low_delta) <= low_noise and abs(variability_delta) <= n['variation_pp']
                    and abs(long_minute_delta) <= long_noise)
    return dict(status='tradeoff' if tradeoff else 'within_noise' if within_noise else 'descriptive_only',
        average_fps_delta=average_delta, max_1s_fps_delta=maximum_delta, low_1pct_fps_delta=low_delta,
        variation_percentage_points_delta=variability_delta, long_fraction_delta=long_rate_delta,
        long_per_minute_delta=long_minute_delta, within_noise=within_noise,
        noise=dict(average_fps=average_noise, max_1s_fps=maximum_noise, low_1pct_fps=low_noise,
                   variation_pp=n['variation_pp'], long_per_minute=long_noise),
        same_recorded_context=previous['context'] == current['context'] and previous['source'] == current['source'],
        message=('성능 수준 하락과 변동 감소가 함께 관측됐어요(절충). ' if tradeoff else
                 '모든 차이가 잡음 기준 안이에요(같은 조건 반복 수준). ' if within_noise else '') +
                '최적화 성공 판정이 아니에요. 같은 장면·조건·측정 길이에서 다시 비교하세요.')


def _spread(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return dict(count=len(values), median=statistics.median(values), minimum=values[0], maximum=values[-1])


def condition_summary(reports):
    """저장된 요약(JSON)들을 조건 이름별로 묶어 구간 값의 중앙값·범위를 낸다(명세 FPS 7절).

    원본 간격을 저장하지 않으므로 조건 전체 1% low를 재계산하지 않는다. 구간 1% low를 평균해 전체 1% low로
    부르지 않는다(3절). 측정 1회 전체 1% low는 저장된 측정 집계가 있을 때 그 값들의 범위만 따로 보인다.
    수집 모드 파일과 '요약 저장' 파일이 같은 구간을 담을 수 있어 (측정 id, 구간 번호)로 중복을 뺀다.

    결과는 파일을 읽는 순서와 무관해야 한다(수집 모드 파일명은 무작위): 구간은 구간 기록의 조건 이름으로
    묶고(이전 형식은 요약 조건), 측정 전체 값은 측정마다 가장 많이 진행된 집계 하나만 쓴다."""
    def label(value):
        return ' '.join(str(value or '').split()) or '(조건 이름 없음)'

    groups, seen, best = {}, set(), {}
    for report in reports:
        if not isinstance(report, dict) or not isinstance(report.get('segments'), list):
            continue
        session = report.get('session')
        for record in report['segments']:
            try:
                key = (session, record['index'])
                if key in seen or record.get('end_reason') == 'collecting' or record.get('quality') != 'observed':
                    continue
                if record.get('end_reason') in INTERRUPTED:
                    continue
                seen.add(key)
                group = groups.setdefault(label(record.get('condition', report.get('condition'))),
                                          dict(low=[], long=[], seconds=0.0, sessions=set()))
                group['low'].append(record['low_1pct_fps'])
                group['long'].append(_long_per_minute(record))
                group['seconds'] += record['measured_seconds']
                group['sessions'].add(session)
            except (KeyError, TypeError, ZeroDivisionError):
                continue
        whole = report.get('measurement')
        if isinstance(whole, dict) and whole.get('low_1pct_fps') is not None:
            # 같은 측정의 집계가 여러 파일에 있으면 구간 수(같으면 유효 간격)가 가장 큰 것 = 마지막 집계
            rank = (whole.get('segments') or 0, whole.get('valid_intervals') or 0)
            if session not in best or rank > best[session][0]:
                best[session] = (rank, label(whole.get('condition', report.get('condition'))), whole['low_1pct_fps'])
    measurements = {}
    for _rank, name, low in best.values():
        measurements.setdefault(name, []).append(low)
    result = []
    for name, group in groups.items():
        if not group['low']:
            continue
        result.append(dict(condition=name, segments=len(group['low']), measurements=len(group['sessions']),
            measured_seconds=group['seconds'], segment_low_1pct_fps=_spread(group['low']),
            segment_long_per_minute=_spread(group['long']),
            measurement_low_1pct_fps=_spread(measurements.get(name, []))))
    return sorted(result, key=lambda item: item['condition'])


def load_reports(folder, limit=512):
    """요약 폴더의 완료 JSON만 읽는다(.partial 제외). 읽지 못한 파일은 건너뛴다."""
    reports = []
    try:
        paths = sorted(p for p in folder.iterdir() if p.suffix == '.json' and p.is_file())[:limit]
    except OSError:
        return reports
    for path in paths:
        try:
            reports.append(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            continue
    return reports


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
