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
from ..optimization.frame_summary import FrameSummary, compare, REASONS, condition_summary, load_reports
from ..optimization.frame_summary_store import SummaryStore
from ..system.optimization import WindowsOptimization
from ..system import presentmon
from .optimization_panel import OptimizationPanel
from .frame_overlay import FrameOverlay
from ..system.perf_metrics import METRICS, PerfSampler


def optimization_badge(recovery, engine, split=None):
    """상단 최적화 상태 한 줄(명세 13.2). (문구, 등급) 또는 None(아무 작업도 없으면 숨김).

    상태만 보여주며 성능 개선을 뜻하지 않는다. 환경 확인(읽기 전용)은 표시하지 않는다."""
    if recovery.corrupt:
        return '최적화: 오류', 'error'
    if engine.busy and engine.task != 'inspect':
        if engine.cancel.is_set() or engine.task == 'restore':
            return '최적화: 원복 중', 'neutral'
        if any(i['kind'] == 'cpu' and i['state'] == 'applied' for i in recovery.pending):
            return ('최적화: 적용 중 ' + split if split else '최적화: 적용 중'), 'neutral'
        return '최적화: 게임 대기', 'neutral'
    if any(i['state'] == 'failed' for i in recovery.pending):
        return '최적화: 오류', 'error'
    if recovery.pending or recovery.restart_targets:
        return '최적화: 원복 대기', 'warn'
    return None


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
        # 오버레이 표시 항목(FPS 명세 8.4). 기본은 FPS만. 표시만 바꾸며 구간 요약·수집에는 영향 없음.
        saved = section.get('metrics')
        saved = saved if isinstance(saved,dict) else {}
        self._metrics = {key: (saved[key] if type(saved.get(key)) is bool else key == 'fps') for key in METRICS}
        self.sampler = PerfSampler()
        # 'FPS 표시' 켜짐은 재실행 후에도 유지(수집 모드는 매번 꺼짐으로 시작). 접근이 확인된 첫 틱에 1회 복원.
        self._restore_display = section.get('display') is True
        self._kept_on = False  # 바꾼 것 없이 켜진 상태는 기록이 없어 재실행하면 꺼짐(13.5)
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
        self._previous_measurement = None  # 직전 측정 1회(시작~중단) 집계: 측정 단위 비교 기준(FPS 7절)
        self._condition_text = None  # '조건별 정리'를 누른 뒤 표시하는 저장 요약 묶음
        self._core_total = None
        self._badge_split = None
        self._badge_wired = False
        self.frames = False
        self.target = None
        self.stream = None
        self.paused = False
        self.closing = False
        self.context = None
        self.last_tick = time.monotonic()
        self.frame_status = ("이전 FPS 세션 정리 필요 · 'FPS 표시'를 한 번 눌러 정리해 주세요." if self.collector.pending
                             else '꺼짐 · 표시 안 함')
        self.last_health = 0.0
        self._delay_logged = time.monotonic()
        self._offered_review = None
        self._offering = False
        self._auto_inspected = False  # 탭을 처음 열 때 환경 확인 1회 자동 실행(13.1)
        self._restoring_selection = False
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._wire_panel()
        self._restore_selection()
        self._tabs_watched = False
        self.refresh_access()

    def _can_start(self):
        return (is_creator() and not getattr(self,'closing',False)
                and not getattr(self.window,'_closing',False)
                and not getattr(self.window,'_config_pending_restart',False))

    @property
    def overlay(self):
        if self._overlay is None:
            overlay = self._overlay = FrameOverlay(self._scale)
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
            if not self._tabs_watched:  # 메인 창 탭은 컨트롤러보다 늦게 생길 수 있어 여기서 한 번 연결
                self._tabs_watched = True
                tabs.currentChanged.connect(lambda _index: self._maybe_auto_inspect())
            if needed and index<0:
                index=tabs.insertTab(tabs.indexOf(self.window._settings_scroll),self.panel,'최적화')
            elif not needed and index>=0:
                if tabs.currentWidget() is self.panel: tabs.setCurrentWidget(self.window._settings_scroll)
                tabs.removeTab(index)
            if needed: tabs.setTabText(index,'최적화')
        if not allowed:
            if self.frames: self.stop_frames('제작자 접근이 해제돼 측정을 중단했어요.')
            if self.engine.busy: self.engine.cancel.set()

    def _update_badge(self):
        badge = getattr(self.window, '_optimization_badge', None)
        if badge is None: return
        if not self._badge_wired:
            self._badge_wired = True
            badge.clicked.connect(self._open_tab)
        state = optimization_badge(self.recovery, self.engine, self._badge_split) if is_creator() else None
        badge.setVisible(state is not None)
        if state is not None:
            text, level = state
            color = {'error': '#e74c3c', 'warn': '#e67e22'}.get(level)
            badge.setText(text)
            badge.setStyleSheet(f'color:{color};' if color else '')

    def _open_tab(self):
        tabs = getattr(self.window, '_tabs', None)
        if tabs is not None and tabs.indexOf(self.panel) >= 0:
            tabs.setCurrentWidget(self.panel)

    # ---- 선택값 저장·환경 확인 자동 실행(명세 13.1) -------------------------------------------
    def _restore_selection(self):
        d, saved = self.panel, config.load_optimization_selection()
        self._restoring_selection = True
        try:
            for key, box in (('cpu', d.cpu), ('tcp', d.tcp), ('rss', d.rss)):
                if key in saved: box.setChecked(saved[key])
        finally:
            self._restoring_selection = False

    def _save_selection(self, *_):
        if self._restoring_selection or self.panel is None: return
        d = self.panel
        selection = dict(cpu=d.cpu.isChecked(), tcp=d.tcp.isChecked(), rss=d.rss.isChecked())
        saved = config.load_optimization_selection()
        # 환경 확인 전(목록이 비어 있음)에는 저장된 배분·어댑터를 지우지 않는다.
        selection['count'] = d.split.currentData() if d.split.currentData() is not None else saved.get('count')
        selection['adapter'] = (d.adapter.currentData() if d.adapter.count() > 1 else saved.get('adapter'))
        config.save_optimization_selection(selection)

    def _maybe_auto_inspect(self):
        if (self._auto_inspected or not hasattr(self.window, '_tabs')
                or self.window._tabs.currentWidget() is not self.panel or not self._can_start() or self.engine.busy):
            return
        self._auto_inspected = True
        self.engine.inspect()  # 읽기 전용(Windows API·PowerShell 조회), 작업 스레드에서 실행

    def _apply_inspection(self, topology, adapters):
        d, saved = self.panel, config.load_optimization_selection()
        notes = []
        self._restoring_selection = True
        try:
            d.split.clear()
            if topology is not None:
                d.cpu_info.setText(f'CPU: {topology.name} · 물리 {len(topology.cores)}개 / 논리 {sum(len(c.cpus) for c in topology.cores)}개')
                count = len([c for c in topology.cores if c.performance])
                self._core_total = len(topology.cores)
                for n in range(1,count):
                    d.split.addItem(f'게임 {n}개 + 백그라운드 물리 코어 {len(topology.cores)-n}개',n)
                index = d.split.findData(saved.get('count')) if 'count' in saved else -1
                if 'count' in saved and index < 0:
                    notes.append(f"저장한 배분(게임 {saved['count']}개)을 이 CPU에서 쓸 수 없어 구조별 기본 배분을 표시해요.")
                d.split.setCurrentIndex(index if index >= 0 else d.split.findData(topology.plan()['count']))
            else:
                d.cpu_info.setText('CPU 구조를 확인하지 못했어요. CPU·RSS 배치를 적용하지 않아요.')
            d.adapter.clear()
            d.adapter.addItem('직접 사용할 물리 어댑터를 선택해 주세요.',None)
            for adapter in adapters:
                d.adapter.addItem(str(adapter['Name']),str(adapter['InterfaceGuid']).strip('{}'))
            wanted = saved.get('adapter')
            if wanted:
                index = next((i for i in range(1, d.adapter.count())
                              if str(d.adapter.itemData(i)).lower() == wanted.lower()), -1)
                if index > 0:
                    d.adapter.setCurrentIndex(index)
                else:
                    notes.append('저장한 네트워크 어댑터를 찾지 못해 선택을 비웠어요. 네트워크 항목을 쓰려면 어댑터를 다시 골라 주세요.')
        finally:
            self._restoring_selection = False
        if notes:
            d.cpu_info.setText(d.cpu_info.text() + '\n' + '\n'.join(notes))

    def _wire_panel(self):
        d=self.panel
        for box in (d.cpu, d.tcp, d.rss): box.toggled.connect(self._save_selection)
        d.split.currentIndexChanged.connect(self._save_selection)
        d.adapter.currentIndexChanged.connect(self._save_selection)
        d.inspect.clicked.connect(self.engine.inspect)
        d.toggle.clicked.connect(self._toggle_optimization)
        d.frames_toggle.clicked.connect(self._toggle_frames)
        d.lock.setChecked(bool((config.load_overlay_state('frameMeter') or {}).get('locked',True)))
        d.lock.toggled.connect(self._lock)
        d.scale.setValue(self._scale)
        d.scale.valueChanged.connect(self._set_scale)
        for key, box in d.metric_boxes.items():
            box.setChecked(self._metrics[key])
            box.toggled.connect(lambda on, key=key: self._set_metric(key, on))
        d.summary_collect.toggled.connect(self._toggle_summary_collection)
        d.summary_save.clicked.connect(self._save_summary)
        d.summary_folder.clicked.connect(self._open_summary_folder)
        d.summary_conditions.clicked.connect(self._show_conditions)
        d.condition.textChanged.connect(self._condition_changed)
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

    def _save_overlay(self, **extra):
        raw=config._read_local_config()
        section=raw.get('frameMeter')
        section=section if isinstance(section,dict) else {}
        section.update(scale=self._scale,metrics=dict(self._metrics),**extra)
        if self._overlay is not None:  # 오버레이를 아직 만들지 않았어도 배율·표시 항목·표시 켜짐은 저장한다
            section.update(overlay=dict(x=self.overlay.x(),y=self.overlay.y(),locked=self.overlay.locked))
        raw['frameMeter']=section
        config._write_local_config(raw)

    def _set_scale(self, percent):
        if not self._can_start(): return
        self._scale=max(50,min(300,int(percent)))
        self.overlay.set_scale(self._scale)
        self._save_overlay()

    def _set_metric(self, key, on):
        if not self._can_start(): return
        self._metrics[key] = bool(on)
        self._save_overlay()

    def overlay_items(self, fps, values):
        """켠 항목만 (이름, 값, 단위)로. 값을 아직 못 읽었으면 '—'."""
        def percent(value):
            return ('—', '') if value is None else (f'{value:.0f}', '%')
        items = []
        if self._metrics['fps']: items.append(('FPS', f'{fps:.0f}', ''))
        if self._metrics['cpu']: items.append(('CPU', *percent(values.get('cpu'))))
        if self._metrics['gpu']: items.append(('GPU', *percent(values.get('gpu'))))
        if self._metrics['memory']:
            memory = values.get('memory')
            items.append(('메모리', '—', '') if memory is None else ('메모리', f'{memory/1024**3:.1f}', 'GB'))
        return items

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
        self._badge_split = (f"{options['count']}+{self._core_total-options['count']}"
                             if options['cpu'] and self._core_total else None)
        self._kept_on = True  # 이미 목표값이라 바꾼 것이 없어도 켜짐으로 보여준다(13.5)
        self._summary_requested = {key: options[key] for key in ('cpu','count','tcp','rss')}
        self._summary_requested['adapter_selected'] = bool(options['adapter'])
        self._summary_state = None
        if self.stream is not None:
            self.stream.boundary(presentmon.clock()[0], 'optimization_start_request')
        self.engine.start(options)

    # ---- 토글 하나(명세 13.5) -------------------------------------------------------------------
    def _optimization_on(self):
        """켜짐: 세션 진행 중, 되돌릴 변경(원복 대기 포함)이 남음, 또는 바꾼 것 없이 목표 상태로 시작한 뒤 아직 끄지 않음."""
        if self.engine.busy and self.engine.task == 'session':
            return True
        if self.recovery.pending or self.recovery.restart_targets:
            return True
        return self._kept_on

    def _toggle_optimization(self, _checked=False):
        if not self._optimization_on():
            self._start_optimization()
        elif self.engine.busy or self.recovery.pending or self.recovery.restart_targets:
            self._kept_on = False
            self._restore_all()
        else:
            # 바꾼 것 없이 켜졌던 상태: 되돌릴 기록이 없으니 바로 끄고, 원복 실패로 오해하지 않게 알린다.
            self._kept_on = False
            self.engine.status = '원래부터 같은 값이라 되돌릴 것이 없어요.'
        self._sync_optimization_toggle()

    def _sync_optimization_toggle(self):
        if self.panel is None: return
        engine = self.engine
        if not engine.busy and engine.session_end is not None:
            # 게임 종료·Governor·중단·오류로 끝난 세션은 남은 변경이 없으면 꺼진다. 네트워크만 한 세션은 켜짐 유지.
            if engine.session_end != 'network_only':
                self._kept_on = False
            engine.session_end = None
        on = self._optimization_on()
        toggle = self.panel.toggle
        if toggle.isChecked() != on:
            toggle.blockSignals(True); toggle.setChecked(on); toggle.blockSignals(False)
        waiting = on and not engine.busy and bool(
            any(i['kind'] != 'cpu' for i in self.recovery.pending) or self.recovery.restart_targets)
        toggle.setText('최적화 적용 중 · 네트워크 원복 대기' if waiting else '최적화 적용 중' if on else '최적화 시작')
        allowed = self._can_start()
        toggle.setEnabled(True if on and (engine.busy or self.recovery.pending or self.recovery.restart_targets)
                          else allowed and not engine.busy and not self.recovery.corrupt)

    def _restore_all(self):
        """'중단 · 원복': 세션을 멈추고 적용했던 CPU·네트워크를 모두 되돌린다. 네트워크가 포함되면
        시작할 때처럼 연결 끊김 확인을 한 번 받는다. 거절하면 CPU만 되돌리고 네트워크는 '원복 대기'로
        남긴다(명세 6절: 게임 중 연결을 끊지 않고 CPU만 멈추는 경로).
        제작자 접근이 없으면 CPU만 원복한다(네트워크 원복은 기존처럼 접근 필요)."""
        network = (any(i['kind'] != 'cpu' for i in self.recovery.pending) or bool(self.recovery.restart_targets))
        network = network and self._can_start()
        normalized = network and bool(self.recovery.normalized_review)
        deferred = False
        if network and not (self._normalized_confirmation() if normalized else self._network_confirmation()):
            network, normalized, deferred = False, False, True
        self._summary_requested = dict(action='restore_all' if network else 'stop_cpu')
        self._summary_state = None
        if self.stream is not None:
            self.stream.boundary(presentmon.clock()[0], 'optimization_stop_request')
        self.engine.stop_and_restore(network=network, accept_normalized=normalized, network_deferred=deferred)

    def _normalized_confirmation(self):
        """장치가 앱 적용값을 정규화한 RSS 항목을 원본으로 다시 쓸지 묻는다(값을 보여주고 확인)."""
        lines = []
        for entry in self.recovery.normalized_review[:4]:
            cur, old = entry['current'], entry['old']
            lines.append(f"현재 최대 CPU {cur['MaxProcessorNumber']} · {cur['MaxProcessors']}개 → "
                         f"원본 최대 CPU {old['MaxProcessorNumber']} · {old['MaxProcessors']}개")
        return QMessageBox.question(self.panel or self.window,'RSS 원본으로 되돌리기',
            '장치가 앱이 쓴 RSS 값을 자체 규칙으로 조정해 기록과 달라졌어요. 앱이 쓴 값이 조정된 것으로 '
            '확인돼요.\n\n' + '\n'.join(lines) + '\n\n원본 값으로 다시 기록할까요? 선택한 어댑터의 연결이 '
            '잠시 끊길 수 있어요.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _offer_normalized_restore(self):
        """원복 중 '장치 정규화'가 감지되면 다시 누르게 하지 않고 바로 확인 창을 띄운다(감지당 1회)."""
        review = self.recovery.normalized_review
        if (not review or review is self._offered_review or self._offering or self.engine.busy
                or self.panel is None or not self._can_start()):
            return
        self._offering = True
        self._offered_review = review  # 거절하면 같은 감지로 다시 묻지 않는다('중단 · 원복'으로 재시도 가능)
        try:
            if self._normalized_confirmation():
                self._summary_requested = dict(action='restore_network')
                self._summary_state = None
                if self.stream is not None:
                    self.stream.boundary(presentmon.clock()[0], 'network_restore_request')
                self.engine.restore_network(accept_normalized=True)
        finally:
            self._offering = False

    def start_frames(self):
        if self.frames or not self._can_start(): return
        try:
            presentmon.clock()
            presentmon.executable()
            if not config.load_game_exe(): raise ValueError('설정에서 게임창을 먼저 등록해 주세요.')
            if self.summary.measurement() is not None:
                self._previous_measurement = self.summary.measurement()  # 새 측정의 비교 기준
            self.summary = FrameSummary()
            self.summary.closed_callback = self._summary_closed
            if self.panel is not None: self.summary.set_condition(self.panel.condition.text())
            self._summary_state = None
            self.frames = True
            self.context = None
            self.frame_status = '표시 중 · 게임 실행 대기'
            self._tick()
        except Exception as exc: self._failed(str(exc))

    def _toggle_frames(self, on):
        """'FPS 표시' 토글: 켜기 = 기존 측정 시작, 끄기 = 측정 중단(동작 변경 없음). 이전 세션 정리도 끄기로 처리."""
        if on and not self.collector.pending:
            self.start_frames()
        else:
            self.stop_frames()
        self._sync_frames_toggle()
        if self._can_start():
            self._restore_display = False
            self._save_overlay(display=bool(on and self.frames))  # 사용자가 바꾼 표시 켜짐만 저장(종료·접근 해제는 저장 안 함)

    def _sync_frames_toggle(self):
        if self.panel is None: return
        toggle = self.panel.frames_toggle
        if toggle.isChecked() != self.frames:
            toggle.blockSignals(True); toggle.setChecked(self.frames); toggle.blockSignals(False)
        toggle.setText('FPS 표시 중' if self.frames else 'FPS 표시')

    def stop_frames(self, message='꺼짐 · 표시 안 함'):
        if self.stream is not None:
            self.stream.boundary(self._summary_now(), 'measurement_stop')
        self.frames = False
        if not self.collector.stop(): message += "\n" + self.collector.cleanup_problem
        self.target, self.stream, self.context = None, None, None
        self.sampler.update((), None)
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
                self.frame_status='표시 중 · 게임 실행 대기'
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
                self.frame_status = '표시 중 · 최신 프레임을 기다려요.'
        if game is None:
            self.frame_status = '표시 중 · 게임 실행 대기'
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
            self.sampler.update((), None)  # 게임 밖에서는 지표 조회도 쉰다
            self._hide_overlay()
            self.frame_status = '표시 중 · 게임 비활성이라 쉬고 있어요.'
            return
        if time.monotonic() - self._delay_logged >= 60:
            self._delay_logged = time.monotonic()
            report = self.stream.delay_report()
            if report: _log.info('FPS 이벤트 도착 지연(최근 약 60초): %s', report)  # PresentMon 출력 묶임 실측(0.13.3)
        if self.stream.header is not None and self.collector.active and time.monotonic()-self.last_health > 1:
            self.last_health = time.monotonic()
            if presentmon.session_losses(self.collector.session):
                raise RuntimeError('Windows 프레임 이벤트 손실을 감지해 측정을 중단했어요. 값을 추정하지 않아요.')
        self._sync_summary_context(now)
        result = self.stream.snapshot(now)
        if result['source'] != self._reported_source:
            self._reported_source=result['source']
            _log.info('FPS 대상 확인: pid=%s source=%s candidates=%s',game['pid'],result['source'],len(result['sources']))
        self.frame_status = '표시 중 · ' + result['status']
        # 추가 지표는 작업 스레드에서 1초마다 읽은 최신 값만 쓴다(UI 스레드에서 OS 조회 없음).
        self.sampler.update([k for k, on in self._metrics.items() if on and k != 'fps'], game['pid'])
        items = self.overlay_items(result['fps'], self.sampler.latest) if result['fps'] is not None else []
        if items and not self.paused:
            self.overlay.set_items(items)
            self.overlay.show()
        else: self._hide_overlay()

    def _tick(self):
        now = time.monotonic()
        gap, self.last_tick = now-self.last_tick, now
        self.refresh_access()
        if self._restore_display and self._can_start():
            self._restore_display = False
            # 이전 FPS 세션 정리가 남아 있으면 켜지 않고 기존 정리 안내를 둔다.
            if not self.collector.pending and not self.frames:
                self.start_frames()
        if self.frames:
            try: self._frame_tick(gap)
            except Exception as exc: self._failed(str(exc))
            if self.frames and self.summary.full:
                self.stop_frames('구간/전환 요약 한도 · 기존 자료를 보존하고 측정을 중단했어요.')
        if self.engine.recovery_requested and not self.engine.busy:
            self.engine.recovery_requested = False
        self._offer_normalized_restore()
        self._update_badge()
        if self.panel is None: return
        self._poll_summary_store()
        self._render_summary()
        d = self.panel
        allowed, busy = self._can_start(), self.engine.busy
        for w in (d.cpu,d.tcp,d.rss,d.split,d.adapter,d.inspect): w.setEnabled(allowed and not busy)
        self._sync_optimization_toggle()
        for control in (d.lock,d.scale,*d.metric_boxes.values()): control.setEnabled(allowed)
        d.frames_toggle.setEnabled((allowed and not self.closing) or self.frames or self.collector.pending)
        self._sync_frames_toggle()
        for control in (d.summary_collect,d.summary_save,d.summary_folder): control.setEnabled(allowed)
        d.frames_status.setText(self.frame_status)
        d.status.setText(('복구 기록이 손상돼 새 적용을 차단했어요. 추정값으로 원복하지 않아요.\n기록: '+str(self.recovery.path)) if self.recovery.corrupt else self.engine.status)
        from collections import Counter
        counts=Counter((item['kind'],item['state']) for item in self.recovery.items)
        kinds={'cpu':'CPU 배치','ack':'TcpAckFrequency','nodelay':'TCPNoDelay','autotuning':'TCP 자동 조정','rss':'RSS'}
        states={'prepared':'적용 확인 필요','applied':'적용됨','failed':'미적용·확인 필요','restored':'원복됨',
                'released':'외부 변경·관리 제외'}
        lines=[f'{kinds[kind]} · {states[state]} {count}개' for (kind,state),count in counts.items()]
        if self.recovery.restart_targets: lines.append(f'네트워크 재연결 대기: {len(self.recovery.restart_targets)}개 어댑터')
        d.results.setText('\n'.join(lines))
        if self.engine.inspection is not None:
            topology, adapters = self.engine.inspection
            self.engine.inspection = None
            self._apply_inspection(topology, adapters)

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
        # 수집은 FPS 표시가 켜져 있을 때만 동작한다(표시를 자동으로 켜지 않음). 꺼져 있으면 파일을 쓰지 않고 안내만.
        self._render_summary(force=True)

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

    def _condition_changed(self, text):
        """측정 조건 이름은 측정 1회에 하나: 측정 중 바꾸면 다음 측정부터 적용해 한 측정에 이름이 섞이지 않게 한다."""
        if self.frames:
            self._summary_message = '측정 조건 변경은 다음 측정부터 적용돼요(현재 측정: ' + (self.summary.condition or '조건 이름 없음') + ').'
            self._render_summary(force=True)
        elif not self.summary.records and not self.summary.samples:
            self.summary.set_condition(text)  # 아직 자료가 없는 측정. 끝난 측정의 이름은 바꾸지 않는다(시작 때 반영).

    def _show_conditions(self):
        """저장된 요약을 조건 이름별로 묶어 구간 값의 중앙값·범위를 보여준다(FPS 7절)."""
        if not self._can_start(): return
        reports = load_reports(self.summary_store.folder)
        groups = condition_summary(reports)
        if not groups:
            self._condition_text = '조건별 정리 · 비교할 저장 요약이 없어요. 수집 모드나 요약 저장으로 남겨 주세요.'
        else:
            lines = [f'조건별 정리 · 저장 요약 {len(reports)}개 · 구간 값의 중앙값 [최소~최대]']
            for g in groups:
                low, long = g['segment_low_1pct_fps'], g['segment_long_per_minute']
                line = (f"■ {g['condition']} (구간 {g['segments']}개 · 측정 {g['measurements']}회)\n"
                        f"    1% low {low['median']:.1f} [{low['minimum']:.1f}~{low['maximum']:.1f}] FPS · "
                        f"긴 간격 분당 {long['median']:.1f} [{long['minimum']:.1f}~{long['maximum']:.1f}]회")
                whole = g['measurement_low_1pct_fps']
                if whole:
                    line += (f" · 측정 전체 1% low {whole['minimum']:.1f}~{whole['maximum']:.1f} FPS"
                             if whole['count'] > 1 else f" · 측정 전체 1% low {whole['median']:.1f} FPS")
                lines.append(line)
            lines.append('구간 1% low를 평균해 조건 전체 1% low로 쓰지 않아요. 같은 장면에서 여러 번 측정해 범위를 비교해 주세요.')
            self._condition_text = '\n'.join(lines)
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
            d.summary_select.addItem(f'측정 전체 · 완료 구간 {len(self.summary.records)}개 기준','measurement')
            for index, record in enumerate(self.summary.records):
                d.summary_select.addItem(f"구간 {index+1} · {record['measured_seconds']:.1f}초 · {REASONS.get(record['end_reason'], '구간 종료')}",index)
            d.summary_select.setCurrentIndex(max(0,d.summary_select.findData(selected)))
            d.summary_select.blockSignals(False)
            d._summary_signature = signature
        index = d.summary_select.currentData()
        d.condition_result.setText(self._condition_text or '')
        d.condition_result.setVisible(bool(self._condition_text))
        if index == 'measurement':
            d.summary_result.setText(self._measurement_text())
            d.summary_path.setText(f'저장 위치: {self.summary_store.folder} · {self._collect_message()}')
            return
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
                    f"중앙값 2배 초과 {record['relative_long_count']}회 (분당 {record['relative_long_per_minute']:.1f}회)"
                    " · 설정/대상 전환은 별도 구간")
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
        d.summary_path.setText(f'저장 위치: {self.summary_store.folder} · {self._collect_message()}')
        d.summary_path.setToolTip(str(self.summary_store.folder))

    def _collect_message(self):
        if self._summary_collecting and not self.frames:
            return '수집 모드 켜짐 · FPS 표시가 꺼져 있어 수집하지 않아요. 위에서 FPS 표시를 켜면 시작해요.'
        return self._summary_message

    def _measurement_text(self):
        """측정 1회(시작~중단) 전체 집계와 직전 측정 비교(FPS 7절). 진행 중이면 완료 구간까지만."""
        whole = self.summary.measurement()
        name = self.summary.condition or '조건 이름 없음'
        if whole is None:
            return f'측정 전체 · {name}\n완료된 구간이 아직 없어요. 측정을 중단하거나 60초 구간이 끝나면 표시해요.'
        low = '자료 부족(100개 미만)' if whole['low_1pct_fps'] is None else f"{whole['low_1pct_fps']:.1f} FPS"
        text = (f"측정 전체 · {name}{' (측정 중 · 완료 구간까지)' if self.frames else ''}\n"
                f"구간 {whole['segments']}개 · 측정 {whole['measured_seconds']:.1f}초 · 유효 간격 {whole['valid_intervals']:,}개\n"
                f"평균 {whole['average_fps']:.1f} FPS · 1% low {low} (구간 평균이 아닌 전체 간격으로 계산)\n"
                f"간격 변동계수 {whole['variation_percent']:.1f}% · 긴 간격 분당 {whole['relative_long_per_minute']:.1f}회"
                f" (총 {whole['relative_long_count']}회)")
        if whole['conditions_recorded'] > 1:
            text += f"\n측정 중 설정·대상 변경 {whole['conditions_recorded']-1}회 포함 · 조건이 섞인 측정이에요."
        previous = self._previous_measurement
        if previous is None:
            return text + '\n이전 측정 없음 · 다음 측정부터 직전 측정과 비교해요.'
        comparison = compare(previous, whole)
        text += f"\n직전 측정({previous['condition'] or '조건 이름 없음'}) 대비"
        if comparison['status'] != 'insufficient':
            text += (f" 평균 {comparison['average_fps_delta']:+.1f} · 1% low {comparison['low_1pct_fps_delta']:+.1f} FPS"
                     f" · 긴 간격 분당 {comparison['long_per_minute_delta']:+.1f}회")
        return text + '\n' + comparison['message']

    def prepare_close(self):
        if not self.closing:
            self.closing = True
            self.stop_frames()
            self.sampler.stop()
            self.engine.stop()
        if self.engine.busy: return False
        self._poll_summary_store()
        if not self.summary_store.close_ready(): return False
        self.timer.stop()
        if self.panel is not None: self.panel.close()
        if self._overlay is not None: self._overlay.close()
        return True
