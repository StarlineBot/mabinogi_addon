"""Read-only subscriptions to a single producer's immutable latest frame."""
from time import monotonic
from .base import FrameSource


class SharedFrame:
    def __init__(self):
        self.latest = None

    def publish(self, frame):
        self.latest = None if frame is None else (monotonic(), frame.copy())

    def source(self):
        return SharedFrameSource(self)


class SharedFrameSource(FrameSource):
    def __init__(self, shared):
        self.shared = shared
        self.closed = False

    def grab(self):
        latest = self.shared.latest
        if self.closed or latest is None or monotonic()-latest[0] > 1:
            return None
        return latest[1]

    def close(self):
        self.closed = True
