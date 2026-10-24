"""One explicit optimization session; all blocking OS calls run off the UI thread."""
import logging
import threading
from .session import ChangeDeferred, PROCESS_KINDS

_log = logging.getLogger(__name__)


NETWORK_APPLIED = '네트워크 설정 적용 중 · 끄면 원래 값으로 되돌려요'
HIGH_PRIORITY = 0x80
NORMAL_PRIORITY = 0x20  # 게임이 재접속·맵 이동 때 되돌리는 값(2026-10-24 실측)
# 게임 우선순위가 원본으로 되돌아가면 다시 건다(라쏘 '항상' 규칙과 같은 효과, 13.7).
# 2026-10-24 실측(diag --watch): 게임 재실행 없이 재접속·맵 이동만 해도 게임이 '보통'으로 되돌린다 → 던전 층·맵 이동마다 생길 수 있어
# 10분에 30회까지(맵 이동 20초 간격 수준) 다시 건다. 그보다 잦으면 무언가 계속 되돌리는 것이라 멈추고 안내한다(무한히 다투지 않음).
PRIORITY_REAPPLY_LIMIT = 30
PRIORITY_REAPPLY_WINDOW = 600.0


def result_headline(notices, failures):
    """결과 첫 줄(명세 13.5): 설정이 목표 상태인 사실만 말한다. 성능 향상은 측정 근거 전 단정하지 않는다.
    선택한 항목이 이미 목표값이라 바꾼 것이 없어도 '적용 완료'다(항목별 상세에서 '이미 목표값 · 그대로 둠')."""
    if any(message in failures for message in notices):
        return '최적화 일부 미적용 · 아래 항목을 확인해 주세요'
    return '최적화 적용 완료 · 설정이 목표 상태로 맞춰졌어요'


def session_line(notices, failures):
    """세션 상태 마지막 줄: 실제 실패만 '확인 필요'로, 보류·관리 제외 안내만 있으면 안내로 구분한다."""
    failed = sum(1 for message in notices if message in failures)
    if failed:
        return f'게임 세션 사용 중 · 미적용/확인 필요 {failed}건(위 내용 확인)'
    if notices:
        return '게임 세션 사용 중 · 적용한 항목은 확인 완료 · 보류·관리 제외 안내는 위를 확인하세요'
    return '게임 세션 사용 중 · 항목별 적용값 확인 완료'


class Engine:
    def __init__(self, backend, recovery, allowed):
        self.backend, self.recovery, self.allowed = backend, recovery, allowed
        self.cancel = threading.Event()
        self.thread = None
        self.status = '시작 전 · 시스템 설정을 변경하지 않았어요.'
        self.inspection = None
        self.recovery_requested = False
        self.lock = threading.Lock()
        self._partial = None  # 진행 중 작업의 결과/안내 줄(예외로 끝나도 버리지 않게)
        self._restore_network_after = None  # '중단 · 원복': CPU 원복 뒤 이어서 할 네트워크 원복(accept_normalized,)
        self._restore_cpu_after = False  # '중단 · 원복'을 누른 시점에 돌던 작업이 무엇이든 끝에서 CPU를 원복
        self._network_deferred = False  # 사용자가 네트워크 원복을 미룸 → '네트워크 원복 대기' 안내
        self.task = None  # 진행 중 작업 종류: 'inspect' | 'session' | 'restore' (busy일 때만 의미)
        # 세션이 끝난 이유: 'network_only'(네트워크만 하고 정상 종료) | 'game_exit' | 'governor' | 'cancel' | 'error'
        self.session_end = None

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def _launch(self, function, restore_cpu=False, status=None, task='restore'):
        with self.lock:
            if self.busy: return False
            self.task = task
            self.cancel.clear()
            self._partial = None
            if status is not None:
                self.status = status  # 이전 결과('원복 완료' 등)가 진행 중에 남지 않게 즉시 교체
            self.thread = threading.Thread(target=self._run, args=(function,restore_cpu), daemon=True, name='optimization-alpha')
            self.thread.start()
            return True

    def _run(self, function, restore_cpu):
        try:
            function()
        except Exception as exc:
            # 지금까지의 적용 결과·미적용 이유(RSS 등)를 버리지 않고 이어 붙인다.
            lines = self._partial() if self._partial is not None else []
            self.status = '\n'.join([*lines, f'작업을 완료하지 못했어요: {exc}'])
            if self.task == 'session':
                self.session_end = 'error'
        finally:
            restore_cpu = restore_cpu or self._restore_cpu_after
            self._restore_cpu_after = False
            errors = self.recovery.restore() if restore_cpu else []
            if restore_cpu: self.recovery_requested = True
            if errors: self.status += '\nCPU 원복 확인 필요: ' + '; '.join(errors[:4])
            network, self._restore_network_after = self._restore_network_after, None
            if network is not None:
                # 원버튼 원복: 같은 작업 안에서 CPU 다음에 네트워크(TCP·RSS)까지 되돌린다.
                net_errors = self._network_restore(*network)
                self.status += ('\n네트워크 원복 완료' if not net_errors and not self.recovery.pending
                                else '\n네트워크 원복 확인 필요: ' + '; '.join(net_errors[:4]))
            deferred, self._network_deferred = self._network_deferred, False
            if deferred and (any(i['kind'] not in PROCESS_KINDS for i in self.recovery.pending) or self.recovery.restart_targets):
                self.status += ("\n네트워크 원복 대기 · 연결을 끊어도 될 때 '최적화 적용 중' 버튼을 다시 눌러 주세요.")
            elif self.recovery.corrupt or any(i['kind'] in PROCESS_KINDS for i in self.recovery.pending) or (
                    network is not None and (self.recovery.pending or self.recovery.restart_targets)):
                self.status += '\n복구 기록이 남아 있어요. 원복 상태를 확인해 주세요.'
            elif self.recovery.pending or self.recovery.restart_targets:
                # 원복을 요청하지 않은 네트워크 변경은 정상 적용 상태다(13.5: '적용 중'과 '원복 대기' 구분).
                self.status += '\n' + NETWORK_APPLIED

    def inspect(self):
        def work():
            if not self.allowed(): raise PermissionError('제작자 접근이 필요해요.')
            topology, adapters, errors = None, [], []
            try:
                topology = self.backend.topology()
                topology.plan()
            except Exception as exc:
                topology=None
                errors.append(str(exc))
            try: adapters = self.backend.adapters()
            except Exception as exc: errors.append(str(exc))
            self.inspection = (topology, adapters)
            self.status = '\n'.join(errors) if errors else '환경을 확인했어요. 시작을 누르기 전에는 적용하지 않아요.'
        return self._launch(work, status='환경 확인 중…', task='inspect')

    def start(self, options):
        self.session_end = None
        def work():
            if not self.allowed(): raise PermissionError('제작자 접근이 필요해요.')
            self.recovery.finish()
            # 13.8: RSS는 새로 적용하지 않는다(예전 기록의 원복만 유지). 13.9: 패스트핑은 TcpAckFrequency만(TCPNoDelay 제외).
            plan = self.backend.topology().plan(options['count']) if options['cpu'] else None
            game = self.backend.game()
            notices = []
            results = []
            failures = set()  # notices 중 실제 미적용·확인 필요(의도된 보류·관리 제외 안내와 구분)
            def fail(message):
                failures.add(message)
                notices.append(message)
            self._partial = lambda: results + notices
            names = {}  # (pid, birth) → 프로세스 이름: 소유 확인 실패 시 어떤 프로세스인지 남긴다
            def network_guard():
                nonlocal game
                if self.cancel.is_set() or not self.allowed():
                    raise ChangeDeferred('중단 요청·접근 해제로 남은 네트워크 적용과 재연결을 보류해요.')
                try: current=self.backend.game()
                except Exception as exc:
                    raise ChangeDeferred('게임 상태를 확인하지 못해 네트워크 변경과 재연결을 보류해요.') from exc
                if current is not None:
                    game=current
                    raise ChangeDeferred('게임 실행 중: 남은 TCP 적용과 네트워크 재연결을 보류했어요.')
            processes = self.backend.processes()
            governor = self.backend.governor_running()
            if governor and (options['cpu'] or options.get('priority')):
                notices.append('Process Lasso Governor 실행 중: CPU·게임 우선순위 적용 보류')
            if game and options['tcp']:
                notices.append('게임 실행 중: TCP 적용을 보류했어요.')
            elif options['tcp']:
                guid = options['adapter']
                if not guid: raise ValueError('적용할 물리 네트워크 어댑터를 선택해 주세요.')
                changes = [('ack',guid,1),('autotuning','global','normal')]
                for kind, target, value in changes:
                    if self.cancel.is_set() or not self.allowed(): break
                    try:
                        result=self.recovery.apply(kind,target,value,guard=network_guard)
                        results.append(f'{kind}: '+{'unchanged':'이미 목표값 · 그대로 둠','written':'적용 · 재연결 후 확인'}.get(result,'적용값 확인 완료'))
                    except ChangeDeferred as exc:
                        notices.append(str(exc))
                        break
                    except Exception as exc: fail(f'{kind} 미적용·확인 필요: {exc}')
                # Explicit start confirmation covered this one batch reconnect.
                try:
                    self.recovery.flush_network(guard=network_guard)
                    if any(i['kind']=='rss' and i['state']=='applied' for i in self.recovery.items):
                        results.append('rss: 재연결 후 적용값 확인 완료')
                except ChangeDeferred as exc: notices.append(str(exc))
                except Exception as exc: fail('네트워크 재연결 확인 필요: '+str(exc))
            if not options['cpu'] and not options.get('priority'):
                # CPU·우선순위를 끈 세션은 게임을 기다릴 이유가 없다(네트워크 설정은 원복 전까지 유지).
                self.status = '\n'.join([result_headline(notices, failures)] + results + notices
                                         + ['네트워크 설정 작업을 마쳤어요. CPU 배치는 사용하지 않아요.'])
                self.session_end = 'network_only'
                return
            seen = set()
            priority = dict(applied=set(), reapplied=[], stopped=set(), preset=set(), background=set())  # 게임 우선순위 상태(13.7)
            observed = game
            while not self.cancel.is_set() and self.allowed():
                if observed is None:
                    observed = self.backend.game()
                    if observed is None:
                        self.status = '\n'.join(results + notices + ['게임 실행 대기 · CPU는 아직 적용하지 않았어요.'])
                        self.cancel.wait(1)
                        continue
                if not self.backend.alive(observed):
                    self.status = '\n'.join(results + notices + ['게임 종료 · CPU를 원복해요. 다음 게임에는 자동 적용하지 않아요.'])
                    self.session_end = 'game_exit'
                    return
                processes = self.backend.processes() if options['cpu'] else []  # 우선순위만이면 전체 목록이 필요 없다
                governor = self.backend.governor_running()
                if governor and (options['cpu'] or options.get('priority')):
                    # Never fight the governor, including if it starts mid-session.
                    self.status = 'Process Lasso Governor가 실행돼 CPU를 원복하고 세션을 종료해요.'
                    self.session_end = 'governor'
                    return
                if options['cpu']:
                    # 관측 목록은 살아 있는 프로세스로만 유지한다(짧게 뜨고 끝나는 프로세스 누적 방지, 13.3).
                    alive = {(p['target']['pid'],p['target']['birth']) for p in processes}
                    alive.add((observed['pid'],observed['birth']))
                    seen &= alive
                    names = {k: v for k, v in names.items() if k in alive}
                    candidates = [p for p in processes if self.backend.background_candidate(p,observed)]
                    for p in candidates: names[(p['target']['pid'],p['target']['birth'])] = p['name']
                    targets = [(observed,plan['game'])] + [(p['target'],plan['background']) for p in candidates]
                    for target, mask in targets:
                        if self.cancel.is_set() or not self.allowed(): break
                        identity = (target['pid'],target['birth'])
                        if identity in seen: continue
                        seen.add(identity)
                        if len(seen)>self.recovery.MAX_ITEMS:
                            raise RuntimeError('프로세스 관측 한도에 도달했어요. 세션을 중단해요.')
                        try:
                            self.recovery.apply('cpu',target,mask)
                        except ProcessLookupError: pass
                        except Exception as exc: fail('CPU 일부 미적용: '+str(exc))
                        notices = notices[-12:]
                    # Verify ownership without overwriting external changes. 한 프로세스가 달라져도
                    # 세션 전체를 끝내지 않고 그 프로세스만 관리에서 뺀다(원복도 하지 않음 — 바꾼 쪽의 값을 존중).
                    for item in [i for i in self.recovery.items if i['kind'] == 'cpu' and i['state'] in ('applied','released')]:
                        try:
                            current = self.backend.read('cpu',item['target'])
                        except ProcessLookupError:
                            self.recovery.forget_exited(item)  # 종료한 프로세스: 되돌릴 대상 없음
                            continue
                        if item['state'] != 'applied' or current == item['applied']: continue
                        identity = (item['target']['pid'],item['target']['birth'])
                        is_game = observed is not None and identity == (observed['pid'],observed['birth'])
                        label = '게임 프로세스' if is_game else names.get(identity,'이름 확인 불가')
                        self.recovery.release(item)
                        message = (f"{'게임 프로세스가 직접' if is_game else '다른 도구가'} CPU 배치를 바꿨어요 · "
                                   f"{label} (PID {identity[0]}): 적용=0x{item['applied']:X}, 현재=0x{current:X}. "
                                   '이 프로세스는 관리에서 빼고 계속해요(원복하지 않음).')
                        _log.warning(message)
                        notices.append(message)
                        notices = notices[-12:]
                if options.get('priority'):
                    notices = self._keep_priority(observed, priority, results, notices, fail)[-12:]
                self.status = '\n'.join([result_headline(notices, failures)] + results + notices + [session_line(notices, failures)])
                self.cancel.wait(2)
            self.status = '\n'.join(results + notices + ['세션을 중단하고 CPU를 원복해요.'])
            self.session_end = 'cancel'
        return self._launch(work, restore_cpu=True, status='적용 중…', task='session')

    def _keep_priority(self, game, state, results, notices, fail):
        """게임 우선순위 높음(최적화 명세 13.7): 게임마다 한 번 걸고, 2초마다 유지 여부를 본다.

        - 원본으로 돌아갔으면 다시 건다(10분에 30회까지, 넘으면 안내만).
        - 원본·적용값이 아닌 다른 값이면 다른 도구가 바꾼 것: 덮어쓰지 않고 관리에서 뺀다.
        - 게임 창이 뒤에 있는 동안 게임이 '보통'으로 낮추면 그대로 둔다(2026-10-24 사용자 결정: 게임에 집중할 때만 높음이면 됨).
          다시 앞으로 왔는데도 '보통'이면 그때 다시 건다(다시 걸기 횟수에도 넣지 않음).
        - 시작 때 이미 높음이었으면(작업 관리자·라쏘로 미리 건 경우) 기록 없이 지켜보다가, 게임이 '보통'으로 되돌리면
          그 '보통'을 원본으로 기록하고 높음을 건다(0.17.0 QA). 이후는 위 유지·원복 흐름. '보통'이 아닌 다른 값으로 바뀌면
          다른 도구가 바꾼 것으로 보고 손대지 않는다.
        - 두 읽기 경로가 다르면 '확인 불가'로 안내만 하고 다시 걸지 않는다(읽기 불일치 조사 중)."""
        import time
        from ..system.process_priority import Unconfirmed, name
        identity = (game['pid'], game['birth'])
        foreground = getattr(self.backend, 'foreground', None)
        try:
            focused = foreground(game) if foreground is not None else True
        except Exception:
            focused = True
        # 직전 확인에서 게임 창이 뒤였는지: 뒤→앞 복귀 뒤 첫 다시 걸기는 한도에 넣지 않는다(Alt+Tab마다 한도가 차 관리가 멈추던 문제, 0.17.0 QA)
        returned = focused and identity in state.setdefault('background', set())
        if focused:
            state['background'].discard(identity)
        else:
            state['background'].add(identity)
        if identity not in state['applied']:
            state['applied'].add(identity)
            try:
                result = self.recovery.apply('priority', game, HIGH_PRIORITY)
                if result == 'unchanged':
                    state['preset'].add(identity)  # 기록 없이 지켜본다(위 독스트링)
                results.append('게임 우선순위: ' + {'unchanged': '이미 높음 · 그대로 둠', 'applied': '높음 적용 · 확인 완료',
                                                    'unverified': '높음 적용 · 확인 불가(읽기 경로가 서로 달라요)'}.get(result, result))
            except ProcessLookupError:
                pass
            except Unconfirmed as exc:
                notices.append(f'게임 우선순위 확인 불가 · 적용하지 않았어요: {exc}')
            except Exception as exc:
                fail(f'게임 우선순위 미적용: {exc}')
            return notices
        if identity in state['preset']:
            try:
                current = self.backend.read('priority', game)
            except (ProcessLookupError, Unconfirmed):
                return notices
            if current == HIGH_PRIORITY or (current == NORMAL_PRIORITY and not focused):
                return notices  # 뒤에 있을 때 게임이 낮춘 보통은 존중하고 계속 지켜본다
            state['preset'].discard(identity)
            if current != NORMAL_PRIORITY:
                message = (f'다른 도구가 게임 우선순위를 바꿨어요(현재 {name(current)}). 덮어쓰지 않아요.')
                _log.warning(message)
                notices.append(message)
                return notices
            try:  # 게임이 '보통'으로 되돌림: 그 값을 원본으로 기록하고 높음을 건다
                result = self.recovery.apply('priority', game, HIGH_PRIORITY)
                _log.info('미리 높음이던 게임 우선순위가 보통으로 돌아가 앱이 관리하기 시작했어요(%s).', result)
                notices.append('게임 우선순위가 보통으로 돌아가 앱이 다시 높음으로 걸었어요(이제 세션이 끝나면 보통으로 원복).')
            except ProcessLookupError:
                pass
            except Unconfirmed as exc:
                notices.append(f'게임 우선순위 확인 불가 · 적용하지 않았어요: {exc}')
            except Exception as exc:
                fail(f'게임 우선순위 미적용: {exc}')
            return notices
        item = next((i for i in self.recovery.items if i['kind'] == 'priority' and i['target'] == game
                     and i['state'] == 'applied'), None)
        if item is None or identity in state['stopped']:
            return notices
        try:
            current = self.backend.read('priority', game)
        except (ProcessLookupError, Unconfirmed):
            return notices
        if current == item['applied']:
            return notices
        if current == item['old'] and not focused:
            return notices  # 게임 창이 뒤: 게임이 낮춘 값을 그대로 둔다(앞으로 오면 다시 건다)
        if current != item['old']:
            self.recovery.release(item)
            message = (f"다른 도구가 게임 우선순위를 바꿨어요(현재 {name(current)}). 덮어쓰지 않고 관리에서 뺐어요(원복하지 않음).")
            _log.warning(message)
            notices.append(message)
            return notices
        if returned:
            # 뒤에 있는 동안 게임이 낮춘 보통: 앞으로 돌아온 첫 확인에서 다시 건다(한도는 앞에 있는 동안 되돌아간 경우만 센다)
            try:
                self.backend.write('priority', game, item['applied'])
            except ProcessLookupError:
                pass
            except Exception as exc:
                fail(f'게임 우선순위 다시 걸기 실패: {exc}')
            return notices
        now = time.monotonic()
        state['reapplied'] = [t for t in state['reapplied'] if now - t < PRIORITY_REAPPLY_WINDOW]
        if len(state['reapplied']) >= PRIORITY_REAPPLY_LIMIT:
            state['stopped'].add(identity)
            message = (f'게임 우선순위가 계속 {name(current)}(으)로 돌아가요. 10분에 {PRIORITY_REAPPLY_LIMIT}회까지 다시 걸고 '
                       '멈췄어요(다른 프로그램과 다투지 않음).')
            _log.warning(message)
            notices.append(message)
            return notices
        state['reapplied'].append(now)
        try:
            self.backend.write('priority', game, item['applied'])
            count = len(state['reapplied'])
            if count <= 3 or count % 10 == 0:  # 맵 이동마다 생기므로 로그는 처음 몇 번과 10회마다
                _log.info('게임 우선순위가 %s(으)로 돌아가 다시 높음으로 걸었어요(최근 10분 %d/%d회).', name(current),
                          count, PRIORITY_REAPPLY_LIMIT)
        except ProcessLookupError:
            pass
        except Exception as exc:
            fail(f'게임 우선순위 다시 걸기 실패: {exc}')
        return notices

    def stop(self):
        self.cancel.set()
        if not self.busy and any(i['kind'] in PROCESS_KINDS for i in self.recovery.pending):
            self._launch(lambda: setattr(self,'status','CPU 원복을 확인했어요.'), restore_cpu=True,
                         status='CPU 원복 중…')

    def _network_restore(self, accept_normalized=False):
        errors = self.recovery.restore(network=True, accept_normalized=accept_normalized)
        try: self.recovery.flush_network(verify_restored=True)
        except Exception as exc: errors.append(str(exc))
        return errors

    def restore_network(self, accept_normalized=False):
        def work():
            errors = self._network_restore(accept_normalized)
            self.status = '원복 완료' if not errors and not self.recovery.pending else '원복 확인 필요: '+'; '.join(errors[:4])
        return self._launch(work, status='네트워크 원복 중…')

    def stop_and_restore(self, network=False, accept_normalized=False, network_deferred=False):
        """'중단 · 원복' 한 번으로 적용했던 것을 모두 되돌린다: 세션 중단 → CPU 원복 → (network면) 네트워크 원복.

        세션이 돌고 있으면 그 작업이 끝나며 CPU를 원복하고 이어서 네트워크를 원복한다(같은 작업 스레드)."""
        if network:
            self._restore_network_after = (accept_normalized,)
        self._network_deferred = network_deferred and not network
        self._restore_cpu_after = True
        self.cancel.set()
        if self.busy:
            self.status = '중단 · 원복 중…'
            return True
        return self._launch(lambda: setattr(self, 'status', 'CPU 원복을 확인했어요.'), restore_cpu=True,
                            status='원복 중…')
