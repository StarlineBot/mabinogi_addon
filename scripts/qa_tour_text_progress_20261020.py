"""Live tour text/progress reproduction; no product or existing test edits.

PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest
scripts/qa_tour_text_progress_20261020.py -q --tb=short --show-capture=no
"""

from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_navigation import window  # noqa: E402,F401


def settled(app):
    loop = QEventLoop()
    QTimer.singleShot(60, loop.quit)
    loop.exec()
    for _ in range(8):
        app.processEvents()


@pytest.mark.parametrize('family', [None, 'Noto Sans CJK KR'])
def test_all_tour_bodies_fit_their_actual_label_height(window, family):
    w, app = window
    w._run_tour(from_guide=True)
    tour = w._tour
    if family:
        for label in (tour._title, tour._body, tour._step_lbl):
            font = QFont(label.font())
            font.setFamily(family)
            label.setFont(font)
    failures = []
    for index in list(range(7)) + list(reversed(range(7))):
        tour._i = index
        tour._show_step()
        settled(app)
        label = tour._body
        needed = label.heightForWidth(label.contentsRect().width())
        actual = label.contentsRect().height()
        if needed > actual:
            failures.append(dict(step=index+1, title=tour._title.text(), needed=needed,
                                 actual=actual, card=tour._card.size().toTuple(),
                                 layout_height=tour._card.layout().heightForWidth(tour._card.width())))
            tour._card.grab().save(f'/tmp/qa-tour-text-{family or "default"}-{index+1}.png')
    assert failures == [], failures


def test_guide_tour_progress_text_fits_with_all_buttons(window):
    w, app = window
    w._run_tour(from_guide=True)
    tour = w._tour
    failures = []
    for index in range(7):
        tour._i = index
        tour._show_step()
        settled(app)
        label = tour._step_lbl
        required = label.fontMetrics().horizontalAdvance(label.text())
        actual = label.contentsRect().width()
        if required > actual:
            failures.append((index+1, label.text(), required, actual))
    assert failures == [], failures


def test_requested_local_tour_counter_has_no_outer_setup_number(window):
    w, app = window
    w._run_tour(from_guide=True)
    tour = w._tour
    settled(app)
    assert tour._step_lbl.text().replace(' ', '') == '1/7'
