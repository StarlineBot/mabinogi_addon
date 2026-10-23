"""게임 프로세스 PCM16 타임라인. 누락 구간을 무음/다른 소리로 채우지 않는다.

WASAPI 루프백 묶음의 시각(QPC)은 수 ms 흔들린다. 허용 오차 안의 차이는 지터로 보고 직전 끝에 샘플 단위로
이어 붙인다. 그보다 큰 공백(게임 무음으로 묶음이 끊겼다 재개 등)은 새 '연속 구간(run)'으로 기록하고,
영상은 소리가 연속인 구간에서만 만든다(공백 시간은 저장 영상에서 빠짐). 겹침은 계속 거부한다.
"""
from collections import deque
from threading import Condition
import logging
import math
import time

_log = logging.getLogger(__name__)


JITTER_US = 3000  # 루프백 시각 흔들림 허용(약 3ms). 이 안이면 연속으로 이어 붙인다
# 이보다 작은 겹침은 중복 부분만 잘라 이어 붙인다(첫 묶음 지터 고정·장치 시계와 QPC 드리프트 누적, 0.13.2 QA).
# 소리를 만들지 않고 이미 받은 시간대의 중복 샘플만 버린다. 이보다 큰 겹침은 시각 이상으로 보고 거부한다.
OVERLAP_TRIM_US = 100_000


class PcmTimeline:
    def __init__(self, rate, channels, max_bytes):
        if any(type(v) is not int or v <= 0 for v in (rate, channels, max_bytes)):
            raise ValueError('explicit audio bounds required')
        self.rate, self.block, self.limit = rate, channels * 2, max_bytes
        self._packets = deque()
        self._bytes = 0
        self._end = None
        self._runs = []  # [시작, 끝] 연속 구간. 큰 공백마다 새 구간
        self.gaps = 0
        self.max_jitter_us = 0  # 허용 범위 안에서 관측한 가장 큰 시각 차이(실측 판단용)
        self.trimmed = 0  # 겹친 앞부분을 잘라 이어 붙인(또는 통째로 버린) 묶음 수
        self.max_trim_us = 0
        self._closed = False
        self._condition = Condition()

    @property
    def start(self):
        with self._condition:
            return self._packets[0][0] if self._packets else None

    def push(self, data, stamp_us):
        if type(data) is not bytes or not data or len(data) % self.block or type(stamp_us) is not int:
            raise ValueError('invalid timestamped PCM16 packet')
        with self._condition:
            if self._closed:
                raise RuntimeError('audio timeline closed')
            continuing = False
            if self._end is not None:
                delta = stamp_us - self._end
                if delta < -OVERLAP_TRIM_US:
                    _log.warning('블랙박스 소리 겹침 %+.0fµs로 녹화 중단(자르기 허용 %dµs)', delta, OVERLAP_TRIM_US)
                    raise ValueError('audio overlap; refusing to merge or synthesize sound')
                if delta < -JITTER_US:
                    # 이미 받은 시간대와 겹친 앞부분(샘플 단위)만 버리고 나머지를 끝에 이어 붙인다.
                    drop = round(-delta * self.rate / 1_000_000) * self.block
                    self.trimmed += 1
                    self.max_trim_us = max(self.max_trim_us, round(-delta))
                    if self.trimmed <= 5 or self.trimmed % 100 == 0:
                        _log.info('블랙박스 소리 겹침 %+.0fµs · 중복 %d샘플 잘라 이어 붙임(누적 %d회, 최대 %dµs)',
                                  delta, drop // self.block, self.trimmed, self.max_trim_us)
                    if drop >= len(data):
                        return  # 묶음 전체가 이미 받은 시간대: 버린다
                    data, delta = data[drop:], 0
                if delta <= JITTER_US:
                    self.max_jitter_us = max(self.max_jitter_us, round(abs(delta)))
                    stamp_us, continuing = self._end, True  # 지터: 샘플 수 기준으로 연속 배치
            if self._bytes + len(data) > self.limit:
                raise BufferError('audio timeline capacity exhausted')
            end = stamp_us + len(data) / self.block * 1_000_000 / self.rate
            self._packets.append((stamp_us, end, data))
            self._bytes += len(data)
            if continuing:
                self._runs[-1][1] = end
            else:
                if self._end is not None:
                    self.gaps += 1  # 큰 공백: 채우지 않고 새 연속 구간
                    if self.gaps <= 5 or self.gaps % 100 == 0:
                        _log.info('블랙박스 소리 공백 %+.0fµs · 새 연속 구간(누적 %d회, 허용 범위 최대 지터 %dµs)',
                                  stamp_us - self._end, self.gaps, self.max_jitter_us)
                self._runs.append([stamp_us, end])
            self._end = end
            self._condition.notify_all()

    def run_within(self, start_us, end_us):
        """[start, end)와 겹치는 첫 연속 소리 구간의 교집합 (시작, 끝). 없으면 None."""
        with self._condition:
            for run_start, run_end in self._runs:
                if run_end > start_us and run_start < end_us:
                    return max(start_us, run_start), min(end_us, run_end)
            return None

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def covered_end(self, requested_end, *, timeout, partial=False):
        """확보한 소리의 끝. 종료 때(또는 partial이면 시간 제한 때) 실제 확보한 만큼만 반환한다."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while (self._end is None or self._end < requested_end) and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if partial:
                        break  # 게임 무음: 기다리지 않고 지금까지 확보한 소리만 쓴다
                    raise TimeoutError('audio coverage deadline exceeded')
                self._condition.wait(remaining)
            return min(requested_end, self._end) if self._end is not None else None

    def slice(self, start_us, end_us, *, timeout):
        if end_us <= start_us or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('finite nonempty audio slice required')
        deadline = time.monotonic() + timeout
        with self._condition:
            while (self._end is None or self._end < end_us) and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('audio did not cover the video interval')
                self._condition.wait(remaining)
            if (not self._packets or self._packets[0][0] > start_us or self._end < end_us
                    or not any(r[0] <= start_us and end_us <= r[1] for r in self._runs)):
                raise ValueError('audio interval incomplete; no silent fallback')  # 소리 공백에 걸친 구간 포함
            parts = []
            for start, end, data in self._packets:
                if end <= start_us or start >= end_us:
                    continue
                first = max(0, round((start_us - start) * self.rate / 1_000_000))
                last = min(len(data) // self.block, round((end_us - start) * self.rate / 1_000_000))
                parts.append(data[first * self.block:last * self.block])
            result = b''.join(parts)
            expected = round((end_us - start_us) * self.rate / 1_000_000)
            if abs(len(result) // self.block - expected) > 1:
                raise ValueError('audio sample count differs from interval')
            while self._packets and self._packets[0][1] <= end_us:
                self._bytes -= len(self._packets.popleft()[2])
            while len(self._runs) > 1 and self._runs[0][1] <= end_us:
                self._runs.pop(0)
            return result
