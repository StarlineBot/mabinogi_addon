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
        # RSS는 물리 코어 단위로 계획한다(SMT 형제 포함 범위는 장치가 재시작 때 줄여 원복이 막힘).
        background_cores = sorted(tuple(sorted(c.cpus)) for c in self.cores if c not in game_cores)
        return dict(count=count, game=sum(1 << n for n in game),
                    background=sum(1 << n for n in background), background_cpus=sorted(background),
                    background_cores=background_cores)


_RSS_RANGE = ('MaxProcessorNumber', 'MaxProcessors')


def rss_normalized(applied, current):
    """현재 RSS 값이 '앱이 쓴 적용값을 장치가 자체 규칙(SMT 형제 제외 등)으로 줄인 결과'인지.

    범위 필드(최대 CPU 번호·개수)만 적용 범위 안에서 줄었고 나머지 필드는 적용값과 같을 때만
    인정한다. 다른 도구의 임의 변경까지 원복하지 않도록 범위를 좁게 둔다."""
    if not isinstance(current, dict) or set(current) != set(applied):
        return False
    if any(current[k] != applied[k] for k in applied if k not in _RSS_RANGE):
        return False
    top, count = current['MaxProcessorNumber'], current['MaxProcessors']
    return (type(top) is int and type(count) is int
            and applied['BaseProcessorNumber'] <= top <= applied['MaxProcessorNumber']
            and 1 <= count <= applied['MaxProcessors']
            and (top, count) != (applied['MaxProcessorNumber'], applied['MaxProcessors']))


class Recovery:
    """Write-ahead journal; originals survive retries, crashes and access revocation."""
    MAX_ITEMS = 4096

    def __init__(self, path: Path, backend, allowed):
        self.path, self.backend, self.allowed = Path(path), backend, allowed
        self.lock = threading.RLock()
        self.measurement_revision = 0
        self.items = []
        self.corrupt = False
        self.restart_targets = set()
        # 마지막 원복 시도에서 '장치 정규화'로 보인 RSS 항목(사용자 확인 후 원본 재기록 대상).
        self.normalized_review = []
        if self.path.exists():
            try:
                if self.path.stat().st_size > 4 * 1024 * 1024:
                    raise ValueError('large journal')
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(data,dict) or data.get('schema') != 1 or not isinstance(data.get('items'), list) or len(data['items']) > self.MAX_ITEMS:
                    raise ValueError('journal schema')
                for item in data['items']:
                    if not isinstance(item,dict) or item.get('state') not in ('prepared','applied','failed','restored','released') or set(item) != {'kind', 'target', 'old', 'applied', 'state'} or item['kind'] not in ('cpu','ack','nodelay','autotuning','rss'):
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
        return [i for i in self.items if i['state'] not in ('restored', 'released')]

    def release(self, item):
        """외부(다른 도구·게임 자신)가 바꾼 CPU 항목을 관리에서 뺀다. 그쪽 값을 덮어쓰거나 원복하지 않는다."""
        with self.lock:
            if item['kind'] != 'cpu' or item not in self.items:
                raise ValueError('CPU 적용 항목만 관리에서 뺄 수 있어요.')
            item['state'] = 'released'
            self._save()

    def _save(self):
        self.measurement_revision += 1
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
                applied = self._read(kind,target,'적용값 확인')
                if applied != value:
                    raise RuntimeError('적용값을 확인하지 못했어요. ' + self._apply_difference(kind, target, value, applied))
                item['state'] = 'applied'
            except Exception as exc:
                if not write_started or isinstance(exc,ChangeDeferred): self.restart_targets=restarts_before
                item['state'] = 'failed'
                self._save()
                raise
            self._save()
            return 'applied'

    def _apply_difference(self, kind, target, value, current):
        """적용 직후 조회값이 요청값과 다를 때 어떤 값이 다른지(현재/적용) 보여준다."""
        if kind == 'rss' and isinstance(current, dict):
            # Only validated RSS scalar fields; never include adapter IDs or shell text.
            try: self.backend.validate('rss', target, current)
            except Exception: return '현재 RSS 값 형식을 확인하지 못했어요.'
            keys = sorted(set(current) | set(value))
            return '차이: ' + '; '.join(f'{k}: 현재={current.get(k)}, 적용={value.get(k)}'
                                       for k in keys if current.get(k) != value.get(k))
        if kind == 'cpu':
            return f'현재=0x{current:X}, 적용=0x{value:X}' if isinstance(current, int) else ''
        if isinstance(current, (int, str, type(None))):
            return f'현재={current}, 적용={value}'
        return ''

    def _difference(self, item, current, *, expected='applied'):
        message = '현재값이 복구 기록과 달라 원복 확인을 보류해요.'
        if item['kind'] == 'rss':
            # Only validated RSS scalar fields; never include adapter IDs or shell text.
            for value in (current, item['old'], item['applied']):
                self.backend.validate('rss', item['target'], value)
            fields = [f"{key}: 현재={current[key]}, 적용={item['applied'][key]}, 원본={item['old'][key]}"
                      for key in sorted(current) if current[key] != item[expected][key]]
            message += ' 비교 시점 차이: ' + '; '.join(fields)
        return message

    def restore(self, *, network=False, accept_normalized=False):
        """기록된 원본으로 되돌린다. accept_normalized: 사용자가 확인한 경우에만 '장치가 앱 적용값을
        정규화한' RSS 항목도 원본으로 다시 쓴다(확인 전에는 차이를 알리고 보류)."""
        with self.lock:
            if self.corrupt:
                return ['복구 기록이 손상돼 추정값으로 변경하지 않아요.']
            errors = []
            if network:
                self.normalized_review = []
            for item in reversed(self.pending):
                if item['kind'] != 'cpu' and not network:
                    continue
                try:
                    current = self._read(item['kind'],item['target'],'원복 전 확인')
                    normalized = item['kind'] == 'rss' and rss_normalized(item['applied'], current)
                    if current == item['old']:
                        pass
                    elif normalized and not accept_normalized:
                        self.normalized_review.append(dict(target=item['target'], current=current, old=item['old']))
                        raise RuntimeError(self._difference(item, current) + ' — 장치가 앱이 쓴 RSS 값을 자체 '
                                           "규칙으로 조정한 것으로 확인돼요. '네트워크 원복'을 다시 누르면 원본으로 "
                                           '되돌릴지 확인해요.')
                    elif current == item['applied'] or normalized:
                        if item['kind'] in ('ack','nodelay','rss'):
                            self.restart_targets.add(item['target'])
                            self._save()
                        self.backend.write(item['kind'], item['target'], item['old'])
                        if self._read(item['kind'],item['target'],'원복값 확인') != item['old']:
                            raise RuntimeError('원복값 확인 실패')
                    else:
                        raise RuntimeError(self._difference(item, current))
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

    def flush_network(self, *, guard=None, verify_restored=False):
        with self.lock:
            if self.corrupt: raise RuntimeError('복구 기록을 확인해 주세요.')
            for target in tuple(self.restart_targets):
                if guard is not None: guard()
                guarded_restart=getattr(self.backend,'guarded_restart',None)
                if guard is not None and guarded_restart is not None:
                    guarded_restart(target,guard)
                else:
                    self.backend.restart_network(target)
                if verify_restored:
                    for item in self.items:
                        if item['target'] != target or item['kind'] == 'cpu' or item['state'] != 'restored':
                            continue
                        try:
                            current = self._read(item['kind'], target, '재연결 후 확인')
                            if current != item['old']:
                                raise RuntimeError(self._difference(item, current, expected='old'))
                        except Exception as exc:
                            item['state'] = 'failed'
                            self._save()  # Keep originals and the restart marker on failure/crash.
                            raise RuntimeError(f"재연결 후 확인/{item['kind']}: {exc}") from None
                self.restart_targets.remove(target)
                self._save()

    def finish(self):
        with self.lock:
            if self.corrupt or self.pending or self.restart_targets:
                raise RuntimeError('복구가 남아 있어 새 세션을 시작할 수 없어요.')
            self.items.clear()
            self._save()
