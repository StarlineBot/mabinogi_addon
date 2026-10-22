"""앱 실행별 전용 디스크 임시 저장소. 외부 경로를 삭제하거나 자동 복구하지 않는다.

제어 스레드가 직렬화한다. write는 worker에서 유한한 인코더를 사용해야 하며 UI에서
직접 실행하지 않는다. 실패 자료/삭제 실패도 예산에 남는다. 수치는 모두 필수 입력이다.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import uuid

from .blackbox_export import ByteSink


@dataclass
class _File:
    path: Path
    identity: tuple[int, int]
    allocation: object
    complete: bool = False


class DiskSpool:
    def __init__(self, parent: Path, budget):
        # 사용자 선택 parent 밑에 새 전용 폴더만 생성. 기존 폴더를 소유했다고 간주하지 않는다.
        self.directory = Path(tempfile.mkdtemp(prefix='blackbox-', dir=parent))
        stat = self.directory.stat()
        self._identity = (stat.st_dev, stat.st_ino)
        self._budget = budget
        self._files: dict[str, _File] = {}

    def _check_directory(self):
        stat = self.directory.lstat()
        if self.directory.is_symlink() or (stat.st_dev, stat.st_ino) != self._identity:
            raise OSError('spool directory replaced')

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(self._files)

    def write(self, encode, *, max_bytes: int, cancel=None) -> str:
        """encode(sink)로 완결 구간을 쓴다. 실패시 sources에서 복구 자료를 찾을 수 있다."""
        self._check_directory()
        allocation = self._budget.reserve(self.directory, max_bytes)
        source = uuid.uuid4().hex
        record = None
        try:
            fd, name = tempfile.mkstemp(prefix='segment-', suffix='.partial', dir=self.directory)
            with os.fdopen(fd, 'wb') as stream:
                stat = os.fstat(stream.fileno())
                record = _File(Path(name), (stat.st_dev, stat.st_ino), allocation)
                self._files[source] = record
                sink = ByteSink(stream, max_bytes, cancel)
                encode(sink)
                sink.check_cancelled()
                stream.flush()
                if stream.tell() == 0:
                    raise ValueError('empty segment')
                os.fsync(stream.fileno())
                sink.check_cancelled()
            record.complete = True
            return source
        finally:
            if record is None:
                self._budget.release(allocation)
            else:
                # 실패 쓰기도 실제 남은 파일의 비용을 계속 보유한다.
                self._budget.settle(allocation, self._owned(record).stat().st_size)

    def _owned(self, record):
        self._check_directory()
        stat = record.path.lstat()
        if record.path.is_symlink() or (stat.st_dev, stat.st_ino) != record.identity:
            raise OSError('spool file replaced')
        return record.path

    def resolve(self, source: str) -> Path:
        record = self._files[source]
        if not record.complete:
            raise ValueError('source is incomplete')
        return self._owned(record)

    def discard(self, source: str):
        """pin 해제/retired 확인 또는 명시적 실패 복구 포기 후 호출한다."""
        record = self._files[source]
        self._check_directory()
        try:
            self._owned(record).unlink()
        except FileNotFoundError:
            self._check_directory()
            if record.path.exists() or record.path.is_symlink():
                raise OSError('source changed during cleanup')
        self._budget.release(record.allocation)
        del self._files[source]

    def retire(self, segments):
        # 실패한 정리는 sources와 예산에 남아 다시 시도할 수 있다.
        for segment in segments:
            self.discard(segment.source)

    def close(self):
        self._check_directory()
        if self._files:
            raise RuntimeError('owned sources must be resolved before close')
        self.directory.rmdir()  # 알 수 없는 파일이 있으면 삭제하지 않고 실패
