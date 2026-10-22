"""CSV 파싱+요약의 로컬 합성 비용. Windows ETW/게임 성능 측정이 아니다."""
import time
import tracemalloc
from mabinogi_addon.optimization.frames import FrameStream
from mabinogi_addon.optimization.frame_summary import FrameSummary


def main():
    lines=[f'g,7,0x1,{100000000+n*20000},20' for n in range(50000)]
    for enabled in (False,True):
        book=FrameSummary() if enabled else None
        stream=FrameStream(7,1000000,book)
        stream.feed('Application,ProcessID,SwapChainAddress,QPCTime,msBetweenPresents',100)
        start=time.perf_counter()
        for n,line in enumerate(lines):stream.feed(line,100+n*.02)
        elapsed=time.perf_counter()-start
        print(dict(summary=enabled,events=len(lines),seconds=elapsed,us_per_event=elapsed/len(lines)*1e6))
    tracemalloc.start()
    book=FrameSummary();book.activate('a',100)
    for n in range(200000):book.interval('a',100+(n+1)*.001,.001)
    print(dict(memory_bytes=tracemalloc.get_traced_memory(),segments=len(book.records),samples=len(book.samples)))
    tracemalloc.stop()
    book=FrameSummary();book.WINDOW_SECONDS=100;book.activate('a',100)
    for n in range(16000):book.interval('a',100+(n+1)*.001,.001)
    start=time.perf_counter()
    for _ in range(10):book.current()
    print(dict(maximum_size_summary_ms=(time.perf_counter()-start)*100))


if __name__=='__main__':main()
