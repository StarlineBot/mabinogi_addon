"""설정 안내 그림(2026-10-25 사용자 결정): 다섯 곳 표시·탭별 그림·도움말 연동·첫 사용 안내."""
import numpy as np
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage

from PySide6.QtWidgets import QApplication

from mabinogi_addon import guide_images, image_io
from mabinogi_addon.guide_images import AREAS, IMAGES, SOURCE_SIZE


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def _source():
    from pathlib import Path
    return image_io.imread(Path(__file__).parent / 'data' / '스크린샷 2026-10-25 233749.png')


def test_areas_are_the_five_user_chosen_regions_inside_the_screenshot():
    assert [AREAS[k][1] for k in IMAGES['all']] == ['버프 목록', '전투 제한 시간', '디버프', '보스 체력바', '하단 체력바']
    assert sorted(a[0] for a in AREAS.values()) == [1, 2, 3, 4, 5]
    for _n, _label, (x, y, w, h) in AREAS.values():
        assert 0 <= x and 0 <= y and x + w <= SOURCE_SIZE[0] and y + h <= SOURCE_SIZE[1]
    assert IMAGES['boss'] == ('boss', 'halo_timer')  # 보스 패턴 알림 = 보스 체력바 + 전투 제한 시간


def test_render_dims_outside_and_keeps_full_screen():
    source = _source()
    assert source.shape[1::-1] == SOURCE_SIZE
    image = guide_images.render(source, 'buff')
    assert image.shape[1] == guide_images.OUTPUT_WIDTH and image.shape[0] == 675  # 영역만 자르지 않음
    small = guide_images.render(source, 'buff', numbered=False)
    scale = guide_images.OUTPUT_WIDTH / SOURCE_SIZE[0]
    import cv2
    plain = cv2.resize(source, (1200, 675), interpolation=cv2.INTER_AREA)
    x, y, w, h = (round(v * scale) for v in AREAS['buff'][2])
    inside = small[y + 10:y + h - 10, x + 10:x + w - 10]
    assert np.array_equal(inside, plain[y + 10:y + h - 10, x + 10:x + w - 10])  # 영역 안은 원본 밝기
    assert small[20:60, 600:700].mean() < plain[20:60, 600:700].mean() * 0.5  # 영역 밖은 어둡게
    with pytest.raises(ValueError):
        guide_images.render(source[:100], 'buff')


def test_caption_numbers_only_the_full_image():
    assert guide_images.caption('all').startswith('① 버프 목록 · ② 전투 제한 시간')
    assert guide_images.caption('boss') == '보스 체력바 · 전투 제한 시간'


@pytest.mark.parametrize('name', list(IMAGES))
def test_bundled_images_exist_and_load(name):
    from mabinogi_addon.ui.guide_figure import guide_path
    image = QImage(str(guide_path(name)))
    assert not image.isNull() and image.width() == 1200


@pytest.mark.parametrize('title, name', [('버프 트래커', 'buff'), ('디버프 트래커', 'debuff'),
                                         ('보스 패턴 알림', 'boss'), ('체력바', 'stat_bars')])
def test_each_tab_help_starts_with_its_own_figure(qapp, title, name, monkeypatch):
    from mabinogi_addon.ui import guide_figure
    from mabinogi_addon.ui.feature_copy import HELP
    from mabinogi_addon.ui.help_dialog import HelpDialog
    html = HELP[title]
    assert html.startswith(f'<p><a href="zoom:{name}"><img src="guide/{name}.jpg" width="420">')
    assert sum(f'guide/{n}.jpg' in html for n in IMAGES) == 1  # 그 탭 그림만
    opened = []
    monkeypatch.setattr(guide_figure.ZoomDialog, 'exec', lambda self: opened.append(self) or 0)
    dialog = HelpDialog(title, html)
    assert dialog.browser.document().resource(3, QUrl(f'guide/{name}.jpg')) is not None
    dialog._link(QUrl(f'zoom:{name}'))
    screen = opened[0].screen().availableGeometry().width()
    assert opened[0].image.pixmap().width() == min(1200, int(screen * 0.9))  # 약 1200px, 화면보다 크면 줄임


def test_setup_guide_shows_full_figure_in_feature_stages(qapp, monkeypatch):
    from mabinogi_addon.ui import guide_figure
    from mabinogi_addon.ui.setup_guide import SetupGuide, GUIDE_FIGURE_TEXT
    page = SetupGuide()
    page.show()
    for stage, visible in ((0, False), (1, True), (2, True)):
        page.stage = stage
        page.refresh()
        assert page.figure.isVisible() is visible and page.figure_caption.isVisible() is visible
    assert page.figure.name == 'all' and page.figure.pixmap().width() == 420
    assert '연습 모드' in GUIDE_FIGURE_TEXT and '보스 체력바' in GUIDE_FIGURE_TEXT
    assert guide_images.caption('all') in page.figure_caption.text()
    opened = []
    monkeypatch.setattr(guide_figure.ZoomDialog, 'exec', lambda self: opened.append(self) or 0)
    page.figure.clicked.emit()
    assert opened
