"""게임 프로세스 PCM16 타임라인. 누락 구간을 무음/다른 소리로 채우지 않는다."""
from collections import deque
from threading import Condition
import math
import time


class PcmTimeline:
    def __init__(self, rate, channels, max_bytes):
        if any(type(v) is not int or v <= 0 for v in (rate, channels, max_bytes)):
            raise ValueError('explicit audio bounds required')
        self.rate, self.block, self.limit = rate, channels * 2, max_bytes
        self._packets = deque()
        self._bytes = 0
        self._end = None
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
            if self._end is not None and abs(stamp_us - self._end) > 1_000_000 / self.rate + 1:
                raise ValueError('audio gap or overlap; refusing to synthesize missing sound')
            if self._bytes + len(data) > self.limit:
                raise BufferError('audio timeline capacity exhausted')
            end = stamp_us + len(data) / self.block * 1_000_000 / self.rate
            self._packets.append((stamp_us, end, data))
            self._bytes += len(data)
            self._end = end
            self._condition.notify_all()

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def covered_end(self, requested_end, *, timeout):
        """종료 때만 실제 확보한 끝을 반환한다. 실행 중 누락은 시간 제한 오류다."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while (self._end is None or self._end < requested_end) and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
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
            if not self._packets or self._packets[0][0] > start_us or self._end < end_us:
                raise ValueError('audio interval incomplete; no silent fallback')
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
            return result
