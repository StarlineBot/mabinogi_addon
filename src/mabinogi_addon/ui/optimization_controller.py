"""Creator tools lifetime is owned by the app, not by the settings dialog."""
import time
import logging

_log = logging.getLogger(__name__)
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox
from .. import config, paths
from ..feature_access import Recheck, is_creator, optimization_available
from ..optimization.session import NETWORK_KINDS, PROCESS_KINDS, Recovery
from ..optimization.engine import Engine
from ..optimization.frames import FrameStream
from ..optimization.frame_summary import FrameSummary, compare, REASONS, condition_summary, load_reports
from ..optimization.frame_summary_store import SummaryStore
from ..system.optimization import WindowsOptimization
from ..system import presentmon
from .optimization_panel import OptimizationPanel
from .frame_overlay import FrameOverlay
from ..system.perf_metrics import METRICS, PerfSampler


# 상단 최적화 배지 색(0.17.2 사용자 결정): 블랙박스·전투 보조와 같은 모양('● 최적화: …', 한 색, 밑줄 없음)
BADGE_COLORS = {'applied': '#2ecc71', 'neutral': '#8a8f98', 'warn': '#e67e22', 'error': '#e74c3c'}
BADGE_TIP = '최적화 상태예요. 성능 개선을 뜻하지 않아요. 누르면 최적화 탭으로 이동해요.'


def badge_color(text, level):
    """적용 중 초록 · 게임 대기·원복 중(그 밖의 neutral) 회색 · 원복 대기 주황 · 오류 빨강."""
    if level == 'neutral':
        return BADGE_COLORS['applied' if text.startswith('최적화: 적용 중') else 'neutral']
    return BADGE_COLORS.get(level, BADGE_COLORS['neutral'])


def optimization_badge(recovery, engine, split=None, *, restore_wait=False, kept_on=False):
    """상단 최적화 상태 한 줄(명세 13.2). (문구, 등급) 또는 None(아무 작업도 없으면 숨김).

    상태만 보여주며 성능 개선을 뜻하지 않는다. 환경 확인(읽기 전용)은 표시하지 않는다.
    13.5 보정: 원복을 요청하지 않은 네트워크 변경·바꾼 것 없이 켜진 상태는 '적용 중'(기본색),
    원복을 미뤘거나 실패했거나 지난 실행 기록이 남은 경우만 '원복 대기'(경고색)."""
    if recovery.corrupt:
        return '최적화: 오류', 'error'
    if engine.busy and engine.task != 'inspect':
        if engine.cancel.is_set() or engine.task == 'restore':
            return '최적화: 원복 중', 'neutral'
        if getattr(engine, 'held', False):
            return '최적화: 보류', 'neutral'  # 13.10 자동 적용 중 Process Lasso Governor 실행
        if any(i['kind'] in PROCESS_KINDS and i['state'] == 'applied' for i in recovery.pending):
            return ('최적화: 적용 중 ' + split if split else '최적화: 적용 중'), 'neutral'
        return '최적화: 게임 대기', 'neutral'
    if any(i['state'] == 'failed' for i in recovery.pending):
        return '최적화: 오류', 'error'
    if recovery.pending or recovery.restart_targets:
        return ('최적화: 원복 대기', 'warn') if restore_wait else ('최적화: 적용 중', 'neutral')
    if kept_on:
        return '최적화: 적용 중', 'neutral'
    return None


def object_particle(word: str) -> str:
    """목적격 조사: 마지막 글자에 받침이 있으면 '을', 없으면 '를'(한글이 아니면 '을(를)')."""
    last = word.rstrip()[-1:] if word.strip() else ''
    if not last or not '가' <= last <= '힣':
        return '을(를)'
    return '을' if (ord(last) - 0xAC00) % 28 else '를'


class OptimizationController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        # 제작자 확인은 config.json 읽기라 FPS 줄(초당 수백 개)·타이머마다 하지 않고 1초 동안 재사용한다(0.17.2).
        # 로그인 변경(login_changed → refresh_access)에는 바로 다시 확인한다.
        self._access = Recheck(lambda: optimization_available())  # 2026-10-28 기능 공개 정책 7절: 모든 사용자
        self._creator = Recheck(lambda: is_creator())  # FPS 수집 모드(구간 요약 파일)는 제작자만
        self.backend = WindowsOptimization()
        # Machine-local recovery must never travel in a settings export/import.
        self.recovery = Recovery(paths.user_data_dir().parent / 'StarlineMabinogiAddonRuntime' / 'recovery.json',
                                 self.backend, lambda: self._can_start() and not self.engine.cancel.is_set())
        self.engine = Engine(self.backend,self.recovery,self._can_start)
        self.panel = OptimizationPanel(window)
        # 탭에 붙기 전에는 메인 창의 맨 자식이라 창이 보일 때 왼쪽 위(0,0)에 조각으로 함께 그려진다 → 붙을 때까지 숨긴다
        self.panel.hide()
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
        # 13.10: 자동 적용을 켜 두었으면 접근이 확인된 첫 틱에 한 번 게임 대기를 시작한다(앱 시작 = 라쏘와 같은 체감).
        self._auto_pending = config.load_optimization_selection().get('auto') is True
        self._restore_retry_at, self._restore_tries = 0.0, 0
        # 수집기 오류로 꺼진 'FPS 표시'의 자동 재시작(0.13.5): 약 5초 뒤, 10분에 3회까지. 저장된 표시 설정은 바꾸지 않는다.
        self._restart_at = None
        self._restarts = []
        self._kept_on = False  # 바꾼 것 없이 켜진 상태는 기록이 없어 재실행하면 꺼짐(13.5)
        # '원복 대기'(확인 필요): 원복을 미뤘거나 실패했거나, 지난 실행에서 되돌리지 못한 기록이 남아 시작한 경우.
        self._restore_wait = self._network_left()  # 원복 대기는 네트워크만(그래픽 효율만 남으면 '적용 중', 0.23.0 QA)
        self._restore_requested = False
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
        self._layouts = {}  # 환경 확인으로 만든 CPU 배치 {키: Layout}(13.11)
        self._auto_adapter = None  # 인터넷 기본 경로 연결 GUID(13.12, 판단 불가면 None)
        self._gpu = None  # 13.6 NVIDIA 그래픽카드 이름(환경 확인 결과, 아니면 None)
        self._gpu_checked = False
        self._logged_status = None  # app.log에 남긴 마지막 세션 기록(13.13: 상세는 항상 로그에)
        # 시작이 막힌 이유·환경 확인 실패(13.13 QA 후속): 접힌 상세에만 두면 버튼이 무반응처럼 보여 상태 줄에 주황으로 보인다.
        # 다시 시작하거나 선택을 바꾸거나 환경 확인을 다시 하면 지운다.
        self._notice = None
        self._inspect_notice = None  # 환경 확인 실패 안내(다시 확인해야 지워짐)
        self._badge_split = None
        self._badge_wired = False
        self.frames = False  # 측정 파이프라인(PresentMon 수집기) 동작 중: FPS 표시 또는 수집 모드가 켜져 있을 때
        self._collect_only = False  # 수집 모드만 켜서 측정 중(FPS 표시 꺼짐 → 오버레이 없음, FPS 명세 9절)
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
        return (self._access() and not getattr(self,'closing',False)
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

    def refresh_access(self, recheck=True):
        if recheck:  # 로그인 변경 등 외부 요청: 설정을 바로 다시 읽는다
            self._access.invalidate(); self._creator.invalidate()
        allowed = self._can_start()
        needed = self._access()
        creator = allowed and self._creator()
        if self.panel is not None:
            self.panel.collect_box.setVisible(creator)
        if not creator and getattr(self, '_summary_collecting', False) and self.panel is not None:
            self.panel.summary_collect.setChecked(False)  # 수집 권한이 없어지면 수집 모드도 끈다
        if hasattr(self.window,'_tabs'):
            tabs=self.window._tabs;index=tabs.indexOf(self.panel)
            if not self._tabs_watched:  # 메인 창 탭은 컨트롤러보다 늦게 생길 수 있어 여기서 한 번 연결
                self._tabs_watched = True
                tabs.currentChanged.connect(lambda _index: self._maybe_auto_inspect())
            if needed and index<0:
                # 탭 순서 … · 최적화 · 블랙박스 · 설정(2026-10-26 사용자 결정): 블랙박스가 이미 있으면 그 앞에
                blackbox = getattr(getattr(self.window, 'blackbox_tools', None), '_page', None)
                before = tabs.indexOf(blackbox) if blackbox is not None else -1
                index=tabs.insertTab(before if before >= 0 else tabs.indexOf(self.window._settings_scroll),self.panel,'최적화')
            elif not needed and index>=0:
                if tabs.currentWidget() is self.panel: tabs.setCurrentWidget(self.window._settings_scroll)
                tabs.removeTab(index)
            if needed: tabs.setTabText(index,'최적화')
        if not allowed:
            if self.frames: self.stop_frames('사용할 수 없게 돼 측정을 중단했어요.')
            if self.engine.busy: self.engine.cancel.set()

    def _update_badge(self):
        badge = getattr(self.window, '_optimization_badge', None)
        if badge is None: return
        if not self._badge_wired:
            self._badge_wired = True
            badge.clicked.connect(self._open_tab)
        state = (optimization_badge(self.recovery, self.engine, self._badge_split,
                                    restore_wait=self._restore_wait, kept_on=self._kept_on) if self._access() else None)
        badge.setVisible(state is not None)
        if state is not None:
            text, level = state
            color = badge_color(text, level)
            badge.setText('● ' + text)
            style = getattr(type(self.window), 'status_style', None)
            badge.setStyleSheet(style(color) if style else f'color:{color}; font-size:12px; border:none;')
            badge.setToolTip(BADGE_TIP)

    def _open_tab(self):
        tabs = getattr(self.window, '_tabs', None)
        if tabs is not None and tabs.indexOf(self.panel) >= 0:
            tabs.setCurrentWidget(self.panel)

    # ---- 선택값 저장·환경 확인 자동 실행(명세 13.1) -------------------------------------------
    def _restore_selection(self):
        d, saved = self.panel, config.load_optimization_selection()
        self._restoring_selection = True
        try:
            for key, box in (('priority', d.priority), ('tcp', d.tcp), ('auto', d.auto), ('graphics', d.graphics)):
                if key in saved: box.setChecked(saved[key])
            if 'tcp' not in saved:
                d.tcp.setChecked(True)  # 13.14: 처음 쓰는 사용자 기본값은 추천(패스트핑 포함). 기존 저장은 유지
            if 'graphics' not in saved:
                d.graphics.setChecked(True)  # 13.6: 추천에 포함(NVIDIA일 때만 적용)
            d.advanced_toggle.setChecked(saved.get('advanced') is True)
        finally:
            self._restoring_selection = False

    def _save_selection(self, *_):
        if self._restoring_selection or self.panel is None: return
        if self._notice and self._notice != self._inspect_notice:
            self._notice = None  # 고른 항목이 바뀌면 시작 차단 안내는 지운다(환경 확인 실패 안내는 다시 확인 때까지)
        d = self.panel
        selection = dict(priority=d.priority.isChecked(), tcp=d.tcp.isChecked(), auto=d.auto.isChecked(),
                         advanced=d.advanced_toggle.isChecked(), graphics=d.graphics.isChecked())
        saved = config.load_optimization_selection()
        # 환경 확인 전(목록이 비어 있음)에는 저장된 배치·어댑터를 지우지 않는다(13.11: 배분 숫자 대신 배치 이름 키).
        layout = self._layout_key()
        if layout is not None:
            selection['layout'] = layout
            selection['cpu'] = layout != 'none'
        selection['adapter'] = (d.adapter.currentData() if d.adapter.count() > 1 else saved.get('adapter'))
        config.save_optimization_selection(selection)

    # ---- CPU 배치 이름(명세 13.11) -----------------------------------------------------------------
    def _layout_key(self):
        """고른 배치 키. 환경 확인 전(목록 비어 있음)이면 저장값, 그것도 없으면 None."""
        data = self.panel.split.currentData() if self.panel is not None else None
        if data is not None:
            return data
        saved = config.load_optimization_selection()
        if 'layout' in saved:
            return saved['layout']
        return 'none' if saved.get('cpu') is False else None

    def _cpu_selected(self):
        """CPU 배치를 적용하는지('배치 안 함'이 아닌지). 환경 확인 전이고 저장값도 없으면 추천을 쓰므로 True."""
        key = self._layout_key()
        if key is None:
            return True
        layout = self._layouts.get(key)
        return key != 'none' and (layout is None or layout.applies)

    @staticmethod
    def _saved_layout(saved, topology):
        """저장한 배치 키. 예전 저장(배분 숫자·CPU 체크)은 같은 뜻의 이름으로 옮긴다."""
        if 'layout' in saved:
            return saved['layout']
        if saved.get('cpu') is False:
            return 'none'
        count = saved.get('count')
        if type(count) is int:
            rest = len(topology.cores) - count
            key = {2: 'focus', 1: 'max_focus'}.get(rest) if len(topology.cores) > 6 else ('focus' if rest == 1 else None)
            return key or f'count:{count}'  # 같은 뜻의 이름이 없으면 '쓸 수 없음' 안내 뒤 추천
        return None

    # ---- 추천 최적화·결과 요약(명세 13.13·13.14) -------------------------------------------------
    def _recommendation(self):
        """이 PC 추천: 게임 우선순위 높음 + CPU 종류별 1순위 배치(13.11) + 패스트핑(자동 선택 연결, 13.12)."""
        first = next(iter(self._layouts.values()), None)
        return dict(priority=True, layout=first.key if first else None, tcp=True, adapter=self._auto_adapter)

    def _is_custom(self):
        """상세에서 하나라도 추천과 다르게 골랐는지. 환경 확인 전에는 알 수 있는 항목만 비교한다."""
        d = self.panel
        if d is None:
            return False
        rec = self._recommendation()
        if not d.priority.isChecked() or not d.tcp.isChecked():
            return True
        if self._gpu and not d.graphics.isChecked():
            return True
        if rec['layout'] is not None and d.split.currentData() not in (None, rec['layout']):
            return True
        chosen = d.adapter.currentData()
        return rec['adapter'] is not None and chosen is not None and str(chosen).lower() != rec['adapter'].lower()

    def _graphics_on(self):
        """13.6: 그래픽 효율을 쓸지(체크 + NVIDIA)."""
        return bool(self._gpu) and self.panel is not None and self.panel.graphics.isChecked()

    def _detect_gpu(self):
        """환경 확인 전(앱 시작 자동 적용 등)에 한 번 NVIDIA 여부를 읽는다."""
        if not self._gpu_checked:
            self._gpu_checked = True
            try:
                graphics = getattr(self.backend, 'graphics', None)
                self._gpu = graphics() if graphics is not None else None
            except Exception:
                self._gpu = None
            self._show_gpu()
        return self._gpu

    def _show_gpu(self):
        d = self.panel
        if d is None:
            return
        d.gpu_label.setText(f'{self._gpu} · 최대 프레임 400' if self._gpu else 'NVIDIA 그래픽카드에서만 쓸 수 있어요')

    def _describe(self, priority, layout_key, tcp, graphics=False):
        parts = []
        if priority:
            parts.append('게임 우선순위 높음')
        layout = self._layouts.get(layout_key)
        if layout is not None:
            parts.append(f'CPU 배치 {layout.name} ({layout.short})' if layout.applies else 'CPU 배치 안 함')
        elif layout_key is None:
            parts.append('CPU 배치(환경 확인 뒤 표시)')
        if tcp:
            parts.append('패스트핑' if self._auto_adapter or self.panel.adapter.currentData() else '패스트핑(연결 선택 필요)')
        if graphics and self._gpu:
            parts.append('그래픽 효율')
        return ' · '.join(parts) or '고른 항목 없음'

    def _update_recommendation(self):
        d = self.panel
        if d is None: return
        custom = self._is_custom()
        if custom:
            text = '직접 고른 설정: ' + self._describe(d.priority.isChecked(), d.split.currentData(), d.tcp.isChecked(), d.graphics.isChecked())
        else:
            rec = self._recommendation()
            text = '이 PC 추천: ' + self._describe(True, rec['layout'], True, True)
        if d.recommend.text() != text:
            d.recommend.setText(text)
        d.reset_recommended.setVisible(custom)

    def _reset_to_recommended(self):
        """'추천 설정으로 되돌리기'(13.14): 상세 선택을 추천값으로."""
        d, rec = self.panel, self._recommendation()
        d.priority.setChecked(True)
        d.tcp.setChecked(True)
        d.graphics.setChecked(True)
        if rec['layout'] is not None:
            d.split.setCurrentIndex(max(0, d.split.findData(rec['layout'])))
        if rec['adapter'] is not None:
            d.adapter.setCurrentIndex(max(0, d.adapter.findData(rec['adapter'])))
        self._update_recommendation()
        self._sync_optimization_toggle()

    def _render_result(self, d):
        """결과 요약(13.13): 상태 한 줄(굵게·색) + 항목 줄. 세션 기록이 바뀌면 app.log에 한 번 남긴다."""
        from ..optimization.result_summary import COLORS, summarize
        layout = self._requested_layout()
        label = f'{layout.name} ({layout.short})' if layout is not None else self._summary_requested.get('layout_name')
        headline, level, lines = summarize(self.engine, self.recovery, self._summary_requested, layout_label=label,
                                           kept_on=self._kept_on, restore_wait=self._restore_wait)
        if self._notice and not self.engine.busy:
            headline, level, lines = self._notice, 'warn', []
        style = f'font-weight:bold; color:{COLORS[level]};'
        if d.status.text() != headline:
            d.status.setText(headline)
        if d.status.styleSheet() != style:
            d.status.setStyleSheet(style)
        text = '\n'.join(lines)
        if d.results.text() != text:
            d.results.setText(text)
        d.results.setVisible(bool(lines))
        if self.engine.status != self._logged_status:
            # 바뀔 때 새로 생긴 줄만 남긴다(2초마다 다시 만든 같은 기록을 반복하지 않게, 13.13 QA 후속)
            before = set((self._logged_status or '').split('\n'))
            added = [line for line in self.engine.status.split('\n') if line and line not in before]
            self._logged_status = self.engine.status
            if added:
                _log.info('최적화 상태: %s', ' / '.join(added))

    def _requested_layout(self):
        """시작한 세션의 배치. 환경 확인 전에 '추천'으로 시작했으면(자동 적용) 확인 뒤 이 CPU의 추천 배치로 푼다."""
        if not isinstance(self._summary_requested, dict):
            return None
        key = self._summary_requested.get('layout')
        if key == 'recommended':
            return next((layout for layout in self._layouts.values() if layout.recommended), None)
        return self._layouts.get(key)

    def _show_layout_detail(self):
        """콤보 아래 회색 줄: 실제 배분만(13.15에서 근거 문장 삭제 — 내부 문서 번호 노출도 함께 해소)."""
        if self.panel is None: return
        layout = self._layouts.get(self.panel.split.currentData())
        self.panel.split_detail.setText(layout.allocation if layout else '')

    def _maybe_auto_inspect(self):
        if (self._auto_inspected or not hasattr(self.window, '_tabs')
                or self.window._tabs.currentWidget() is not self.panel or not self._can_start()
                or (self.engine.busy and self.engine.task != 'session')):
            return
        # 0.22.0 QA: 자동 적용 세션이 앱 시작부터 엔진을 점유해도(게임 대기 포함) 확인한다 — 세션 중이면 별도 스레드에서 결과만.
        # 읽기 전용(Windows API·PowerShell 조회). 이미 확인 중이라 거절(False)됐을 때만 다음 틱에 다시 시도한다.
        self._auto_inspected = self.engine.inspect() is not False

    def _apply_inspection(self, topology, adapters):
        d, saved = self.panel, config.load_optimization_selection()
        notes = []
        self._restoring_selection = True
        try:
            d.split.clear()
            self._layouts = {}
            if topology is not None:
                d.cpu_info.setText(f'CPU: {topology.name} · 물리 {len(topology.cores)}개 / 논리 {sum(len(c.cpus) for c in topology.cores)}개')
                self._core_total = len(topology.cores)
                from ..optimization.layouts import layouts
                from .optimization_panel import POPUP_ROLE
                for layout in layouts(topology):  # 13.11: 이름 + 실제 배분, 추천 순
                    self._layouts[layout.key] = layout
                    d.split.addItem(layout.label(), layout.key)
                    popup = f"{layout.name}{' · 추천' if layout.recommended else ''}\n{layout.allocation}"
                    d.split.setItemData(d.split.count() - 1, popup, POPUP_ROLE)
                wanted = self._saved_layout(saved, topology)
                index = d.split.findData(wanted) if wanted else -1
                if wanted and index < 0:
                    notes.append('저장한 CPU 배치를 이 CPU에서 쓸 수 없어 추천 배치를 표시해요.')
                d.split.setCurrentIndex(max(index, 0))
            else:
                d.cpu_info.setText('CPU 구조를 확인하지 못했어요. CPU 배치를 적용하지 않아요.')
            d.adapter.clear()
            d.adapter.addItem('적용할 연결을 선택해 주세요.',None)
            # 13.12: 인터넷 기본 경로를 쓰는 연결을 자동 선택. 연결이 1개면 선택 칸 없이 한 줄, 2개 이상이면 미리 고른 콤보.
            from ..system.optimization import default_adapter
            self._auto_adapter = default_adapter(adapters)
            for adapter in adapters:
                guid = str(adapter['InterfaceGuid']).strip('{}')
                suffix = ' (인터넷 연결 중 · 자동 선택)' if guid == self._auto_adapter else ''
                d.adapter.addItem(str(adapter['Name']) + suffix, guid)
            wanted = saved.get('adapter')
            index = -1
            if wanted:
                index = next((i for i in range(1, d.adapter.count())
                              if str(d.adapter.itemData(i)).lower() == wanted.lower()), -1)
                if index < 0:
                    notes.append('저장한 네트워크 연결을 찾지 못했어요.' + (' 인터넷에 연결된 연결을 자동으로 골랐어요.' if self._auto_adapter
                                                                         else ' 패스트핑을 쓰려면 적용할 연결을 다시 골라 주세요.'))
            if index < 0 and self._auto_adapter:
                index = d.adapter.findData(self._auto_adapter)
            if index > 0:
                d.adapter.setCurrentIndex(index)
            single = len(adapters) == 1 and self._auto_adapter is not None
            d.adapter.setVisible(not single)
            d.adapter_label.setVisible(single)
            d.adapter_label.setText(d.adapter.itemText(1) if single else '')
        finally:
            self._restoring_selection = False
        if notes:
            d.cpu_info.setText(d.cpu_info.text() + '\n' + '\n'.join(notes))
        self._show_layout_detail()

    def _wire_panel(self):
        d=self.panel
        for box in (d.priority, d.tcp, d.auto, d.graphics): box.toggled.connect(self._save_selection)
        d.reset_recommended.clicked.connect(self._reset_to_recommended)
        d.advanced_toggle.toggled.connect(self._save_selection)
        d.auto.toggled.connect(self._auto_changed)
        d.split.currentIndexChanged.connect(self._save_selection)
        d.split.currentIndexChanged.connect(lambda _index: self._show_layout_detail())
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
        d.condition.editingFinished.connect(self._condition_changed)  # 입력을 마친 순간(Enter·포커스 이동) 바로 적용
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
        if self._metrics['cpu']: items.append(('게임 CPU', *percent(values.get('cpu'))))  # FPS 명세 10.4 D안
        if self._metrics['gpu']: items.append(('GPU', *percent(values.get('gpu'))))
        if self._metrics['memory']:
            memory = values.get('memory')
            items.append(('게임 메모리', '—', '') if memory is None else ('게임 메모리', f'{memory/1024**3:.1f}', 'GB'))
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

    # ---- 자동 적용(명세 13.10) -------------------------------------------------------------------
    def _auto_changed(self, on):
        """체크를 켜면 바로 게임 대기(앱 시작과 같은 체감), 끄면 지금 게임이 끝날 때 세션도 끝난다(이전 방식)."""
        if self._restoring_selection: return
        self.engine.auto = bool(on)
        if on: self._auto_start()

    def _auto_start(self):
        """자동 적용 세션: 체크한 프로세스 항목만, 네트워크(패스트핑)는 바꾸지 않는다. 게임이 없으면 아무것도 바꾸지 않고 기다린다.
        이미 세션이 돌거나 복구 기록이 손상됐거나 프로세스 항목을 하나도 고르지 않았으면 시작하지 않는다."""
        d = self.panel
        if (d is None or not d.auto.isChecked() or not self._can_start() or self.engine.busy or self.recovery.corrupt
                or not (self._cpu_selected() or d.priority.isChecked())):
            return False
        # 환경 확인 전이면 저장한 배치(없으면 이 CPU의 추천 — 엔진이 구조를 읽어 정한다)
        self._detect_gpu()
        options = dict(cpu=self._cpu_selected(), count=None, layout=self._layout_key() or 'recommended', adapter=None,
                       tcp=False, rss=False, priority=d.priority.isChecked(), auto=True,
                       graphics=self._graphics_on(), game_exe=config.load_game_exe())  # 13.6: 자동 적용에 포함
        self._begin(options)
        return True

    def _begin(self, options):
        self._notice = None
        layout = self._layouts.get(options.get('layout')) if options.get('layout') else None
        if options['cpu'] and options.get('layout'):
            from ..optimization.layouts import NAMES
            name = layout.name if layout else NAMES.get(options['layout'], ('',))[0]
            self._badge_split = f'· {name}' if name else None  # 상단: '최적화: 적용 중 · 게임 집중'(13.11)
        else:
            self._badge_split = (f"{options['count']}+{self._core_total-options['count']}"
                                 if options['cpu'] and options['count'] and self._core_total else None)
        self._kept_on = True  # 이미 목표값이라 바꾼 것이 없어도 켜짐으로 보여준다(13.5)
        self._summary_requested = {key: options[key] for key in ('cpu','count','tcp','priority')}
        self._summary_requested['graphics'] = bool(options.get('graphics'))
        self._summary_requested['adapter_selected'] = bool(options['adapter'])
        self._summary_requested['auto'] = bool(options.get('auto'))  # 13.10: FPS 자동 기록에 자동 적용 여부
        if options.get('layout'):  # 13.11: FPS 자동 기록에 배치 이름과 실제 배분(숫자)
            self._summary_requested['layout'] = options['layout']
            if layout is not None:
                self._summary_requested.update(layout_name=layout.name, layout_allocation=layout.short)
        self._summary_state = None
        if self.stream is not None:
            self.stream.boundary(presentmon.clock()[0], 'optimization_start_request')
        self.engine.start(options)

    def _start_optimization(self):
        if not self._can_start() or self.engine.busy: return
        d = self.panel
        layout = self._layout_key() or 'recommended'  # 환경 확인 전이면 저장값, 없으면 이 CPU의 추천
        options = dict(cpu=self._cpu_selected(),count=None,layout=layout,adapter=d.adapter.currentData(),
                       tcp=d.tcp.isChecked(),rss=False,priority=d.priority.isChecked(),
                       auto=d.auto.isChecked(),  # 13.8: RSS 새 적용 없음 · 13.11: 배치는 이름 키
                       graphics=self._graphics_on(), game_exe=config.load_game_exe())  # 13.6
        if not any(options[k] for k in ('cpu','tcp','priority','graphics')):
            self.engine.status = self._notice = '사용할 항목을 선택해 주세요.'
            return
        if options['tcp'] and not options['adapter']:
            self.engine.status = self._notice = '패스트핑을 적용할 연결을 상세 설정에서 선택해 주세요.'
            return
        if options['tcp'] and not self._network_confirmation(): return
        self._begin(options)

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

    # ---- 홈 '게임 최적화' 스위치(탐색 구조 명세 12.3 C안) ---------------------------------------
    def home_state(self):
        """홈 줄: (상태 문구, 'ok'|'muted'|'warn', 스위치 켬). 켬 = 자동 적용 체크 또는 지금 적용 중."""
        if self.panel is None or not self._access():
            return '꺼짐', 'muted', False
        on = self.panel.auto.isChecked() or self._optimization_on()
        state = optimization_badge(self.recovery, self.engine, None, restore_wait=self._restore_wait, kept_on=self._kept_on)
        text = state[0].removeprefix('최적화: ') if state is not None else None
        if text is None:
            return ('대기 중 · 게임 대기' if on else '꺼짐'), 'muted', on
        if text.startswith('적용 중'):
            return '적용 중', 'ok', on
        if text in ('오류', '원복 대기'):
            return text + ' · 최적화 탭에서 확인', 'warn', on
        return '대기 중 · ' + text, 'muted', on  # 게임 대기 · 보류 · 원복 중

    def set_home_enabled(self, on):
        """C안 '최적화 사용': 켜면 자동 적용 켜기 + 게임이 있으면 바로 적용, 끄면 자동 적용 끄기 + 지금 적용분 원복.
        패스트핑(네트워크)은 여기서 바꾸지 않는다(명세 13.10 — 최적화 탭에서 적용)."""
        d = self.panel
        if d is None or not self._access():
            return
        if on:
            if not d.auto.isChecked():
                d.auto.setChecked(True)  # _auto_changed → 저장·_auto_start(게임 대기 또는 바로 적용)
            else:
                self._auto_start()
            return
        if d.auto.isChecked():
            d.auto.setChecked(False)
        if self._optimization_on():
            self._toggle_optimization()  # 끄기 = 원복(네트워크가 남았으면 기존 확인 창)

    def _network_left(self):
        """되돌릴 네트워크(패스트핑 등) 변경이 남았는지. '원복 대기'는 연결을 끊어야 하는 네트워크만 해당한다."""
        return (any(i['kind'] in NETWORK_KINDS for i in self.recovery.pending)
                or bool(self.recovery.restart_targets))

    def _update_restore_wait(self):
        """'원복 대기'(확인 필요) 여부 갱신. 남은 변경이 있는지 돌려준다. 상단 상태·토글이 같은 값을 쓴다."""
        remaining = bool(self.recovery.pending or self.recovery.restart_targets)
        if not self._network_left():
            self._restore_wait = False
        elif self._restore_requested and not self.engine.busy:
            self._restore_wait = True  # 원복을 요청했는데(거절·실패) 아직 남음 → 확인 필요
        if not self.engine.busy:
            self._restore_requested = False
        return remaining

    def _sync_optimization_toggle(self):
        if self.panel is None: return
        engine = self.engine
        remaining = self._update_restore_wait()
        if not engine.busy and engine.session_end is not None:
            # 게임 종료·Governor·중단·오류로 끝난 세션은 남은 변경이 없으면 꺼진다. 네트워크만 한 세션은 켜짐 유지.
            if engine.session_end != 'network_only':
                self._kept_on = False
            if engine.session_end == 'cancel' and self.panel.auto.isChecked():
                # 0.18.0 QA: 자동 적용 중 토글로 끄면 체크는 켜진 채라도 다음 앱 시작(또는 체크 다시 켬)까지 기다리지 않는다
                engine.status += '\n자동 적용을 멈췄어요 · 앱을 다시 켜거나 체크를 다시 켜면 게임을 기다려요.'

            engine.session_end = None
        on = self._optimization_on()
        toggle = self.panel.toggle
        if toggle.isChecked() != on:
            toggle.blockSignals(True); toggle.setChecked(on); toggle.blockSignals(False)
        waiting = on and not engine.busy and self._restore_wait and remaining
        toggle.setText('최적화 적용 중 · 네트워크 원복 대기' if waiting else '최적화 적용 중' if on
                       else '선택한 설정으로 최적화' if self._is_custom() else '추천 설정으로 최적화')
        allowed = self._can_start()
        toggle.setEnabled(True if on and (engine.busy or self.recovery.pending or self.recovery.restart_targets)
                          else allowed and not engine.busy and not self.recovery.corrupt)

    def _restore_all(self):
        """'중단 · 원복': 세션을 멈추고 적용했던 CPU·네트워크를 모두 되돌린다. 네트워크가 포함되면
        시작할 때처럼 연결 끊김 확인을 한 번 받는다. 거절하면 CPU만 되돌리고 네트워크는 '원복 대기'로
        남긴다(명세 6절: 게임 중 연결을 끊지 않고 CPU만 멈추는 경로).
        접근(로그인)이 없으면 CPU만 원복한다(네트워크 원복은 기존처럼 접근 필요)."""
        self._restore_requested = True  # 끝난 뒤 남으면 '원복 대기'(13.5)
        network = (any(i['kind'] in NETWORK_KINDS for i in self.recovery.pending) or bool(self.recovery.restart_targets))
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
            self.frame_status = self._run_label() + ' · 게임 실행 대기'
            self._tick()
        except Exception as exc: self._failed(str(exc))

    def _run_label(self):
        return '수집 중' if self._collect_only else '표시 중'

    def _ensure_frames(self):
        """측정 파이프라인을 켠다(이미 켜져 있으면 그대로). 이전 세션 정리가 남아 있으면 먼저 정리한다(0.13.5)."""
        if self.frames:
            return True
        if self.collector.pending:
            self.stop_frames()  # 정리 시도. 실패하면 꺼진 채 정리 안내가 상태 줄에 남는다
        if not self.collector.pending:
            self.start_frames()
        return self.frames

    def _toggle_frames(self, on):
        """'FPS 표시' 토글: 켜기 = 측정을 켜고 오버레이 표시, 끄기 = 표시만 끔.
        수집 모드가 켜져 있으면 표시를 꺼도 측정·수집은 계속한다(FPS 명세 9절). 둘 다 꺼지면 측정을 멈춘다."""
        self._restart_at = None  # 사용자가 직접 켜거나 끄면 자동 재시작 예약을 취소
        if on:
            self._collect_only = False
            self._ensure_frames()
        elif self._summary_collecting and self.frames:
            self._collect_only = True  # 표시만 끄고 수집은 계속
            self._hide_overlay()
            self.frame_status = '수집 중 · 표시는 꺼짐'
        else:
            self.stop_frames()
        self._sync_frames_toggle()
        if self._can_start():
            self._restore_display = False
            self._save_overlay(display=bool(on and self.frames))  # 사용자가 바꾼 표시 켜짐만 저장(종료·접근 해제는 저장 안 함)

    def _sync_frames_toggle(self):
        if self.panel is None: return
        toggle = self.panel.frames_toggle
        shown = self.frames and not self._collect_only
        if toggle.isChecked() != shown:
            toggle.blockSignals(True); toggle.setChecked(shown); toggle.blockSignals(False)
        toggle.setText('FPS 표시 중' if shown else 'FPS 표시')

    def stop_frames(self, message='꺼짐 · 표시 안 함'):
        user = message == '꺼짐 · 표시 안 함'
        if self.stream is not None:
            self.stream.boundary(self._summary_now(), 'measurement_stop')
        was_running, self.frames = self.frames, False
        cleaned = self.collector.stop()
        if not cleaned: message += "\n" + self.collector.cleanup_problem
        if not user and was_running:
            # 사용자가 끄지 않았는데 꺼진 경우는 사후 판정을 위해 사유·정리 결과를 남긴다(0.13.5).
            _log.warning('FPS 표시 중단: %s · 수집기 정리 %s', message.replace('\n', ' / '),
                         '완료' if cleaned else '실패')
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
                self.frame_status = self._run_label() + ' · 게임 실행 대기'
                return
        except Exception:
            pass
        self._failed('FPS 수집기가 종료됐어요. 권한·계측 상태를 확인하고 다시 시작해 주세요.')

    RESTART_DELAY = 5.0
    RESTART_LIMIT = 3          # 10분 동안 자동 재시작 최대 횟수
    RESTART_WINDOW = 600.0

    def _failed(self, message):
        running = self.frames  # 시작 실패(게임 미등록 등)는 다시 시도하지 않는다
        if self.stream is not None:
            self.stream.boundary(self._summary_now(), 'collector_error')  # 중단 구간은 비교에서 제외
        now = time.monotonic()
        self._restarts = [t for t in self._restarts if now - t < self.RESTART_WINDOW]
        if running and not self.closing and self._can_start():
            if len(self._restarts) < self.RESTART_LIMIT:
                self._restart_at = now + self.RESTART_DELAY
                message += f'\n잠시 뒤 FPS 표시를 다시 켜요({len(self._restarts) + 1}/{self.RESTART_LIMIT}).'
            else:
                message += '\n자동 재시작 한도(10분에 3회)에 도달해 꺼졌어요. 다시 켜려면 FPS 표시를 눌러 주세요.'
        self.stop_frames(message)

    def set_paused(self, paused):
        self.paused = paused
        if paused: self._hide_overlay()

    def _line(self, line):
        if not self.frames or self.stream is None: return
        try:
            now, _ = presentmon.clock()
            if not self._can_start():
                self.stop_frames('사용 불가 · 측정 중단')
                return
            active = self.context is None or self.context[0]
            accept_events = active and self._sync_summary_context(now)
            # PresentMon sends its header once, often while our app has focus.
            # Preserve protocol metadata even when focus/transition excludes samples.
            self.stream.feed(line, now, accept_events=accept_events)
            if self.summary.full:
                self._summary_limit()
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
                self.frame_status = self._run_label() + ' · 최신 프레임을 기다려요.'
        if game is None:
            self.frame_status = self._run_label() + ' · 게임 실행 대기'
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
            self.frame_status = self._run_label() + ' · 게임 비활성이라 쉬고 있어요.'
            return
        if time.monotonic() - self._delay_logged >= 60:
            self._delay_logged = time.monotonic()
            report = self.stream.delay_report()
            if report: _log.info('FPS 이벤트 도착 지연(최근 약 60초): %s', report)  # PresentMon 출력 묶임 실측(0.13.3)
        if self.stream.header is not None and self.collector.active and time.monotonic()-self.last_health > 1:
            self.last_health = time.monotonic()
            if lost := presentmon.session_losses(self.collector.session):
                raise RuntimeError(f'Windows 프레임 이벤트 손실({lost}건)을 '
                                   '감지해 측정을 중단했어요. 값을 추정하지 않아요.')
        self._sync_summary_context(now)
        result = self.stream.snapshot(now)
        if result['source'] != self._reported_source:
            self._reported_source=result['source']
            _log.info('FPS 대상 확인: pid=%s source=%s candidates=%s',game['pid'],result['source'],len(result['sources']))
        self.frame_status = self._run_label() + ' · ' + result['status']
        # 추가 지표는 작업 스레드에서 1초마다 읽은 최신 값만 쓴다(UI 스레드에서 OS 조회 없음).
        # 표시 중에는 켠 표시 항목, 수집 중에는 구간 기록용 CPU·GPU 사용률과 게임 선호도·우선순위도 함께 읽는다(FPS 명세 9절).
        wanted = set() if self._collect_only else {k for k, on in self._metrics.items() if on and k != 'fps'}
        if self._summary_collecting:
            wanted |= {'cpu', 'gpu', 'process'}
        self.sampler.update(sorted(wanted), game['pid'])
        self.summary.observe(self.sampler.latest)
        items = (self.overlay_items(result['fps'], self.sampler.latest)
                 if result['fps'] is not None and not self._collect_only else [])
        if items and not self.paused:
            self.overlay.set_items(items)
            self.overlay.show()
        else: self._hide_overlay()

    def _tick(self):
        now = time.monotonic()
        gap, self.last_tick = now-self.last_tick, now
        self.refresh_access(recheck=False)
        if self._restart_at is not None and now >= self._restart_at:
            self._restart_at = None
            if not self.frames and self._can_start() and not self.closing:
                self._restarts.append(now)
                _log.info('FPS 표시 자동 재시작 %d/%d', len(self._restarts), self.RESTART_LIMIT)
                if self.collector.pending:
                    self.stop_frames()
                if not self.collector.pending:
                    self.start_frames()
        if self._auto_pending and self._can_start() and self.panel is not None:
            self._auto_pending = False
            if self._auto_start():
                _log.info('최적화 자동 적용: 앱 시작 · 게임을 기다려요')
        if self._restore_display and self._can_start() and now >= self._restore_retry_at:
            # 이전 FPS 세션 정리가 남아 있으면 먼저 정리하고 바로 켠다(0.14.1: 업데이트 뒤 표시 미복원).
            # 정리에 실패하면 5초 뒤 다시(최대 3회), 그래도 안 되면 기존 정리 안내만 남긴다.
            if self.collector.pending and not self.frames:
                self.stop_frames()
            if not self.collector.pending:
                self._restore_display = False
                self._collect_only = False
                self._ensure_frames()
            else:
                self._restore_tries += 1
                self._restore_retry_at = now + 5
                if self._restore_tries >= 3:
                    self._restore_display = False
        if self.frames:
            try: self._frame_tick(gap)
            except Exception as exc: self._failed(str(exc))
            if self.frames and self.summary.full:
                self._summary_limit()
        if self.engine.recovery_requested and not self.engine.busy:
            self.engine.recovery_requested = False
        self._offer_normalized_restore()
        self._update_restore_wait()
        self._update_badge()
        if self.panel is None: return
        self._poll_summary_store()
        self._render_summary()
        d = self.panel
        allowed, busy = self._can_start(), self.engine.busy
        for w in (d.priority,d.tcp,d.split,d.adapter): w.setEnabled(allowed and not busy)
        d.graphics.setEnabled(allowed and not busy and bool(self._gpu))  # 13.6: NVIDIA가 아니면 비활성
        d.inspect.setEnabled(allowed and not self.engine.inspecting)  # 0.22.0 QA: 세션(자동 적용 대기 포함) 중에도 다시 확인 가능
        self._sync_optimization_toggle()
        for control in (d.lock,d.scale,*d.metric_boxes.values()): control.setEnabled(allowed)
        d.frames_toggle.setEnabled((allowed and not self.closing) or self.frames or self.collector.pending)
        self._sync_frames_toggle()
        for control in (d.summary_collect,d.summary_save,d.summary_folder): control.setEnabled(allowed and self._creator())
        d.frames_status.setText(self.frame_status)
        self._render_result(d)
        self._update_recommendation()
        self._maybe_auto_inspect()  # 탭에 머문 채 세션이 끝나거나 접근이 생겨도 한 번은 확인
        from collections import Counter
        counts=Counter((item['kind'],item['state']) for item in self.recovery.items)
        kinds={'cpu':'CPU 배치','priority':'게임 우선순위','ack':'TcpAckFrequency','nodelay':'TCPNoDelay','autotuning':'TCP 자동 조정','rss':'RSS',
               'frl':'그래픽 효율(최대 프레임)'}
        states={'prepared':'적용 확인 필요','applied':'적용됨','failed':'미적용·확인 필요','restored':'원복됨',
                'released':'외부 변경·관리 제외'}
        lines=[f'{kinds.get(kind,kind)} · {states.get(state,state)} {count}개' for (kind,state),count in counts.items()]  # 모르는 종류도 멈추지 않게
        if self.recovery.restart_targets: lines.append(f'네트워크 재연결 대기: {len(self.recovery.restart_targets)}개 어댑터')
        # 13.13: 세션 기록·변경 수는 접힌 '자세히 보기'에만(요약에 쓰지 않음)
        details = self.engine.status + ('\n\n' + '\n'.join(lines) if lines else '')
        if self.recovery.corrupt:
            details += '\n기록: ' + str(self.recovery.path)
        d.details.setText(details)
        if self.engine.inspection is not None:
            topology, adapters = self.engine.inspection
            self.engine.inspection = None
            self._apply_inspection(topology, adapters)
            self._gpu, self._gpu_checked = getattr(self.engine, 'inspection_gpu', None), True
            self._show_gpu()
            self._update_recommendation()
            failed = getattr(self.engine, 'inspection_failed', [])
            names = '·'.join(failed)
            self._inspect_notice = (f"{names}{object_particle(names)} 읽지 못했어요 · 자세히 보기에서 이유를 확인하고 '다시 확인'을 눌러 주세요"
                                    if failed else None)
            self._notice = self._inspect_notice
            layout = self._requested_layout()
            if busy and isinstance(self._summary_requested, dict) and self._summary_requested.get('cpu') and layout is not None and self._badge_split is None:
                self._badge_split = f'· {layout.name}'  # 추천으로 시작한 자동 세션: 상단에도 배치 이름
            self._render_result(d)  # 같은 틱에 바로 보이게

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
            auto = bool(self.panel is not None and self.panel.auto.isChecked())
            state = (self.recovery.measurement_revision, self.engine.busy, self.engine.cancel.is_set(),
                     tuple(sorted((self.target or {}).items())), repr(self._summary_requested), self.recovery.corrupt, auto)
            if state == self._summary_state:
                return True
            counts = Counter((i['kind'],i['state']) for i in self.recovery.items)
            values = [dict(kind=i['kind'], state=i['state'], value=i['applied']) for i in self.recovery.items
                      if i['kind'] not in PROCESS_KINDS or i['target'] == self.target][:128]
            from ..version import __version__
            context = dict(target=self.target, requested=self._summary_requested,
                app_version=__version__, collector_sha256=presentmon.SHA256, qpc_frequency=self.stream.frequency,
                observation='journal_unconfirmed' if self.recovery.corrupt else 'last_journal_confirmation_not_live_os_read',
                optimization_worker_active=self.engine.busy, values=values,
                states=[dict(kind=k,state=st,count=n) for (k,st),n in sorted(counts.items())],
                reconnect_pending=len(self.recovery.restart_targets),
                optimization_auto_apply=auto)  # 13.10: 자동 적용 켬/끔(실험 자료가 섞였는지 확인용)
            self._summary_state = state
        finally:
            self.recovery.lock.release()
        if context != self.summary.context:
            self.stream.boundary(now, 'optimization_state_observed')
            self.summary.set_context(now, context)
        return True

    def _toggle_summary_collection(self, enabled):
        if enabled and not (self._can_start() and self._creator()):
            self.panel.summary_collect.setChecked(False)
            return
        if self.stream is not None:
            self.stream.boundary(self._summary_now(), 'collection_toggle')
        self._summary_collecting = enabled
        # 수집 모드를 켜면 FPS 표시와 관계없이 측정을 켜서 게임이 앞에 있는 동안 자동 수집한다(FPS 명세 9절).
        # 표시는 켜지 않는다. 수집을 끄면 표시도 꺼져 있을 때만 측정을 멈춘다.
        if enabled and not self.frames:
            self._collect_only = True  # 표시는 켜지 않는다
        if enabled and not self._ensure_frames():
            self._collect_only = False
            self._summary_collecting = False
            self._summary_message = '수집을 시작하지 못했어요: ' + self.frame_status
            self.panel.summary_collect.blockSignals(True)
            self.panel.summary_collect.setChecked(False)
            self.panel.summary_collect.blockSignals(False)
        elif not enabled and self.frames and self._collect_only:
            self.stop_frames()
            self._collect_only = False
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

    def _new_summary(self, reason):
        """진행 중 구간을 마감하고 같은 조건 이름의 새 측정으로 이어 간다. 끝난 측정은 비교 기준으로만 남긴다."""
        closer = self.stream if self.stream is not None else self.summary
        closer.boundary(self._summary_now(), reason)
        condition = self.summary.condition
        if self.summary.measurement() is not None:
            self._previous_measurement = self.summary.measurement()
        self.summary = FrameSummary()
        self.summary.closed_callback = self._summary_closed
        if self.stream is not None:
            self.stream.summary = self.summary
        self._summary_state = None  # 새 측정에도 최적화 상태 기록을 다시 남긴다
        self.summary.set_condition(condition)

    def _summary_limit(self):
        """구간 요약 한도(구간 128개·전환 512개, 약 2시간)에 닿았을 때(0.17.2: 사용자 app.log 'FPS 표시 중단: 구간/전환 요약 한도').

        한도는 요약(수집) 자료의 상한이지 표시의 상한이 아니다. 수집을 안 하면 조용히 새 요약으로 이어 가고 표시는 계속한다.
        수집 중이면 기존 자료 보존 원칙대로 수집만 멈추고 안내한다(완료 구간은 이미 저장됨). 표시가 꺼진 수집 전용이면 측정도 끝낸다."""
        collecting = self._summary_collecting
        self._new_summary('summary_capacity')
        if not collecting:
            _log.info('FPS 구간 요약 한도 · 수집 꺼짐이라 새 요약으로 이어서 표시해요')
            return
        self._summary_collecting = False
        if self.panel is not None:
            self.panel.summary_collect.blockSignals(True)
            self.panel.summary_collect.setChecked(False)
            self.panel.summary_collect.blockSignals(False)
        message = ('수집 한도(구간 128개, 약 2시간)에 닿아 수집을 멈췄어요. 지금까지 구간은 저장돼 있어요. '
                   "이어서 모으려면 '수집'을 다시 켜 주세요.")
        self._summary_message = message
        _log.info('FPS 구간 요약 한도 · 수집을 멈추고 표시는 계속해요')
        if self._collect_only:
            self._collect_only = False
            self.stop_frames('수집 한도에 닿아 수집을 멈췄어요(표시는 꺼져 있어 측정도 끝냈어요).')
        self._render_summary(force=True)

    def _condition_changed(self, text=None):
        """측정 조건 이름은 입력을 마치면 바로 적용한다(FPS 명세 9절). 기록 중이면 지금 구간을 끊고 새 측정으로 이어서,
        한 구간·한 측정 안에 두 이름이 섞이지 않게 한다(7절 원칙). 끝난 측정의 이름은 바꾸지 않는다."""
        if text is None:
            text = self.panel.condition.text() if self.panel is not None else ''
        name = ' '.join(str(text or '').split())[:48]
        if name == self.summary.condition:
            return
        if self.summary.records or self.summary.samples:
            self._new_summary('condition_change')  # 진행 중 구간을 옛 이름으로 마감
            self.summary.set_condition(name)
            self._summary_message = f'측정 조건을 「{name or "조건 이름 없음"}」(으)로 바꿨어요 · 지금부터 새 이름으로 기록해요.'
            self._render_summary(force=True)
        else:
            self.summary.set_condition(name)

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
                cpu, game_cpu, gpu = g.get('cpu_busiest_percent'), g.get('game_cpu_percent'), g.get('gpu_percent')
                if cpu or game_cpu or gpu:
                    usage = []
                    if game_cpu:
                        usage.append(f"게임 CPU {game_cpu['median']:.0f}% [{game_cpu['minimum']:.0f}~{game_cpu['maximum']:.0f}]")
                    if cpu:  # 0.16.0 자료(이전 정의): 섞어 비교하지 않게 이름을 구분
                        usage.append(f"가장 바쁜 코어(이전 정의) {cpu['median']:.0f}% [{cpu['minimum']:.0f}~{cpu['maximum']:.0f}]")
                    if gpu: usage.append(f"GPU {gpu['median']:.0f}% [{gpu['minimum']:.0f}~{gpu['maximum']:.0f}]")
                    line += '\n    ' + ' · '.join(usage)
                states = g.get('process_states') or []
                if states:
                    text = ' / '.join(f"{st['affinity']} · 우선순위 {st['priority']}" for st in states)
                    line += ('\n    ⚠ 조건 안에서 선호도·우선순위가 바뀜: ' if g.get('process_mixed') else '\n    게임 선호도·우선순위: ') + text
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
            observed = []  # FPS 명세 9절: 수집 중 함께 기록한 값(읽기 전용)
            if record.get('game_cpu_thread_avg_percent') is not None:
                observed.append(f"게임 CPU 평균 {record['game_cpu_thread_avg_percent']:.0f}%")
            if record.get('gpu_avg_percent') is not None:
                observed.append(f"GPU 평균 {record['gpu_avg_percent']:.0f}%")
            for state in record.get('process_states') or ():
                observed.append(f"게임 선호도 {state['affinity']} · 우선순위 {state['priority']}")
            if observed:
                text += '\n' + ' · '.join(observed)
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
            # 수집기 오류로 멈춘 경우(자동 재시작 대기 등). 표시 여부와는 무관하다(FPS 명세 9절).
            return '수집 모드 켜짐 · 측정이 멈춰 있어요. 상태 줄을 확인해 주세요.'
        if self._summary_collecting and self._collect_only:
            return '수집 중(FPS 표시 꺼짐) · ' + self._summary_message
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
