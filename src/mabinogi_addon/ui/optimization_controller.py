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
from ..system.optimization import WindowsOptimization
from ..system import presentmon
from .optimization_dialog import OptimizationDialog
from .memo_overlay import MemoOverlay


class OptimizationController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.backend = WindowsOptimization()
        # Machine-local recovery must never travel in a settings export/import.
        self.recovery = Recovery(paths.user_data_dir().parent / 'StarlineMabinogiAddonRuntime' / 'recovery.json',
                                 self.backend, lambda: self._can_start() and not self.engine.cancel.is_set())
        self.engine = Engine(self.backend,self.recovery,self._can_start)
        self.dialog = None
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
        self.frames = False
        self.target = None
        self.stream = None
        self.paused = False
        self.closing = False
        self.close_prompted = False
        self.context = None
        self.last_tick = time.monotonic()
        self.frame_status = '이전 FPS 세션 정리 필요 · 측정 중단을 눌러 주세요.' if self.collector.pending else '중단됨 · 측정값 없음'
        self.last_health = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.refresh_access()

    def _can_start(self):
        return (is_creator() and not getattr(self,'closing',False)
                and not getattr(self.window,'_closing',False)
                and not getattr(self.window,'_config_pending_restart',False))

    @property
    def overlay(self):
        if self._overlay is None:
            overlay = self._overlay = MemoOverlay(round(20*self._scale/100))
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
        button = self.window.settings_tab.optimization_button
        button.setVisible(allowed or bool(self.recovery.pending or self.recovery.restart_targets) or self.recovery.corrupt or self.collector.pending)
        button.setText('게임 최적화 · FPS 측정' if allowed else '게임 최적화 복구')
        if not allowed:
            if self.frames: self.stop_frames('제작자 접근이 해제돼 측정을 중단했어요.')
            if self.engine.busy: self.engine.cancel.set()

    def open(self):
        if not is_creator() and not (self.recovery.pending or self.recovery.restart_targets) and not self.recovery.corrupt and not self.collector.pending: return
        if self.dialog is None:
            d = self.dialog = OptimizationDialog(self.window)
            d.inspect.clicked.connect(self.engine.inspect)
            d.start.clicked.connect(self._start_optimization)
            d.stop.clicked.connect(self.engine.stop)
            d.restore.clicked.connect(self._restore_network)
            d.frames_start.clicked.connect(self.start_frames)
            d.frames_stop.clicked.connect(lambda: self.stop_frames())
            d.lock.setChecked(self._overlay.locked if self._overlay is not None else bool((config.load_overlay_state('frameMeter') or {}).get('locked',True)))
            d.lock.toggled.connect(self._lock)
            d.scale.setValue(self._scale)
            d.scale.valueChanged.connect(self._set_scale)
            d.source.currentIndexChanged.connect(self._select_source)
        self.apply_theme()
        self.dialog.show()
        self.dialog.raise_()
        self._tick()

    def apply_theme(self):
        if self.dialog is not None:
            from .main_window import _tab_qss
            from .theme import is_dark
            self.dialog.tabs.setStyleSheet(_tab_qss(is_dark()))

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
        return QMessageBox.question(self.dialog or self.window,'네트워크 재연결',
            '선택한 어댑터의 연결이 잠시 끊길 수 있어요. 통신 중인 다른 앱에도 영향을 줄 수 있어요. 지금 진행할까요?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _start_optimization(self):
        if not self._can_start() or self.engine.busy: return
        d = self.dialog
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
        self.engine.start(options)

    def _restore_network(self):
        if self.engine.busy: return
        if self._network_confirmation(): self.engine.restore_network()

    def start_frames(self):
        if self.frames or not self._can_start(): return
        try:
            presentmon.clock()
            presentmon.executable()
            if not config.load_game_exe(): raise ValueError('설정에서 게임창을 먼저 등록해 주세요.')
            self.frames = True
            self.context = None
            self.frame_status = '게임 실행 대기 · 측정값 없음'
            self._tick()
        except Exception as exc: self._failed(str(exc))

    def stop_frames(self, message='중단됨 · 측정값 없음'):
        self.frames = False
        if not self.collector.stop(): message += "\n" + self.collector.cleanup_problem
        self.target, self.stream, self.context = None, None, None
        self._hide_overlay()
        self.frame_status = message
        if self.dialog is not None: self.dialog.frames_status.setText(message)

    def _collector_ended(self, code):
        if not self.frames: return
        try:
            if self.target is not None and not self.backend.alive(self.target):
                self.collector.stop()
                self.target,self.stream,self.context=None,None,None
                self._hide_overlay()
                self.frame_status='게임 실행 대기 · 측정값 없음'
                return
        except Exception:
            pass
        self._failed('FPS 수집기가 종료됐어요. 권한·계측 상태를 확인하고 다시 시작해 주세요.')

    def _failed(self, message):
        self.stop_frames(message)

    def set_paused(self, paused):
        self.paused = paused
        if paused: self._hide_overlay()

    def _select_source(self):
        if self.stream is not None:
            now, _ = presentmon.clock()
            source=self.dialog.source.currentData()
            _log.info('FPS 대상 수동 선택: %s',source)
            self.stream.select(source,now)
            self._hide_overlay()

    def _line(self, line):
        if not self.frames or self.stream is None: return
        try:
            now, _ = presentmon.clock()
            self.stream.feed(line,now)
        except Exception as exc: self._failed(str(exc))

    def _frame_tick(self, gap):
        game = self.backend.game()
        if game is None and self.target is not None and self.backend.alive(self.target):
            game = self.target
        if game != self.target:
            self.collector.stop()
            self._hide_overlay()
            self.target, self.stream, self.context = game,None,None
            self._reported_source=None
            if game is not None:
                now, frequency = presentmon.clock()
                self.stream = FrameStream(game['pid'],frequency)
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
            self.stream.boundary(now)
            self.context = context
            self._hide_overlay()
        if not active:
            self.stream.boundary(now)
            self._hide_overlay()
            self.frame_status = '게임 비활성 · 표시를 쉬고 있어요.'
            return
        if self.stream.header is not None and self.collector.active and time.monotonic()-self.last_health > 1:
            self.last_health = time.monotonic()
            if presentmon.session_losses(self.collector.session):
                raise RuntimeError('Windows 프레임 이벤트 손실을 감지해 측정을 중단했어요. 값을 추정하지 않아요.')
        result = self.stream.snapshot(now)
        if result['source'] != self._reported_source:
            self._reported_source=result['source']
            _log.info('FPS 대상 확인: pid=%s source=%s candidates=%s',game['pid'],result['source'],len(result['sources']))
        self.frame_status = result['status']
        if result['fps'] is not None and not self.paused:
            self.overlay.set_text(f"{result['fps']:.1f} FPS\n\n제출 프레임")
            self.overlay.show()
        else: self._hide_overlay()
        if self.dialog is not None:
            d = self.dialog
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
        if self.engine.recovery_requested and not self.engine.busy and not self.closing:
            self.engine.recovery_requested = False
            if self.recovery.restart_targets or any(i['kind']!='cpu' for i in self.recovery.pending):
                if self._network_confirmation(): self.engine.restore_network()
        if self.dialog is None: return
        d = self.dialog
        allowed, busy = self._can_start(), self.engine.busy
        for w in (d.cpu,d.tcp,d.rss,d.split,d.adapter,d.inspect,d.start): w.setEnabled(allowed and not busy)
        d.start.setEnabled(allowed and not busy and not self.recovery.corrupt and not (self.recovery.pending or self.recovery.restart_targets))
        d.stop.setEnabled(busy or bool(self.recovery.pending or self.recovery.restart_targets))
        d.restore.setEnabled(not busy and bool(self.recovery.pending or self.recovery.restart_targets))
        for control in (d.lock,d.scale,d.source): control.setEnabled(allowed)
        d.frames_start.setEnabled(allowed and not self.frames)
        d.frames_stop.setEnabled(self.frames or self.collector.pending)
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

    def prepare_close(self):
        if not self.closing:
            self.closing = True
            self.stop_frames()
            self.engine.stop()
        if self.engine.busy: return False
        network = bool(self.recovery.restart_targets) or any(i['kind']!='cpu' for i in self.recovery.pending)
        if network and not self.close_prompted:
            self.close_prompted = True
            if self._network_confirmation():
                self.engine.restore_network()
                return False
        self.timer.stop()
        if self.dialog is not None: self.dialog.close()
        if self._overlay is not None: self._overlay.close()
        return True
