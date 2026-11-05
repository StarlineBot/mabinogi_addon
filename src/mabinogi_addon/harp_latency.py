"""하프 채널 연결 시간(docs/harp-channel-tcp-spec.md) — 화면과 무관한 측정·통계.

채널마다 TCP 연결을 한 번 맺고(데이터는 보내지 않음) 바로 닫아, 연결에 걸린 시간을 잰다. 대략 왕복 한 번(RTT)이다.
게임 안 핑·채널 혼잡도와는 다르다. 일반 소켓만 써서 OS 의존 코드가 아니다(맥·리눅스에서 로컬 서버로 시험).
"""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import errno
import json
from pathlib import Path
import selectors
import socket
import statistics
import threading
from time import perf_counter

from . import paths

# 0.40.1: exe(PyInstaller)는 assets를 _MEIPASS/assets에 넣는다 — __file__ 기준이면 exe에서 못 찾아 앱 시작 즉시 종료됐다.
DATA_PATH = paths.resource_dir() / "harp_channels.json"
TIMEOUT = 2.0          # 연결 제한 시간(초)
CONCURRENCY = 2        # 동시 연결 최대
RECENT = 5             # 중앙값에 쓰는 최근 성공 수
TIE_MS = 0.1           # 이 안의 차이는 같은 빠르기로 본다
MIN_SAMPLES = 3        # 0.40.2: 성공이 이만큼 모인 채널만 추천·'가장 빠름'(1~3ms에서 0.1ms 차이는 측정 오차 수준)
_SLICE = 0.05          # 취소 확인 간격(초)

OK, TIMEOUT_KIND, REFUSED, ERROR, CANCELLED = "ok", "timeout", "refused", "error", "cancelled"
_REFUSED_CODES = {errno.ECONNREFUSED, 10061}               # 10061 = WSAECONNREFUSED(Windows)
_PENDING_CODES = {0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035}  # 10035 = WSAEWOULDBLOCK


@dataclass(frozen=True)
class Channel:
    number: int
    ip: str
    port: int
    source: str = "관찰"   # 관찰 | 추정 — 목록 관리용(화면에는 보이지 않음)
    checked: str = ""

    @property
    def address(self) -> tuple[str, int]:
        return self.ip, self.port


def load_channels(path: Path = DATA_PATH) -> list[Channel]:
    """데이터 파일의 채널 목록(번호순). 형식이 틀리면 ValueError — 추정으로 채우지 않는다."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    result = []
    for row in doc["channels"]:
        number, ip, port = row["channel"], row["ip"], row["port"]
        if not (type(number) is int and number > 0 and isinstance(ip, str) and type(port) is int and 0 < port < 65536):
            raise ValueError(f"잘못된 채널 항목: {row!r}")
        socket.inet_aton(ip)  # IPv4 주소만
        if row.get("source", "관찰") not in ("관찰", "추정"):
            raise ValueError(f"source는 관찰|추정: {row!r}")
        result.append(Channel(number, ip, port, row.get("source", "관찰"), str(row.get("checked", ""))))
    numbers = [c.number for c in result]
    if len(set(numbers)) != len(numbers):
        raise ValueError("채널 번호 중복")
    return sorted(result, key=lambda c: c.number)


@dataclass(frozen=True)
class Result:
    kind: str                 # ok | timeout | refused | error | cancelled
    ms: float | None = None   # ok일 때만
    detail: str = ""


def connect_time(host: str, port: int, timeout: float = TIMEOUT, cancel: threading.Event | None = None) -> Result:
    """TCP 연결 한 번에 걸린 시간. 연결만 하고 바로 닫는다(데이터 없음). 소켓은 어떤 경우에도 닫는다."""
    if cancel is not None and cancel.is_set():
        return Result(CANCELLED)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    selector = selectors.DefaultSelector()
    try:
        sock.setblocking(False)
        started = perf_counter()
        code = sock.connect_ex((host, port))
        if code in _REFUSED_CODES:
            return Result(REFUSED)
        if code not in _PENDING_CODES:
            return Result(ERROR, detail=errno.errorcode.get(code, str(code)))
        if code == 0:
            return Result(OK, (perf_counter() - started) * 1000)
        selector.register(sock, selectors.EVENT_WRITE)  # Windows는 실패도 쓰기 가능(예외 목록)으로 알린다
        deadline = started + timeout
        while True:
            if cancel is not None and cancel.is_set():
                return Result(CANCELLED)
            remaining = deadline - perf_counter()
            if remaining <= 0:
                return Result(TIMEOUT_KIND)
            if selector.select(min(_SLICE, remaining)):
                elapsed = (perf_counter() - started) * 1000
                code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if code == 0:
                    return Result(OK, elapsed)
                if code in _REFUSED_CODES:
                    return Result(REFUSED)
                return Result(ERROR, detail=errno.errorcode.get(code, str(code)))
    except OSError as exc:
        if exc.errno in _REFUSED_CODES:
            return Result(REFUSED)
        return Result(ERROR, detail=type(exc).__name__)
    finally:
        selector.close()
        sock.close()


@dataclass
class ChannelStats:
    """한 채널의 측정 기록. 취소는 시도에 넣지 않는다. 중앙값은 최근 성공 5회로만."""
    address: tuple[str, int]
    recent: deque = field(default_factory=lambda: deque(maxlen=RECENT))
    successes: int = 0
    attempts: int = 0
    last: Result | None = None

    def record(self, result: Result) -> None:
        if result.kind == CANCELLED:
            return
        self.attempts += 1
        self.last = result
        if result.kind == OK:
            self.successes += 1
            self.recent.append(result.ms)

    @property
    def median(self) -> float | None:
        return statistics.median(self.recent) if self.recent else None


def fingerprint(channels) -> str:
    """주소 목록 지문 — 데이터 파일의 채널·주소가 바뀌면 저장해 둔 지난 결과를 버린다(8절 1항)."""
    import hashlib
    text = ";".join(f"{c.number},{c.ip},{c.port}" for c in sorted(channels, key=lambda c: c.number))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class History:
    """채널별 기록. 데이터 파일의 주소가 바뀌면 그 채널 기록을 지운다."""

    def __init__(self, channels: list[Channel]):
        self.stats: dict[int, ChannelStats] = {}
        self.sync(channels)

    def sync(self, channels: list[Channel]) -> None:
        current = {c.number: c for c in channels}
        self.stats = {n: (s if n in current and s.address == current[n].address else ChannelStats(current[n].address))
                      for n, s in self.stats.items() if n in current}
        for number, channel in current.items():
            self.stats.setdefault(number, ChannelStats(channel.address))

    def record(self, number: int, result: Result) -> None:
        self.stats[number].record(result)

    def export(self) -> dict[str, list[float]]:
        """채널별 최근 성공값(최대 RECENT개) — 저장용."""
        return {str(n): [round(v, 3) for v in s.recent] for n, s in self.stats.items() if s.recent}

    def restore(self, recent: dict) -> None:
        """저장값으로 채운다(성공만 — 시도·실패는 모름). 모르는 채널·잘못된 값은 건너뛴다."""
        for key, values in recent.items():
            try:
                number = int(key)
            except (TypeError, ValueError):
                continue
            stats = self.stats.get(number)
            if stats is None or not isinstance(values, list):
                continue
            for value in values[-RECENT:]:
                if isinstance(value, (int, float)) and 0 <= value < 10_000:
                    stats.record(Result(OK, float(value)))

    def ranking(self) -> list[tuple[int, float]]:
        """(채널, 중앙값) 빠른 순 — 중앙값 오름차순, 같으면 번호 낮은 순. 성공 MIN_SAMPLES회 이상인 채널만(실패만 한 채널 제외)."""
        rows = [(n, s.median) for n, s in self.stats.items() if len(s.recent) >= MIN_SAMPLES]
        return sorted(rows, key=lambda r: (r[1], r[0]))

    def samples(self) -> int:
        """추천까지 모인 표본 수(성공이 가장 많은 채널 기준, 최대 MIN_SAMPLES) — '측정 중이에요(n/3)'."""
        return min(MIN_SAMPLES, max((len(s.recent) for s in self.stats.values()), default=0))

    def fastest(self) -> set[int]:
        """'가장 빠름' 배지 — 추천 채널 하나에만(0.40.2: 동점 묶음 전부에 달면 추천과 엇갈려 보였다)."""
        top, _others, _similar = self.recommendation()
        return {top} if top is not None else set()

    def recommendation(self) -> tuple[int | None, list[int], bool]:
        """(추천 채널, 옆에 보일 채널 최대 2개, 그 채널들이 '비슷하게 빠름'인지).
        추천 = 중앙값이 가장 작은 채널(같으면 번호 낮은 채널). 추천과 0.1ms 안인 채널이 있으면 그 채널들을 '비슷하게 빠름'으로,
        없으면 다음으로 빠른 2개를 '다음으로 빠른 채널'로."""
        ranking = self.ranking()
        if not ranking:
            return None, [], False
        top, best = ranking[0]
        similar = [n for n, m in ranking[1:] if m - best <= TIE_MS + 1e-9]
        if similar:
            return top, similar[:2], True
        return top, [n for n, _m in ranking[1:3]], False


class Round:
    """한 회차: 채널마다 연결 1회, 동시 최대 2개. 결과는 on_result(채널, Result), 끝나면 on_done(취소됐는지).
    콜백은 작업 스레드에서 불린다(화면 쪽에서 신호로 넘길 것)."""

    def __init__(self, channels, on_start, on_result, on_done, *, connect=connect_time, timeout=TIMEOUT,
                 concurrency=CONCURRENCY):
        self.channels = list(channels)
        self.cancel_event = threading.Event()
        self._on_start, self._on_result, self._on_done = on_start, on_result, on_done
        self._connect, self._timeout, self._concurrency = connect, timeout, concurrency
        self._thread = threading.Thread(target=self._run, name="harp-round", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread.is_alive():
            self._thread.join(timeout)

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def _one(self, channel: Channel) -> None:
        if self.cancel_event.is_set():
            return
        self._on_start(channel.number)
        try:
            result = self._connect(channel.ip, channel.port, self._timeout, self.cancel_event)
        except Exception as exc:  # noqa: BLE001 — 한 채널 실패가 회차를 멈추지 않게
            result = Result(ERROR, detail=type(exc).__name__)
        if self.cancel_event.is_set():
            result = Result(CANCELLED)
        self._on_result(channel.number, result)

    def _run(self) -> None:
        try:
            with ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix="harp-connect") as pool:
                for future in [pool.submit(self._one, c) for c in self.channels]:
                    future.result()
        finally:
            self._on_done(self.cancel_event.is_set())
