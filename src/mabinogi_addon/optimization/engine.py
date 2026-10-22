"""One explicit optimization session; all blocking OS calls run off the UI thread."""
import threading
from .session import ChangeDeferred


class Engine:
    def __init__(self, backend, recovery, allowed):
        self.backend, self.recovery, self.allowed = backend, recovery, allowed
        self.cancel = threading.Event()
        self.thread = None
        self.status = '시작 전 · 시스템 설정을 변경하지 않았어요.'
        self.inspection = None
        self.recovery_requested = False
        self.lock = threading.Lock()

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def _launch(self, function, restore_cpu=False):
        with self.lock:
            if self.busy: return False
            self.cancel.clear()
            self.thread = threading.Thread(target=self._run, args=(function,restore_cpu), daemon=True, name='optimization-alpha')
            self.thread.start()
            return True

    def _run(self, function, restore_cpu):
        try:
            function()
        except Exception as exc:
            self.status = f'작업을 완료하지 못했어요: {exc}'
        finally:
            errors = self.recovery.restore() if restore_cpu else []
            if restore_cpu: self.recovery_requested = True
            if errors: self.status += '\nCPU 원복 확인 필요: ' + '; '.join(errors[:4])
            if self.recovery.corrupt or self.recovery.pending or self.recovery.restart_targets:
                self.status += '\n복구 기록이 남아 있어요. 원복 상태를 확인해 주세요.'

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
        return self._launch(work)

    def start(self, options):
        def work():
            if not self.allowed(): raise PermissionError('제작자 접근이 필요해요.')
            self.recovery.finish()
            plan = self.backend.topology().plan(options['count']) if options['cpu'] or options['rss'] else None
            game = self.backend.game()
            notices = []
            results = []
            def network_guard():
                nonlocal game
                if self.cancel.is_set() or not self.allowed():
                    raise ChangeDeferred('중단 요청·접근 해제로 남은 네트워크 적용과 재연결을 보류해요.')
                try: current=self.backend.game()
                except Exception as exc:
                    raise ChangeDeferred('게임 상태를 확인하지 못해 네트워크 변경과 재연결을 보류해요.') from exc
                if current is not None:
                    game=current
                    raise ChangeDeferred('게임 실행 중: 남은 TCP·RSS 적용과 네트워크 재연결을 보류했어요.')
            processes = self.backend.processes()
            governor = self.backend.governor_running()
            if governor and (options['cpu'] or options['rss']): notices.append('Process Lasso Governor 실행 중: CPU·RSS 적용 보류')
            if game and (options['tcp'] or options['rss']):
                notices.append('게임 실행 중: TCP·RSS 적용을 보류했어요.')
            elif options['tcp'] or options['rss']:
                guid = options['adapter']
                if not guid: raise ValueError('적용할 물리 네트워크 어댑터를 선택해 주세요.')
                changes = [('ack',guid,1),('nodelay',guid,1),('autotuning','global','normal')] if options['tcp'] else []
                if options['rss'] and not governor:
                    try: changes.append(('rss',guid,self.backend.rss_plan(guid,plan['background_cores'])))
                    except Exception as exc: notices.append('RSS 미적용: '+str(exc))
                for kind, target, value in changes:
                    if self.cancel.is_set() or not self.allowed(): break
                    try:
                        result=self.recovery.apply(kind,target,value,guard=network_guard)
                        results.append(f'{kind}: '+('기존 값 일치·변경 없음' if result=='unchanged' else '적용값 확인 완료'))
                    except ChangeDeferred as exc:
                        notices.append(str(exc))
                        break
                    except Exception as exc: notices.append(f'{kind} 미적용·확인 필요: {exc}')
                # Explicit start confirmation covered this one batch reconnect.
                try: self.recovery.flush_network(guard=network_guard)
                except ChangeDeferred as exc: notices.append(str(exc))
                except Exception as exc: notices.append('네트워크 재연결 확인 필요: '+str(exc))
            seen = set()
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
                    return
                processes = self.backend.processes()
                governor = self.backend.governor_running()
                if governor and (options['cpu'] or options['rss']):
                    # Never fight the governor, including if it starts mid-session.
                    self.status = 'Process Lasso Governor가 실행돼 CPU를 원복하고 세션을 종료해요.'
                    return
                if options['cpu']:
                    targets = [(observed,plan['game'])] + [(p['target'],plan['background']) for p in processes if self.backend.background_candidate(p,observed)]
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
                        except Exception as exc: notices.append('CPU 일부 미적용: '+str(exc))
                        notices = notices[-12:]
                    # Verify existing ownership without overwriting external changes.
                    for item in self.recovery.pending:
                        if item['kind'] != 'cpu' or item['state'] != 'applied': continue
                        try:
                            if self.backend.read('cpu',item['target']) != item['applied']:
                                raise RuntimeError('다른 도구가 CPU 배치를 바꿨어요. 새 적용을 중단해요.')
                        except ProcessLookupError: continue
                self.status = '\n'.join(results + notices + ['게임 세션 사용 중 · 항목별 적용값 확인 완료' if not notices else '게임 세션 사용 중 · 일부 항목은 미적용/확인 필요'])
                self.cancel.wait(2)
            self.status = '\n'.join(results + notices + ['세션을 중단하고 CPU를 원복해요.'])
        return self._launch(work, restore_cpu=True)

    def stop(self):
        self.cancel.set()
        if not self.busy and any(i['kind']=='cpu' for i in self.recovery.pending):
            self._launch(lambda: setattr(self,'status','CPU 원복을 확인했어요.'), restore_cpu=True)

    def restore_network(self, accept_normalized=False):
        def work():
            errors = self.recovery.restore(network=True, accept_normalized=accept_normalized)
            try: self.recovery.flush_network(verify_restored=True)
            except Exception as exc: errors.append(str(exc))
            self.status = '원복 완료' if not errors and not self.recovery.pending else '원복 확인 필요: '+'; '.join(errors[:4])
        return self._launch(work)
