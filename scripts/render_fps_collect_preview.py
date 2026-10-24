"""FPS 명세 9절 렌더: 수집 모드(FPS 표시 꺼짐) 상태·구간 기록값·조건별 정리(선호도·우선순위 섞임 표시). 합성 자료, 장치 접근 없음.

QT_QPA_PLATFORM=offscreen uv run python -m scripts.render_fps_collect_preview /tmp/fps-collect
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from test_support.qt_runtime import configure_offscreen_fonts
from test_support.boundaries import ExternalBoundaries
from mabinogi_addon.optimization.frame_summary import FrameSummary
from mabinogi_addon.ui.optimization_controller import OptimizationController
from mabinogi_addon.ui.optimization_panel import OptimizationPanel
from mabinogi_addon.ui.theme import apply_theme

SMT = dict(affinity='코어당 1개(SMT 끔으로 보임 · 논리 CPU 8개)', priority='높음')
FULL = dict(affinity='전체(논리 CPU 16개)', priority='보통')


def book(condition, slow_every, cpu, gpu, states, seconds=130):
    summary = FrameSummary(); summary.set_condition(condition); summary.activate('0x1', 0)
    t, n = 0.0, 0
    while t < seconds:
        value = .03 if n % slow_every == 0 else .012
        t += value; summary.interval('0x1', t, value)
        if n % 80 == 0:
            summary.observe(dict(cpu=cpu, gpu=gpu, process=states[min(len(summary.records), len(states) - 1)]))
        n += 1
    return summary


def render(destination):
    configure_offscreen_fonts()
    app = QApplication.instance() or QApplication([])
    apply_theme('light')
    destination.mkdir(parents=True, exist_ok=True)
    with ExternalBoundaries() as boundary, tempfile.TemporaryDirectory() as folder:
        panel = OptimizationPanel(); panel.resize(1000, 1250); panel.tabs.setCurrentIndex(1)
        current = book('smt끔+높음 · 렉 던전', 40, 97.0, 55.0, [SMT])
        for n, (name, every, cpu, gpu, states) in enumerate((('기본 · 렉 던전', 25, 92.0, 58.0, [FULL]),
                                                             ('smt끔+높음 · 렉 던전', 40, 97.0, 55.0, [FULL, SMT]))):
            (Path(folder) / f'frames-{n}.json').write_text(json.dumps(book(name, every, cpu, gpu, states).report()), encoding='utf-8')
        host = SimpleNamespace(panel=panel, summary=current, _summary_render_at=0, _summary_saved=3,
                               _summary_message='요약 저장 완료 · 3개', summary_store=SimpleNamespace(folder=Path(folder)),
                               _summary_now=lambda: 130.0, frames=True, _collect_only=True, _summary_collecting=True,
                               _condition_text=None, _previous_measurement=None, _can_start=lambda: True)
        host._collect_message = lambda: OptimizationController._collect_message(host)
        host._measurement_text = lambda: OptimizationController._measurement_text(host)
        host._render_summary = lambda force=False: OptimizationController._render_summary(host, force)
        panel.frames_status.setText('수집 중 · 60FPS 이상 안정(합성 예시 · 실제 Windows 측정 아님)')
        panel.summary_collect.setChecked(True)
        panel.condition.setText('smt끔+높음 · 렉 던전')
        OptimizationController._show_conditions(host)
        panel.show(); app.processEvents()
        assert panel.grab().save(str(destination / 'fps-collect-conditions.png'))
        panel.close(); panel.deleteLater(); app.processEvents()
        assert not boundary.violations, boundary.violations
    return destination


if __name__ == '__main__':
    print(render(Path(sys.argv[1])))
