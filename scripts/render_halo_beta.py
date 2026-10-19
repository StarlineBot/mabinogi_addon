"""Render actual halo/setup widgets offline; no capture, audio or user settings."""

from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from mabinogi_addon import config
from mabinogi_addon.ui.main_window import MainWindow
from test_support.boundaries import ExternalBoundaries


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    out = Path('/tmp/halo-beta-preview')
    out.mkdir(exist_ok=True)
    raw = {'general':{'skipSetup':True,'gameExe':'Client.exe','setupSelection':{'halo_timer':True}},
           'buffTracker':{'enabled':False},'debuffTracker':{'enabled':False},
           'haloTimer':{'box':dict(x=1229,y=134,w=119,h=42)}}
    with ExitStack() as stack:
        boundary = stack.enter_context(ExternalBoundaries())
        stack.enter_context(patch.object(config,'_read_local_config',lambda *a,**k:deepcopy(raw)))
        stack.enter_context(patch.object(config,'_write_local_config',lambda *a,**k:None))
        stack.enter_context(patch.object(config,'load_discord_user',lambda:{'id':'280290004926857216','name':'미리보기'}))
        stack.enter_context(patch.object(QApplication,'quit',lambda:None))
        stack.enter_context(patch('os._exit',lambda *a:None))
        window = MainWindow()
        window._post_show_done = True
        try:
            window._leave_setup()
            window._open_setup_feature('halo_timer')
            s = window.boss_tab.halo_capture
            s._root = Path('C:/Users/Preview/진단 자료/halo_timer_shots')
            s._refresh()
            window.show()
            for timer in window.findChildren(QTimer):
                timer.stop()
            with ZipFile('tests/data/0058.zip') as archive:
                image = QPixmap()
                assert image.loadFromData(archive.read('0001/frame.png'),'PNG')
            s.preview.setFixedSize(image.width()+2,image.height()+2)
            s.preview.setPixmap(image)
            s.reading.setText('판독 시간: 14:41')
            s.state.setText('감시 중 · 다음 헤일로까지 00:51')
            for pixels in (12,20):
                for widget in window.findChildren(QWidget):
                    font = QFont(widget.font())
                    font.setPixelSize(pixels)
                    widget.setFont(font)
                for expanded in (False,True):
                    s.disclosure.setChecked(expanded)
                    for _ in range(8): app.processEvents()
                    inner = window.boss_tab.pattern_tabs.widget(1)
                    assert inner.horizontalScrollBar().maximum()==0
                    assert window._combat_pages['boss'].horizontalScrollBar().maximum()==0
                    assert window.grab().save(str(out/f'halo-{pixels}-{expanded}.png'))
            window._open_guide()
            window.setup_guide.stage=1
            window.setup_guide.refresh()
            for _ in range(8): app.processEvents()
            assert window.grab().save(str(out/'guide.png'))
            stack.enter_context(patch.object(type(app.primaryScreen()),'availableGeometry',
                                              lambda self:QRect(0,0,800,652)))
            window.creator_dialogue.refresh()
            for _ in range(8): app.processEvents()
            assert window.setup_guide.next_btn.mapTo(window,window.setup_guide.next_btn.rect().bottomRight()).y()<window.height()
            assert window.grab().save(str(out/'guide-small.png'))
            window._open_setup_feature('halo_timer')
            window.boss_tab.pattern_tabs.widget(1).ensureWidgetVisible(s.folder)
            for _ in range(8): app.processEvents()
            assert window.height()==620
            assert window.boss_tab.pattern_tabs.widget(1).horizontalScrollBar().maximum()==0
            assert window.grab().save(str(out/'halo-small.png'))
            assert not boundary.violations,boundary.violations
            print(out)
        finally:
            window._force_quit = True
            window.close()
            app.processEvents()


if __name__=='__main__':
    main()
