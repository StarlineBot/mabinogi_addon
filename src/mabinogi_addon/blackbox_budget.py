"""블랙박스 소유 임시 자료와 내보내기 예약의 합산 예산. 파일 삭제는 하지 않는다.

승인 전 용량/여유 공간/항목 수 기본값을 두지 않는다. 저장 완료 클립은 이 임시 예산에서
제외하지만 실제 볼륨 여유 공간에는 반영된다. 실행 중 예약은 보수적으로 전체 상한을
여유 공간에서 차감한다(이미 기록한 부분과 중복 차감될 수 있음). OS 차원의 공간 예약이
아니므로 다른 프로그램/드라이브 분리로 발생한 실제 쓰기 실패는 여전히 처리해야 한다.
"""

from dataclasses import dataclass
from pathlib import Path
import shutil
from threading import Lock


class BudgetError(RuntimeError):
    pass


@dataclass(eq=False)
class _Allocation:
    capacity: int
    volume: int
    pending: bool
    identity: tuple[int, int] | None = None


class DiskBudget:
    def __init__(self, *, max_bytes: int, min_free_bytes: int, max_entries: int,
                 disk_free=None):
        for value in (max_bytes, max_entries):
            if type(value) is not int or value <= 0:
                raise ValueError('budget limits must be positive integers')
        if type(min_free_bytes) is not int or min_free_bytes < 0:
            raise ValueError('minimum free space must be a nonnegative integer')
        self.max_bytes = max_bytes
        self.min_free_bytes = min_free_bytes
        self.max_entries = max_entries
        self._disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self._entries: dict[object, _Allocation] = {}
        self._lock = Lock()

    @property
    def accounted_bytes(self):
        with self._lock:
            return sum(entry.capacity for entry in self._entries.values())

    @property
    def entry_count(self):
        with self._lock:
            return len(self._entries)

    def _check_capacity(self, amount):
        if len(self._entries) >= self.max_entries:
            raise BudgetError('temporary allocation count limit reached')
        if sum(entry.capacity for entry in self._entries.values()) + amount > self.max_bytes:
            raise BudgetError('aggregate temporary byte limit reached')

    def reserve(self, directory: Path, amount: int):
        if type(amount) is not int or amount <= 0:
            raise ValueError('reservation must be a positive integer')
        directory = Path(directory)
        with self._lock:
            self._check_capacity(amount)
            if not directory.is_dir():
                raise OSError('output directory unavailable')
            volume = directory.stat().st_dev
            free = self._disk_free(directory)
            if type(free) is not int or free < 0:
                raise OSError('cannot establish volume free space')
            pending = sum(e.capacity for e in self._entries.values() if e.pending and e.volume == volume)
            if free - pending - amount < self.min_free_bytes:
                raise BudgetError('minimum free space would not be preserved')
            token = object()
            self._entries[token] = _Allocation(amount, volume, True)
            return token

    def retain_existing(self, path: Path):
        """이미 존재하는 소유 원본/실패 자료를 등록. 같은 inode의 중복 등록은 거부한다."""
        path = Path(path)
        with self._lock:
            if path.is_symlink() or not path.is_file():
                raise OSError('owned regular file required')
            stat = path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if any(e.identity == identity for e in self._entries.values()):
                raise BudgetError('file is already accounted')
            self._check_capacity(stat.st_size)
            token = object()
            self._entries[token] = _Allocation(stat.st_size, stat.st_dev, False, identity)
            return token

    def settle(self, token, actual_bytes: int):
        """작업이 닫힌 후 실제 남은 크기로 변경한다. 초과도 숨기지 않고 기록 후 오류로 알린다."""
        if type(actual_bytes) is not int or actual_bytes < 0:
            raise ValueError('invalid retained size')
        with self._lock:
            if token not in self._entries:
                raise ValueError('unknown allocation')
            entry = self._entries[token]
            over = actual_bytes > entry.capacity
            entry.capacity = actual_bytes
            entry.pending = False
            if over:
                raise BudgetError('retained file exceeded its reservation')

    def release(self, token):
        """정리가 확인됐거나 저장 완료 클립으로 확정됐을 때만 호출. 파일 자체는 삭제하지 않는다."""
        with self._lock:
            if token not in self._entries:
                raise ValueError('unknown allocation')
            del self._entries[token]
