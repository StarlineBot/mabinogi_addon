"""Present-event FPS, independent of Qt repaint/capture rates."""
from collections import deque
import csv
import math


class FrameStream:
    WINDOW = 1.0
    MIN_SPAN = 0.25
    STALE = 2.0
    MAX_FRAMES = 16384
    MAX_SOURCES = 8

    def __init__(self, pid, frequency, summary=None):
        if pid <= 0 or frequency <= 0:
            raise ValueError('Invalid process/clock')
        self.summary = summary
        self.pid, self.frequency = pid, frequency
        self.header = None
        self.time_column = self.interval_column = None
        self.sources = {}
        self.selected = None
        self.cutoff = 0.0
        self.problem = ''

    def boundary(self, now, reason="context_boundary"):
        if self.summary is not None:
            self.summary.boundary(now, reason)
        self.cutoff = now
        self.sources.clear()
        self.problem = ''

    def select(self, source, now):
        self.selected = source
        self.boundary(now, "manual_swapchain_selection")

    def feed(self, line, now):
        try:
            return self._feed(line, now)
        except Exception:
            if self.summary is not None:
                self.summary.reject('invalid_event', now)
                self.summary.boundary(now, 'collector_error')
            raise

    def _feed(self, line, now):
        if len(line) > 16384:
            raise ValueError('프레임 데이터 한도를 초과했어요.')
        row = next(csv.reader([line]))
        if row and row[0].lstrip('\ufeff') == 'Application':
            if self.header is not None:
                self.boundary(now, 'collector_header_restart')
            self.header = [x.lstrip('\ufeff') for x in row]
            columns=set(self.header)
            v1={'QPCTime','msBetweenPresents'} <= columns
            modern={'TimeInQPC','MsBetweenPresents'} <= columns
            if v1 == modern:
                raise ValueError('지원하지 않는 프레임 데이터 형식이에요.')
            if v1:
                self.time_column,self.interval_column='QPCTime','msBetweenPresents'
            elif modern:
                self.time_column,self.interval_column='TimeInQPC','MsBetweenPresents'
            else:
                raise ValueError('지원하지 않는 프레임 데이터 형식이에요.')
            if len(columns)!=len(self.header) or not {'ProcessID','SwapChainAddress'} <= columns:
                raise ValueError('지원하지 않는 프레임 데이터 형식이에요.')
            return
        if not row or all(not field.strip() for field in row):
            return
        if self.header is None:
            raise ValueError('프레임 데이터 헤더를 확인하지 못했어요.')
        if len(row) != len(self.header):
            raise ValueError('프레임 데이터가 손상됐어요.')
        data = dict(zip(self.header, row))
        if int(data['ProcessID']) != self.pid:
            raise ValueError('등록한 게임 이외의 프레임이 감지됐어요.')
        source = data['SwapChainAddress']
        if not 0 < int(source, 16) < 2**64:
            raise ValueError('렌더링 대상 식별값이 잘못됐어요.')
        stamp = int(data[self.time_column]) / self.frequency
        interval = float(data[self.interval_column]) / 1000
        if not math.isfinite(stamp) or not math.isfinite(interval) or interval < 0 or stamp > now + .1:
            raise ValueError('프레임 시각이 잘못됐어요.')
        if stamp <= self.cutoff or now - stamp > self.STALE:
            if stamp > self.cutoff and self.summary is not None:
                self.summary.reject('stale_delivery', now, interval)
                self.summary.boundary(now, 'stale_delivery')
            return  # Queued events from before a focus/sleep/target boundary.
        if source not in self.sources:
            if len(self.sources) >= self.MAX_SOURCES:
                raise ValueError('렌더링 대상이 너무 많아 측정을 중단했어요.')
            self.sources[source] = deque(maxlen=self.MAX_FRAMES)
        events = self.sources[source]
        valid_delta = None
        if events:
            delta = stamp - events[-1]
            if delta <= 0 or abs(delta - interval) > max(2 / self.frequency, .000002):
                if self.summary is not None and self.summary.source == source:
                    self.summary.reject('out_of_order_or_missing_event', now, interval)
                    self.summary.boundary(now, 'out_of_order_or_missing_event')
                events.clear()
                self.problem = '프레임 순서·누락을 감지해 새 구간을 기다려요.'
            else:
                valid_delta = delta
            if len(events) == self.MAX_FRAMES and stamp - events[0] < self.WINDOW:
                raise ValueError('프레임 버퍼 한도를 초과했어요. 값을 추정하지 않아요.')
        events.append(stamp)
        if self.summary is not None:
            candidates = [key for key, values in self.sources.items() if values and now-values[-1] <= self.STALE]
            effective = self.selected if self.selected in candidates else None
            if self.selected is None and len(candidates) == 1:
                effective = candidates[0]
            ready = self.summary.activate(effective, stamp)
            if ready and effective == source and valid_delta is not None:
                self.summary.interval(source, stamp, valid_delta)
        while len(events) > 2 and stamp - events[0] > self.WINDOW:
            events.popleft()

    def snapshot(self, now):
        available = sorted(key for key, events in self.sources.items() if events and now-events[-1] <= self.STALE)
        source = self.selected
        if source is None and len(available) == 1:
            source = available[0]
        status = '렌더링 대상을 선택해 주세요.' if len(available)>1 and source is None else '측정 준비 중 · 최신 프레임을 기다려요.'
        events = self.sources.get(source, ())
        fps = None
        if len(events) >= 2 and now-events[-1] <= self.STALE:
            span = events[-1]-events[0]
            if span >= self.MIN_SPAN:
                fps = (len(events)-1)/span
                status = f'{fps:.1f} FPS · 게임 제출 프레임'
                self.problem = ''
        return dict(fps=fps, sources=available, source=source, status=self.problem or status)
