"""Bounded, journaled changes. No OS mutation occurs without an explicit start."""
from dataclasses import dataclass
from pathlib import Path
import json
import os
import logging
import threading
import uuid


_log = logging.getLogger(__name__)


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


# 프로세스 단위 항목: 게임·백그라운드 CPU 배치와 게임 우선순위(13.7). 원복은 CPU 원복과 같은 때 하고, 프로세스가 끝나면 되돌릴 것이 없다.
PROCESS_KINDS = ('cpu', 'priority')


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
                    if not isinstance(item,dict) or item.get('state') not in ('prepared','applied','failed','restored','released') or set(item) != {'kind', 'target', 'old', 'applied', 'state'} or item['kind'] not in ('cpu','priority','ack','nodelay','autotuning','rss'):
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

    def forget_exited(self, item):
        """종료한 프로세스의 CPU 기록을 지운다(되돌릴 대상이 없다). 블랙박스 인코더처럼 짧게 뜨고 끝나는
        프로세스가 계속 쌓여 기록 한도(MAX_ITEMS)에 닿아 세션이 끝나지 않게 한다(명세 13.3)."""
        with self.lock:
            if item['kind'] not in PROCESS_KINDS or item not in self.items:
                raise ValueError('프로세스 적용 항목만 정리할 수 있어요.')
            self.items.remove(item)
            self._save()

    def release(self, item):
        """외부(다른 도구·게임 자신)가 바꾼 CPU 항목을 관리에서 뺀다. 그쪽 값을 덮어쓰거나 원복하지 않는다."""
        with self.lock:
            if item['kind'] not in PROCESS_KINDS or item not in self.items:
                raise ValueError('프로세스 적용 항목만 관리에서 뺄 수 있어요.')
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
            if kind in PROCESS_KINDS: raise  # Preserve process-lifecycle(·우선순위 확인 불가) exception types.
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
                if kind == 'rss':
                    # -NoRestart로 쓴 RSS는 어댑터를 다시 시작해야 반영돼, 지금 조회하면 이전 값이 나온다
                    # (0.11.3 실측: 항상 확인 실패 → failed로 남아 다음 시작이 막힘). 'prepared'로 두고
                    # flush_network가 재시작 직후 확인한다. 원본은 이미 기록돼 있다.
                    self._save()
                    return 'written'
                if kind == 'priority':
                    # 13.7: 읽기 경로 불일치 원인이 확인되기 전에는 확인 실패를 적용 실패로 단정하지 않는다.
                    # 쓰기는 성공했으므로 원본과 함께 '적용'으로 기록하고(원복 대상), 확인 결과만 따로 알린다.
                    from ..system.process_priority import Unconfirmed
                    try:
                        applied = self._read(kind, target, '적용값 확인')
                    except Unconfirmed:
                        applied = None
                    item['state'] = 'applied'
                    self._save()
                    return 'applied' if applied == value else 'unverified'
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
        if kind == 'priority':
            from ..system.process_priority import name
            return f'현재={name(current)}, 적용={name(value)}'
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
                if item['kind'] not in PROCESS_KINDS and not network:
                    continue
                try:
                    if item['kind'] == 'priority':
                        if self._restore_priority(item):
                            continue  # 외부 변경으로 관리에서 뺌(덮어쓰지 않음)
                        item['state'] = 'restored'
                        self._save()
                        continue
                    current = self._read(item['kind'],item['target'],'원복 전 확인')
                    normalized = item['kind'] == 'rss' and rss_normalized(item['applied'], current)
                    if item['kind'] == 'rss' and item['state'] == 'prepared':
                        # 재연결 전에 끝난 RSS 적용: 조회(실행값)는 아직 원본이지만 저장값은 적용값이라,
                        # 쓰기를 생략하면 재연결 때 적용값이 반영된다. 원본을 다시 쓰고 재연결 후 확인한다.
                        self.restart_targets.add(item['target'])
                        self._save()
                        self.backend.write('rss', item['target'], item['old'])
                    elif current == item['old']:
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
                        # RSS(-NoRestart)는 재시작 전 조회가 이전 값이라 여기서 비교하지 않는다.
                        # flush_network(verify_restored=True)가 재연결 직후 원본과 비교한다.
                        if item['kind'] != 'rss' and self._read(item['kind'],item['target'],'원복값 확인') != item['old']:
                            raise RuntimeError('원복값 확인 실패')
                    else:
                        raise RuntimeError(self._difference(item, current))
                    item['state'] = 'restored'
                except ProcessLookupError:
                    if item['kind'] in PROCESS_KINDS:
                        item['state'] = 'restored'
                    else:
                        errors.append('원래 어댑터를 찾지 못했어요.')
                except Exception as exc:
                    errors.append(f"원복/{item['kind']}: {exc}")
                self._save()
            return errors

    def _restore_priority(self, item):
        """게임 우선순위 원복(13.7). 지금 값이 원본·적용값이 아니면 다른 도구가 바꾼 것이라 덮어쓰지 않고 관리에서 뺀다(True).
        두 읽기 경로가 다르면(확인 불가) 원본을 다시 쓴다 — 같은 값을 다시 써도 해가 없고, 읽기만 믿다가 '높음'을 남기지 않게."""
        from ..system.process_priority import Unconfirmed, name
        try:
            current = self._read('priority', item['target'], '원복 전 확인')
        except Unconfirmed:
            current = None
        if current is not None and current not in (item['old'], item['applied']):
            item['state'] = 'released'
            self._save()
            _log.warning('게임 우선순위를 다른 도구가 바꿔(%s) 원복하지 않고 관리에서 뺐어요(원본 %s · 적용 %s).',
                         name(current), name(item['old']), name(item['applied']))
            return True
        self.backend.write('priority', item['target'], item['old'])
        try:
            back = self._read('priority', item['target'], '원복값 확인')
        except Unconfirmed:
            back = None  # 확인 불가: 원본을 썼으므로 원복으로 본다(읽기 불일치 조사 중)
        if back is not None and back != item['old']:
            raise RuntimeError(f"원복값 확인 실패(현재 {name(back)}, 원본 {name(item['old'])})")
        return False

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
                verified = self._verify_after_restart(target)
                if verify_restored:
                    for item in self.items:
                        if item['target'] != target or item['kind'] in PROCESS_KINDS or item['state'] != 'restored':
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
                if verified:
                    raise RuntimeError('; '.join(verified))

    def _verify_after_restart(self, target):
        """재시작 직후 RSS 적용값을 확인한다. 장치 정규화(범위만 줄어듦)는 적용으로 인정하고 그 값을
        적용값으로 기록한다(이후 원복이 '현재=적용'으로 바로 맞게). 실패 문구 목록을 돌려준다."""
        failures = []
        for item in self.items:
            if item['target'] != target or item['kind'] != 'rss' or item['state'] != 'prepared':
                continue
            try:
                current = self._read('rss', target, '재연결 후 적용값 확인')
                if current != item['applied'] and not rss_normalized(item['applied'], current):
                    raise RuntimeError('적용값을 확인하지 못했어요. '
                                       + self._apply_difference('rss', target, item['applied'], current))
                item['applied'] = current
                item['state'] = 'applied'
            except Exception as exc:
                item['state'] = 'failed'
                failures.append(f'재연결 후 확인/rss: {exc}')
            self._save()
        return failures

    def finish(self):
        with self.lock:
            if self.corrupt or self.pending or self.restart_targets:
                raise RuntimeError('복구가 남아 있어 새 세션을 시작할 수 없어요.')
            self.items.clear()
            self._save()
