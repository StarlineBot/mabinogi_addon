"""실제 FPS 패널의 수집 모드 샘플. 장치·계측·사용자 설정 접근 없음."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from test_support.qt_runtime import configure_offscreen_fonts
from test_support.boundaries import ExternalBoundaries
from mabinogi_addon.ui.optimization_panel import OptimizationPanel
from mabinogi_addon.ui.optimization_controller import OptimizationController
from mabinogi_addon.ui.theme import apply_theme
from mabinogi_addon.optimization.frame_summary import FrameSummary


def render(destination):
    configure_offscreen_fonts()
    app=QApplication.instance() or QApplication([])
    apply_theme('light')
    destination.mkdir(parents=True,exist_ok=True)
    with ExternalBoundaries() as boundary:
        panel=OptimizationPanel();panel.resize(1000,1100);panel.tabs.setCurrentIndex(1)
        book=FrameSummary();book.set_context(100,dict(requested=dict(count=8),values=[]));book.activate('0x1',100)
        stamp=100.
        for duration in [.01,.01,.01,.03]*500:
            stamp+=duration;book.interval('0x1',stamp,duration)
        book.boundary(stamp,'optimization_start_request')
        book.set_context(stamp,dict(requested=dict(count=7),values=[dict(kind='cpu',state='applied',value=16383)]))
        book.activate('0x1',stamp)
        for _ in range(1200):
            stamp+=.025;book.interval('0x1',stamp,.025)
        host=SimpleNamespace(panel=panel,summary=book,_summary_render_at=0,_summary_saved=1,
            _summary_message='수집 모드 예시 · 요약 1개',summary_store=SimpleNamespace(folder=Path('예시/프레임_요약')),
            _summary_now=lambda:stamp)
        panel.frames_status.setText('배치 확인용 합성 데이터 · 실제 Windows 측정 결과가 아니에요.')
        panel.summary_collect.setChecked(True)
        panel.source.clear();panel.source.addItem('등록 게임 렌더링 대상 (예시)')
        OptimizationController._render_summary(host,force=True)
        panel.show();app.processEvents()
        assert panel.grab().save(str(destination/'fps-summary-tradeoff.png'))
        book=FrameSummary();book.activate('0x1',100)
        for n in range(20):book.interval('0x1',100+(n+1)*.02,.02)
        host.summary=book;host._summary_now=lambda:100.4
        host._summary_message='저장 전 · 표본 수집 중 예시'
        panel.summary_collect.setChecked(False)
        OptimizationController._render_summary(host,force=True)
        app.processEvents()
        assert panel.grab().save(str(destination/'fps-summary-insufficient.png'))
        panel.close();panel.deleteLater();app.processEvents()
        assert not boundary.violations,boundary.violations
    return destination


if __name__=='__main__':
    import sys
    print(render(Path(sys.argv[1])))
