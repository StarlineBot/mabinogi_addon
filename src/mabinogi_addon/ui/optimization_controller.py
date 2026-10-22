"""Creator tools lifetime is owned by the app, not by the settings dialog."""
import time
import logging

_log = logging.getLogger(__name__)
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox
from .. import config, paths
from ..feature_access import is_creator
from ..optimization.session import Recovery
from ..optimization.engine import Engine
from ..optimization.frames import FrameStream
from ..optimization.frame_summary import FrameSummary, compare, REASONS
from ..optimization.frame_summary_store import SummaryStore
from ..system.optimization import WindowsOptimization
from ..system import presentmon
from .optimization_panel import OptimizationPanel
from .frame_overlay import FrameOverlay


class OptimizationController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.backend = WindowsOptimization()
        # Machine-local recovery must never travel in a settings export/import.
        self.recovery = Recovery(paths.user_data_dir().parent / 'StarlineMabinogiAddonRuntime' / 'recovery.json',
                                 self.backend, lambda: self._can_start() and not self.engine.cancel.is_set())
        self.engine = Engine(self.backend,self.recovery,self._can_start)
        self.panel = OptimizationPanel(window)
        section = config._read_local_config().get('frameMeter')
        section = section if isinstance(section,dict) else {}
        scale = section.get('scale',100)
        self._scale = scale if type(scale) is int and 50<=scale<=300 else 100
        self._reported_source = None
        self._overlay = None
        self.collector = presentmon.Collector(self)
        self.collector.line.connect(self._line)
        self.collector.failed.connect(self._failed)
        self.collector.ended.connect(self._collector_ended)
        self.summary = FrameSummary()
        self.summary.closed_callback = self._summary_closed
        self.summary_store = SummaryStore(paths.user_data_dir() / 'frame_summaries')
        self._summary_collecting = False
        self._summary_state = None
        self._summary_requested = {}
        self._summary_render_at = 0.0
        self._summary_saved = 0
        self._summary_message = '아직 저장한 요약이 없어요.'
        self.frames = False
        self.target = None
        self.stream = None
        self.paused = False
        self.closing = False
        self.context = None
        self.last_tick = time.monotonic()
        self.frame_status = '이전 FPS 세션 정리 필요 · 측정 중단을 눌러 주세요.' if self.collector.pending else '중단됨 · 측정값 없음'
        self.last_health = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._wire_panel()
        self.refresh_access()

    def _can_start(self):
        return (is_creator() and not getattr(self,'closing',False)
                and not getattr(self.window,'_closing',False)
                and not getattr(self.window,'_config_pending_restart',False))

    @property
    def overlay(self):
        if self._overlay is None:
            overlay = self._overlay = FrameOverlay(round(20*self._scale/100))
            overlay.resize(round(210*self._scale/100),80)
            overlay.move(30,90)
            state = config.load_overlay_state('frameMeter') or {}
            if type(state.get('x')) is int and type(state.get('y')) is int:
                from PySide6.QtGui import QGuiApplication
                from PySide6.QtCore import QPoint
                point = QPoint(state['x'],state['y'])
                if any(screen.availableGeometry().contains(point) for screen in QGuiApplication.screens()):
                    overlay.move(point)
            overlay.set_locked(bool(state.get('locked',True)))
            overlay.moved.connect(self._save_overlay)
        return self._overlay

    def _hide_overlay(self):
        if self._overlay is not None: self._overlay.hide()

    def refresh_access(self):
        allowed = self._can_start()
        needed = is_creator()
        if hasattr(self.window,'_tabs'):
            tabs=self.window._tabs;index=tabs.indexOf(self.panel)
            if needed and index<0:
                index=tabs.insertTab(tabs.indexOf(self.window._settings_scroll),self.panel,'최적화')
            elif not needed and index>=0:
                if tabs.currentWidget() is self.panel: tabs.setCurrentWidget(self.window._settings_scroll)
                tabs.removeTab(index)
            if needed: tabs.setTabText(index,'최적화')
        if not allowed:
            if self.frames: self.stop_frames('제작자 접근이 해제돼 측정을 중단했어요.')
            if self.engine.busy: self.engine.cancel.set()

    def _wire_panel(self):
        d=self.panel
        d.inspect.clicked.connect(self.engine.inspect)
        d.start.clicked.connect(self._start_optimization)
        d.stop.clicked.connect(self._stop_optimization)
        d.restore.clicked.connect(self._restore_network)
        d.frames_start.clicked.connect(self.start_frames)
        d.frames_stop.clicked.connect(lambda: self.stop_frames())
        d.lock.setChecked(bool((config.load_overlay_state('frameMeter') or {}).get('locked',True)))
        d.lock.toggled.connect(self._lock)
        d.scale.setValue(self._scale)
        d.scale.valueChanged.connect(self._set_scale)
        d.source.currentIndexChanged.connect(self._select_source)
        d.summary_collect.toggled.connect(self._toggle_summary_collection)
        d.summary_save.clicked.connect(self._save_summary)
        d.summary_folder.clicked.connect(self._open_summary_folder)
        d.summary_select.currentIndexChanged.connect(lambda: self._render_summary(force=True))

    def open(self):
        self.refresh_access()
        if self.window._tabs.indexOf(self.panel)<0: return
        self.window._pages.setCurrentWidget(self.window._tabs)
        self.window._tabs.setCurrentWidget(self.panel)
        self.apply_theme()
        self._tick()

    def apply_theme(self):
        if self.panel is not None:
            from .main_window import _subtab_qss
            from .theme import is_dark
            self.panel.tabs.setStyleSheet(_subtab_qss(is_dark()))

    def _save_overlay(self):
        if self._overlay is None: return
        raw=config._read_local_config()
        section=raw.get('frameMeter')
        section=section if isinstance(section,dict) else {}
        section.update(scale=self._scale,overlay=dict(x=self.overlay.x(),y=self.overlay.y(),locked=self.overlay.locked))
        raw['frameMeter']=section
        config._write_local_config(raw)

    def _set_scale(self, percent):
        if not self._can_start(): return
        self._scale=max(50,min(300,int(percent)))
        self.overlay.resize(round(210*self._scale/100),self.overlay.height())
        self.overlay.set_font_size(round(20*self._scale/100))
        self._save_overlay()

    def _lock(self, locked):
        if not self._can_start(): return
        self.overlay.set_locked(locked)
        self._save_overlay()

    def _network_confirmation(self):
        return QMessageBox.question(self.panel or self.window,'네트워크 재연결',
            '선택한 어댑터의 연결이 잠시 끊길 수 있어요. 통신 중인 다른 앱에도 영향을 줄 수 있어요. 지금 진행할까요?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _start_optimization(self):
        if not self._can_start() or self.engine.busy: return
        d = self.panel
        options = dict(cpu=d.cpu.isChecked(),count=d.split.currentData(),adapter=d.adapter.currentData(),
                       tcp=d.tcp.isChecked(),rss=d.rss.isChecked())
        if not any(options[k] for k in ('cpu','tcp','rss')):
            self.engine.status='사용할 항목을 선택해 주세요.'
            return
        if (options['cpu'] or options['rss']) and options['count'] is None:
            self.engine.status='먼저 환경을 확인하고 물리 코어 배분을 선택해 주세요.'
            return
        if (options['tcp'] or options['rss']) and not options['adapter']:
            self.engine.status='적용할 물리 네트워크 어댑터를 선택해 주세요.'
            return
        if (options['tcp'] or options['rss']) and not self._network_confirmation(): return
        self._summary_requested = {key: options[key] for key in ('cpu','count','tcp','rss')}
        self._summary_requested['adapter_selected'] = bool(options['adapter'])
        self._summary_state = None
        if self.stream is not None:
            self.stream.boundary(presentmon.clock()[0], 'optimization_start_request')
        self.engine.start(options)

    def _stop_optimization(self):
        self._summary_requested = dict(action='stop_cpu')
        self._summary_state = None
        if self.stream is not None:
            self.stream.boundary(presentmon.clock()[0], 'optimization_stop_request')
        self.engine.stop()

    def _restore_network(self):
        if not self._can_start() or self.engine.busy: return
        if self._network_confirmation():
            self._summary_requested = dict(action='restore_network')
            self._summary_state = None
            if self.stream is not None:
                self.stream.boundary(presentmon.clock()[0], 'network_restore_request')
            self.engine.restore_network()

    def start_frames(self):
        if self.frames or not self._can_start(): return
        try:
            presentmon.clock()
            presentmon.executable()
            if not config.load_game_exe(): raise ValueError('설정에서 게임창을 먼저 등록해 주세요.')
            self.summary = FrameSummary()
            self.summary.closed_callback = self._summary_closed
            self._summary_state = None
            self.frames = True
            self.context = None
            self.frame_status = '게임 실행 대기 · 측정값 없음'
            self._tick()
        except Exception as exc: self._failed(str(exc))

    def stop_frames(self, message='중단됨 · 측정값 없음'):
        if self.stream is not None:
            self.stream.boundary(self._summary_now(), 'measurement_stop')
        self.frames = False
        if not self.collector.stop(): message += "\n" + self.collector.cleanup_problem
        self.target, self.stream, self.context = None, None, None
        self._hide_overlay()
        self.frame_status = message
        if self.panel is not None: self.panel.frames_status.setText(message)

    def _collector_ended(self, code):
        if not self.frames: return
        try:
            if self.target is not None and not self.backend.alive(self.target):
                self.collector.stop()
                if self.stream is not None:
                    self.stream.boundary(self._summary_now(), 'game_exit')
                self.target,self.stream,self.context=None,None,None
                self._hide_overlay()
                self.frame_status='게임 실행 대기 · 측정값 없음'
                return
        except Exception:
            pass
        self._failed('FPS 수집기가 종료됐어요. 권한·계측 상태를 확인하고 다시 시작해 주세요.')

    def _failed(self, message):
        if self.stream is not None:
            self.stream.boundary(self._summary_now(), 'collector_error')
        self.stop_frames(message)

    def set_paused(self, paused):
        self.paused = paused
        if paused: self._hide_overlay()

    def _select_source(self):
        if self.stream is not None:
            now, _ = presentmon.clock()
            source=self.panel.source.currentData()
            _log.info('FPS 대상 수동 선택: %s',source)
            self.stream.select(source,now)
            self._hide_overlay()

    def _line(self, line):
        if not self.frames or self.stream is None: return
        try:
            now, _ = presentmon.clock()
            if not self._can_start():
                self.stop_frames('제작자 접근 해제 · 측정 중단')
                return
            active = self.context is None or self.context[0]
            accept_events = active and self._sync_summary_context(now)
            # PresentMon sends its header once, often while our app has focus.
            # Preserve protocol metadata even when focus/transition excludes samples.
            self.stream.feed(line, now, accept_events=accept_events)
            if self.summary.full:
                self.stop_frames('구간/전환 요약 한도 · 기존 자료를 보존하고 측정을 중단했어요.')
        except Exception as exc: self._failed(str(exc))

    def _frame_tick(self, gap):
        game = self.backend.game()
        if game is None and self.target is not None and self.backend.alive(self.target):
            game = self.target
        if game != self.target:
            if self.stream is not None:
                self.stream.boundary(self._summary_now(), 'game_identity_change')
            self.collector.stop()
            self._hide_overlay()
            self.target, self.stream, self.context = game,None,None
            self._reported_source=None
            if game is not None:
                now, frequency = presentmon.clock()
                self.stream = FrameStream(game['pid'],frequency,self.summary)
                self.stream.boundary(now)
                self.collector.start(game['pid'])
                self.frame_status = '측정 준비 중 · 최신 프레임을 기다려요.'
        if game is None:
            self.frame_status = '게임 실행 대기 · 측정값 없음'
            return
        context = presentmon.game_context(game,self.backend._game_window)
        active = context[0]
        now, _ = presentmon.clock()
        if context != self.context or gap > 1.5:
            self.stream.boundary(now, 'focus_target_or_clock_gap')
            self.context = context
            self._hide_overlay()
        if not active:
            self.stream.boundary(now, 'inactive')
            self._hide_overlay()
            self.frame_status = '게임 비활성 · 표시를 쉬고 있어요.'
            return
        if self.stream.header is not None and self.collector.active and time.monotonic()-self.last_health > 1:
            self.last_health = time.monotonic()
            if presentmon.session_losses(self.collector.session):
                raise RuntimeError('Windows 프레임 이벤트 손실을 감지해 측정을 중단했어요. 값을 추정하지 않아요.')
        self._sync_summary_context(now)
        result = self.stream.snapshot(now)
        if result['source'] != self._reported_source:
            self._reported_source=result['source']
            _log.info('FPS 대상 확인: pid=%s source=%s candidates=%s',game['pid'],result['source'],len(result['sources']))
        self.frame_status = result['status']
        if result['fps'] is not None and not self.paused:
            self.overlay.set_text(f"{result['fps']:.1f} FPS")
            self.overlay.show()
        else: self._hide_overlay()
        if self.panel is not None:
            d = self.panel
            sources = result['sources']
            signature=(tuple(sources),self.stream.selected)
            if signature != getattr(d,'_source_signature',None):
                d._source_signature=signature
                selected = self.stream.selected
                d.source.blockSignals(True)
                d.source.clear()
                d.source.addItem('렌더링 대상 자동 확인 (단일 대상일 때)',None)
                for source in sources: d.source.addItem('렌더링 대상 '+source,source)
                if selected is not None and selected not in sources:
                    d.source.addItem('선택한 대상 '+selected+' · 최근 프레임 없음',selected)
                d.source.setCurrentIndex(max(0,d.source.findData(selected)))
                d.source.blockSignals(False)

    def _tick(self):
        now = time.monotonic()
        gap, self.last_tick = now-self.last_tick, now
        self.refresh_access()
        if self.frames:
            try: self._frame_tick(gap)
            except Exception as exc: self._failed(str(exc))
            if self.frames and self.summary.full:
                self.stop_frames('구간/전환 요약 한도 · 기존 자료를 보존하고 측정을 중단했어요.')
        if self.engine.recovery_requested and not self.engine.busy:
            self.engine.recovery_requested = False
        if self.panel is None: return
        self._poll_summary_store()
        self._render_summary()
        d = self.panel
        allowed, busy = self._can_start(), self.engine.busy
        for w in (d.cpu,d.tcp,d.rss,d.split,d.adapter,d.inspect,d.start): w.setEnabled(allowed and not busy)
        d.start.setEnabled(allowed and not busy and not self.recovery.corrupt and not (self.recovery.pending or self.recovery.restart_targets))
        d.stop.setEnabled(busy or any(i['kind']=='cpu' for i in self.recovery.pending))
        d.restore.setEnabled(allowed and not busy and bool(self.recovery.pending or self.recovery.restart_targets))
        for control in (d.lock,d.scale,d.source): control.setEnabled(allowed)
        d.frames_start.setEnabled(allowed and not self.frames)
        d.frames_stop.setEnabled(self.frames or self.collector.pending)
        for control in (d.summary_collect,d.summary_save,d.summary_folder): control.setEnabled(allowed)
        d.frames_status.setText(self.frame_status)
        d.status.setText(('복구 기록이 손상돼 새 적용을 차단했어요. 추정값으로 원복하지 않아요.\n기록: '+str(self.recovery.path)) if self.recovery.corrupt else self.engine.status)
        from collections import Counter
        counts=Counter((item['kind'],item['state']) for item in self.recovery.items)
        kinds={'cpu':'CPU 배치','ack':'TcpAckFrequency','nodelay':'TCPNoDelay','autotuning':'TCP 자동 조정','rss':'RSS'}
        states={'prepared':'적용 확인 필요','applied':'적용됨','failed':'미적용·확인 필요','restored':'원복됨'}
        lines=[f'{kinds[kind]} · {states[state]} {count}개' for (kind,state),count in counts.items()]
        if self.recovery.restart_targets: lines.append(f'네트워크 재연결 대기: {len(self.recovery.restart_targets)}개 어댑터')
        d.results.setText('\n'.join(lines))
        if self.engine.inspection is not None:
            topology, adapters = self.engine.inspection
            self.engine.inspection = None
            d.split.clear()
            if topology is not None:
                d.cpu_info.setText(f'CPU: {topology.name} · 물리 {len(topology.cores)}개 / 논리 {sum(len(c.cpus) for c in topology.cores)}개')
                count = len([c for c in topology.cores if c.performance])
                for n in range(1,count):
                    d.split.addItem(f'게임 {n}개 + 백그라운드 물리 코어 {len(topology.cores)-n}개',n)
                d.split.setCurrentIndex(d.split.findData(topology.plan()['count']))
            else:
                d.cpu_info.setText('CPU 구조를 확인하지 못했어요. CPU·RSS 배치를 적용하지 않아요.')
            d.adapter.clear()
            d.adapter.addItem('직접 사용할 물리 어댑터를 선택해 주세요.',None)
            for adapter in adapters:
                d.adapter.addItem(str(adapter['Name']),str(adapter['InterfaceGuid']).strip('{}'))

    def _summary_now(self):
        try: return presentmon.clock()[0]
        except Exception:
            return self.summary.samples[-1][0] if self.summary.samples else (self.summary.origin or 0)

    def _sync_summary_context(self, now):
        from collections import Counter
        acquired = self.recovery.lock.acquire(blocking=False)
        if not acquired:
            if self.summary.context.get('observation') != 'transition_unconfirmed':
                self.stream.boundary(now, 'optimization_transition_unconfirmed')
                self.summary.set_context(now, dict(observation='transition_unconfirmed'))
            self._summary_state = None
            return False
        try:
            state = (self.recovery.measurement_revision, self.engine.busy, self.engine.cancel.is_set(),
                     tuple(sorted((self.target or {}).items())), repr(self._summary_requested), self.recovery.corrupt)
            if state == self._summary_state:
                return True
            counts = Counter((i['kind'],i['state']) for i in self.recovery.items)
            values = [dict(kind=i['kind'], state=i['state'], value=i['applied']) for i in self.recovery.items
                      if i['kind'] != 'cpu' or i['target'] == self.target][:128]
            from ..version import __version__
            context = dict(target=self.target, requested=self._summary_requested,
                app_version=__version__, collector_sha256=presentmon.SHA256, qpc_frequency=self.stream.frequency,
                observation='journal_unconfirmed' if self.recovery.corrupt else 'last_journal_confirmation_not_live_os_read',
                optimization_worker_active=self.engine.busy, values=values,
                states=[dict(kind=k,state=st,count=n) for (k,st),n in sorted(counts.items())],
                reconnect_pending=len(self.recovery.restart_targets))
            self._summary_state = state
        finally:
            self.recovery.lock.release()
        if context != self.summary.context:
            self.stream.boundary(now, 'optimization_state_observed')
            self.summary.set_context(now, context)
        return True

    def _toggle_summary_collection(self, enabled):
        if enabled and not self._can_start():
            self.panel.summary_collect.setChecked(False)
            return
        if self.stream is not None:
            self.stream.boundary(self._summary_now(), 'collection_toggle')
        self._summary_collecting = enabled
        if enabled and not self.frames:
            self.start_frames()
        if enabled and not self.frames:
            self._summary_collecting = False
            self.panel.summary_collect.blockSignals(True)
            self.panel.summary_collect.setChecked(False)
            self.panel.summary_collect.blockSignals(False)

    def _summary_closed(self, record):
        if self._summary_collecting:
            try:
                report = self.summary.report()
                report['segments'] = [record]
                self.summary_store.submit(report)
            except Exception as exc:
                self._summary_message = str(exc)
                self._summary_collecting = False
                self.panel.summary_collect.blockSignals(True)
                self.panel.summary_collect.setChecked(False)
                self.panel.summary_collect.blockSignals(False)

    def _save_summary(self):
        if not self._can_start(): return
        try:
            report = self.summary.report()
            if not report['segments']: raise ValueError('저장할 유효 구간이 없어요.')
            self.summary_store.submit(report)
            self._summary_message = '요약 저장 중…'
        except Exception as exc: self._summary_message = str(exc)
        self._render_summary(force=True)

    def _open_summary_folder(self):
        if self._can_start(): paths.open_folder(self.summary_store.folder)

    def _poll_summary_store(self):
        for path, error in self.summary_store.poll():
            if error:
                if path:
                    self._summary_saved += 1
                self._summary_message = error if path else '요약 저장 실패: ' + error
                self._summary_collecting = False
                self.panel.summary_collect.blockSignals(True)
                self.panel.summary_collect.setChecked(False)
                self.panel.summary_collect.blockSignals(False)
            else:
                self._summary_saved += 1
                self._summary_message = f'요약 저장 완료 · {self._summary_saved}개'

    def _render_summary(self, force=False):
        now = time.monotonic()
        if not force and now-self._summary_render_at < 1: return
        self._summary_render_at = now
        d = self.panel
        signature = (self.summary.id, len(self.summary.records))
        if getattr(d, '_summary_signature', None) != signature:
            selected = d.summary_select.currentData()
            d.summary_select.blockSignals(True)
            d.summary_select.clear();d.summary_select.addItem('현재 구간',None)
            for index, record in enumerate(self.summary.records):
                d.summary_select.addItem(f"구간 {index+1} · {record['measured_seconds']:.1f}초 · {REASONS.get(record['end_reason'], '구간 종료')}",index)
            d.summary_select.setCurrentIndex(max(0,d.summary_select.findData(selected)))
            d.summary_select.blockSignals(False)
            d._summary_signature = signature
        index = d.summary_select.currentData()
        record = self.summary.current() if index is None else self.summary.records[index]
        if record is None:
            text = '현재 유효 표본 없음 · 중단/대기 구간은 안정 상태로 판정하지 않아요.'
            if self.summary.records: text += ' 이전 구간을 선택해 요약을 확인하세요.'
        else:
            low = '자료 부족(100개 미만)' if record['low_1pct_fps'] is None else f"{record['low_1pct_fps']:.1f} FPS"
            maximum = '자료 부족' if record['max_1s_fps'] is None else f"{record['max_1s_fps']:.0f} FPS"
            text = (f"평균 {record['average_fps']:.1f} FPS · 최대(완전한 1초 창) {maximum}\n1% low {low}\n"
                    f"유효 간격 {record['valid_intervals']:,}개 · 측정 {record['measured_seconds']:.2f}초\n"
                    f"간격 변동계수 {record['variation_percent']:.1f}% · 최장 {record['max_ms']:.1f}ms\n"
                    f"중앙값 2배 초과 {record['relative_long_count']}회 · 설정/대상 전환은 별도 구간")
            if index is None and self.summary.samples and self._summary_now()-self.summary.samples[-1][0] > 2:
                text += '\n최근 이벤트 없음 · 과거 표본이며 현재 안정 상태를 뜻하지 않아요.'
            if record['end_reason'] != 'collecting': text += '\n종료: ' + REASONS.get(record['end_reason'],'구간 종료')
            previous_index = (len(self.summary.records)-1) if index is None else index-1
            if previous_index >= 0:
                comparison = compare(self.summary.records[previous_index],record)
                if comparison['status'] != 'insufficient':
                    text += f"\n직전 대비 평균 {comparison['average_fps_delta']:+.1f} / 최대 {comparison['max_1s_fps_delta']:+.0f} FPS"
                text += '\n' + comparison['message']
            context = record['context']
            requested = context.get('requested',{})
            game_cpu = [v for v in context.get('values',[]) if v['kind']=='cpu' and v['state']=='applied']
            cpu = f"논리 {int(game_cpu[0]['value']).bit_count()}개 적용 확인 기록" if game_cpu else '게임 CPU 현재값 미확인'
            text += f"\nCPU 요청 {requested.get('count','—')}개 · {cpu}"
            text += ' · 설정 상세는 저장 요약에 포함'
        d.summary_result.setText(text)
        d.summary_path.setText(f'저장 위치: {self.summary_store.folder} · {self._summary_message}')
        d.summary_path.setToolTip(str(self.summary_store.folder))

    def prepare_close(self):
        if not self.closing:
            self.closing = True
            self.stop_frames()
            self.engine.stop()
        if self.engine.busy: return False
        self._poll_summary_store()
        if not self.summary_store.close_ready(): return False
        self.timer.stop()
        if self.panel is not None: self.panel.close()
        if self._overlay is not None: self._overlay.close()
        return True
