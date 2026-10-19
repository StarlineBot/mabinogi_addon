"""Bounded lossless timer collection, with no Qt or device access."""

from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import threading
import time
import uuid

import cv2
import numpy as np

MAX_SHOTS = 900
MAX_BYTES = 100 * 1024 * 1024
MAX_PIXELS = 1_000_000


def digit_mask(frame):
    low = frame.min(axis=2)
    high = frame.max(axis=2)
    return (low > 180) & (high.astype(np.int16) - low < 45)


class CaptureSession:
    def __init__(self, root: Path):
        self.path = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex)
        self.count = self.bytes = 0
        self.last_mask = None
        self.last_raw = None
        self._pending_raw = None
        self.last_at = float("-inf")
        self.thread = None
        self.results = queue.Queue(maxsize=1)
        self.cancelled = threading.Event()

    def submit(self, frame, metadata, *, now=None, force=False):
        now = time.monotonic() if now is None else now
        if self.thread is not None or self.cancelled.is_set() or now - self.last_at < 1:
            return False
        if (frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8
                or min(frame.shape[:2]) <= 0
                or frame.shape[0] * frame.shape[1] > MAX_PIXELS):
            raise ValueError("invalid timer capture")
        mask = digit_mask(frame)
        raw_time = metadata.get('raw_time')
        if type(raw_time) is not int or not 0 <= raw_time <= 900:
            raw_time = None
        if not force and raw_time is not None and raw_time == self.last_raw:
            return False
        if (not force and (raw_time is None or self.last_raw is None)
                and self.last_mask is not None and mask.shape == self.last_mask.shape
                and np.count_nonzero(mask != self.last_mask) < max(2, min(mask.sum(), self.last_mask.sum()) * .04)):
            return False
        if self.count >= MAX_SHOTS or self.bytes >= MAX_BYTES:
            raise ValueError("수집 한도에 도달했습니다.")
        self.last_at = now
        pixels = frame.copy()
        self._pending_raw = raw_time
        read_status = ('recognized' if raw_time is not None else 'uncertain') if 'read_status' in metadata else 'not_implemented'
        metadata = dict(metadata, captured_at=datetime.now(timezone.utc).isoformat(),
                        raw_time=raw_time, read_status=read_status, sequence=self.count + 1,
                        change_method="recognized-time-or-bright-neutral-mask-v2", shape=list(frame.shape))
        self.thread = threading.Thread(target=self._write, args=(pixels, mask, metadata), daemon=True,
                                       name="halo-png-write")
        self.thread.start()
        return True

    def _write(self, frame, mask, metadata):
        try:
            ok, encoded = cv2.imencode(".png", frame)
            if not ok:
                raise OSError("PNG encoding failed")
            png = encoded.tobytes()
            meta = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
            size = len(png) + len(meta)
            if self.bytes + size > MAX_BYTES:
                raise OSError("수집 용량 한도에 도달했습니다.")
            if self.cancelled.is_set():
                self.results.put((None, 0, "cancelled"))
                return
            self.path.mkdir(parents=True, exist_ok=True)
            partial = self.path / f"{self.count+1:04d}.pending"
            partial.mkdir()
            (partial / "frame.png").write_bytes(png)
            (partial / "metadata.json").write_bytes(meta)
            if self.cancelled.is_set():
                self.results.put((None, 0, "cancelled"))
                return
            partial.rename(self.path / f"{self.count+1:04d}")
            self.results.put((mask, size, ""))
        except Exception:
            self.results.put((None, 0, "수집 파일을 저장하지 못했습니다. 경로 권한과 저장 공간을 확인하세요."))

    def poll(self):
        if self.thread is None or self.thread.is_alive():
            return None
        self.thread.join()
        self.thread = None
        mask, size, error = self.results.get_nowait()
        if not error:
            self.count += 1
            self.bytes += size
            self.last_mask = mask
            self.last_raw = self._pending_raw
        return error

    def stop(self):
        self.cancelled.set()
