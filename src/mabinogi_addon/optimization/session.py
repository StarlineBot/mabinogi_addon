"""Bounded, journaled changes. No OS mutation occurs without an explicit start."""
from dataclasses import dataclass
from pathlib import Path
import json
import os
import threading
import uuid


class ChangeDeferred(RuntimeError):
    """A mutation was withheld; durable originals must remain available."""


@dataclass(frozen=True)
class Core:
    index: int
    cpus: tuple[int, ...]
    performance: bool = True


@dataclass(frozen=True)
class Topology:
    name: str
    cores: tuple[Core, ...]

    def plan(self, count=None):
        performance = [c for c in self.cores if c.performance]
        if len(performance) < 2 or len(self.cores) > 64:
            raise ValueError('분리할 물리 코어 구조를 확인하지 못했어요.')
        cpus = [cpu for core in self.cores for cpu in core.cpus]
        if any(not core.cpus for core in self.cores) or not cpus or len(cpus) != len(set(cpus)) or min(cpus) < 0 or max(cpus) >= 64:
            raise ValueError('다중 그룹 또는 중복 CPU 구조는 지원하지 않아요.')
        default = (7 if '9800X3D' in self.name.upper() and len(self.cores) == 8 and len(cpus) == 16
                   and len(performance) == 8 else min(len(performance)-1, max(4, (len(performance)+1)//2)))
        count = default if count is None else count
        if type(count) is not int or not 1 <= count < len(performance):
            raise ValueError('게임과 백그라운드에 각각 물리 코어를 남겨주세요.')
        game_cores = performance[:count]
        game = {n for c in game_cores for n in c.cpus}
        background = set(cpus) - game
        return dict(count=count, game=sum(1 << n for n in game),
                    background=sum(1 << n for n in background), background_cpus=sorted(background))


class Recovery:
    """Write-ahead journal; originals survive retries, crashes and access revocation."""
    MAX_ITEMS = 4096

    def __init__(self, path: Path, backend, allowed):
        self.path, self.backend, self.allowed = Path(path), backend, allowed
        self.lock = threading.RLock()
        self.items = []
        self.corrupt = False
        self.restart_targets = set()
        if self.path.exists():
            try:
                if self.path.stat().st_size > 4 * 1024 * 1024:
                    raise ValueError('large journal')
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(data,dict) or data.get('schema') != 1 or not isinstance(data.get('items'), list) or len(data['items']) > self.MAX_ITEMS:
                    raise ValueError('journal schema')
                for item in data['items']:
                    if not isinstance(item,dict) or item.get('state') not in ('prepared','applied','failed','restored') or set(item) != {'kind', 'target', 'old', 'applied', 'state'} or item['kind'] not in ('cpu','ack','nodelay','autotuning','rss'):
                        raise ValueError('journal item')
                    backend.validate(item['kind'], item['target'], item['old'])
                    backend.validate(item['kind'], item['target'], item['applied'])
                restarts = data.get('restart_targets', [])
                if not isinstance(restarts,list) or len(restarts)>32:
                    raise ValueError('restart journal')
                for target in restarts: uuid.UUID(target)
                self.restart_targets = set(restarts)
                self.items = data['items']
            except Exception:
                self.corrupt = True

    @property
    def pending(self):
        return [i for i in self.items if i['state'] != 'restored']

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as file:
                os.chmod(temporary, 0o600)
                json.dump(dict(schema=1, items=self.items, restart_targets=sorted(self.restart_targets)), file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read(self, kind, target, phase):
        try: return self.backend.read(kind,target)
        except OSError as exc:
            if kind=='cpu': raise  # Preserve process-lifecycle exception types.
            raise OSError(exc.errno, f'{phase}/{kind}: {exc}') from None

    def apply(self, kind, target, value, *, guard=None):
        with self.lock:
            if not self.allowed() or self.corrupt:
                raise PermissionError('제작자 접근 또는 복구 기록을 확인해 주세요.')
            self.backend.validate(kind, target, value)
            if guard is not None: guard()
            existing = next((i for i in self.items if i['kind'] == kind and i['target'] == target and i['state'] != 'restored'), None)
            if existing:
                current = self._read(kind,target,'원본·현재 조회')
                if current != existing['applied']:
                    raise RuntimeError('다른 도구가 값을 바꿨어요. 재적용을 보류해요.')
                return 'unchanged'
            current = self._read(kind,target,'원본·현재 조회')
            if guard is not None: guard()
            if current == value:
                return 'unchanged'
            if len(self.items) >= self.MAX_ITEMS:
                raise RuntimeError('변경 기록 한도에 도달했어요. 먼저 원복해 주세요.')
            self.backend.validate(kind, target, current)
            item = dict(kind=kind, target=target, old=current, applied=value, state='prepared')
            self.items.append(item)
            restarts_before = self.restart_targets.copy()
            if kind in ('ack','nodelay','rss'): self.restart_targets.add(target)
            try:
                self._save()  # Never mutate before durable originals exist.
            except Exception:
                self.items.pop()
                self.restart_targets = restarts_before
                raise
            write_started=False
            try:
                if guard is not None: guard()
                if not self.allowed():
                    raise PermissionError('제작자 접근이 해제됐어요.')
                write_started=True
                guarded_write=getattr(self.backend,'guarded_write',None)
                if guard is not None and guarded_write is not None:
                    guarded_write(kind,target,value,guard)
                else:
                    self.backend.write(kind, target, value)
                if self._read(kind,target,'적용값 확인') != value:
                    raise RuntimeError('적용값을 확인하지 못했어요.')
                item['state'] = 'applied'
            except Exception as exc:
                if not write_started or isinstance(exc,ChangeDeferred): self.restart_targets=restarts_before
                item['state'] = 'failed'
                self._save()
                raise
            self._save()
            return 'applied'

    def restore(self, *, network=False):
        with self.lock:
            if self.corrupt:
                return ['복구 기록이 손상돼 추정값으로 변경하지 않아요.']
            errors = []
            for item in reversed(self.pending):
                if item['kind'] != 'cpu' and not network:
                    continue
                try:
                    current = self._read(item['kind'],item['target'],'원복 전 확인')
                    if current == item['old']:
                        pass
                    elif current == item['applied']:
                        if item['kind'] in ('ack','nodelay','rss'):
                            self.restart_targets.add(item['target'])
                            self._save()
                        self.backend.write(item['kind'], item['target'], item['old'])
                        if self._read(item['kind'],item['target'],'원복값 확인') != item['old']:
                            raise RuntimeError('원복값 확인 실패')
                    else:
                        raise RuntimeError('외부 변경이 있어 원복을 보류해요.')
                    item['state'] = 'restored'
                except ProcessLookupError:
                    if item['kind'] == 'cpu':
                        item['state'] = 'restored'
                    else:
                        errors.append('원래 어댑터를 찾지 못했어요.')
                except Exception as exc:
                    errors.append(f"원복/{item['kind']}: {exc}")
                self._save()
            return errors

    def flush_network(self, *, guard=None):
        with self.lock:
            if self.corrupt: raise RuntimeError('복구 기록을 확인해 주세요.')
            for target in tuple(self.restart_targets):
                if guard is not None: guard()
                guarded_restart=getattr(self.backend,'guarded_restart',None)
                if guard is not None and guarded_restart is not None:
                    guarded_restart(target,guard)
                else:
                    self.backend.restart_network(target)
                self.restart_targets.remove(target)
                self._save()

    def finish(self):
        with self.lock:
            if self.corrupt or self.pending or self.restart_targets:
                raise RuntimeError('복구가 남아 있어 새 세션을 시작할 수 없어요.')
            self.items.clear()
            self._save()
