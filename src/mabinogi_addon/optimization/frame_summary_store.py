"""구간 요약만 유한 큐로 저장. 파일명 생성/소유 파일만 쓰며 이전 기록은 삭제하지 않는다."""
import json
import os
from pathlib import Path
from queue import Queue, Full, Empty
from threading import Thread
from uuid import uuid4


class SummaryStore:
    MAX_FILES = 512
    MAX_BYTES = 16 * 1024 * 1024
    MAX_REPORT = 512 * 1024

    def __init__(self, folder):
        self.folder = Path(folder)
        self.queue = Queue(maxsize=8)
        self.results = Queue(maxsize=8)
        self.thread = None
        self.closing = False

    def submit(self, report):
        if self.closing:
            raise RuntimeError('요약 저장 종료 중이에요.')
        payload = json.dumps(report, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(payload) > self.MAX_REPORT:
            raise ValueError('요약 크기 상한에 도달했어요. 현재 자료를 확인해 주세요.')
        try:
            self.queue.put_nowait(payload)
        except Full:
            raise RuntimeError('요약 저장이 밀려 수집 모드를 중단했어요. 메모리 요약은 유지해요.') from None
        if self.thread is None or not self.thread.is_alive():
            self.thread = Thread(target=self._run, name='fps-summary-writer')
            self.thread.start()

    def _run(self):
        # 종료 직전 enqueue 경쟁은 controller가 결과를 drain할 때 restart()로 처리.
        while not self.results.full():
            try:
                payload = self.queue.get_nowait()
            except Empty:
                return
            published = None
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                total = len(payload)
                for count, path in enumerate(self.folder.iterdir(), 1):
                    if path.is_file(): total += path.stat().st_size
                    if count >= self.MAX_FILES or total > self.MAX_BYTES:
                        raise OSError('요약 보관 한도에 도달했어요. 기존 파일은 삭제하지 않아요.')
                name = self.folder / ('frames-' + uuid4().hex + '.json')
                temporary = name.with_suffix('.partial')
                with temporary.open('xb') as stream:
                    stream.write(payload); stream.flush(); os.fsync(stream.fileno())
                os.link(temporary, name)  # create-only 완료. 기존 파일을 덮어쓰지 않는다.
                published = str(name)
                temporary.unlink()
                self.results.put_nowait((str(name), None))
            except Exception as exc:
                self.results.put_nowait((published, ('저장 완료·임시 파일 정리 실패: ' if published else '') + str(exc)))

    def poll(self):
        results = []
        while True:
            try: results.append(self.results.get_nowait())
            except Empty: break
        if (self.thread is None or not self.thread.is_alive()) and not self.queue.empty():
            self.thread = Thread(target=self._run, name='fps-summary-writer')
            self.thread.start()
        return results

    def close_ready(self):
        self.closing = True
        return self.queue.empty() and self.results.empty() and (self.thread is None or not self.thread.is_alive())
