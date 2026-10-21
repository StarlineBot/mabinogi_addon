"""Offline render of the actual embedded pages; all values and settings are samples."""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import os
import tempfile
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QRect,QTimer
from PySide6.QtWidgets import QApplication,QMessageBox
from mabinogi_addon import config,paths
from mabinogi_addon.ui import optimization_controller as module
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui.theme import apply_theme
from test_support.boundaries import ExternalBoundaries


def main():
    out=Path('docs/qa/assets/optimization_tabs_20261021');out.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([]);app.setStyle('Fusion');apply_theme('dark')
    raw={'general':{'skipSetup':True,'theme':'dark'},'buffTracker':{'enabled':False},'debuffTracker':{'enabled':False}}
    creator=[True]
    with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
        data=Path(folder)/'data';data.mkdir()
        boundary=stack.enter_context(ExternalBoundaries())
        stack.enter_context(patch.object(paths,'user_data_dir',lambda:data))
        stack.enter_context(patch.object(config,'_read_local_config',lambda *a,**k:deepcopy(raw)))
        stack.enter_context(patch.object(config,'_write_local_config',lambda *a,**k:None))
        stack.enter_context(patch.object(config,'load_discord_user',lambda *a,**k:{'id':'preview','name':'미리보기'}))
        stack.enter_context(patch.object(config,'get_nexon_api_key',lambda:None))
        stack.enter_context(patch.object(module,'is_creator',lambda:creator[0]))
        stack.enter_context(patch.object(QApplication,'quit',lambda:None))
        stack.enter_context(patch.object(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No))
        screen=type(app.primaryScreen())
        for name in ('availableGeometry','geometry'): stack.enter_context(patch.object(screen,name,lambda self:QRect(0,0,1600,1200)))
        w=MainWindow();w._post_show_done=True;w._booting=False;w._leave_setup();w.resize(1000,960);w.show()
        for timer in w.findChildren(QTimer): timer.stop()
        c=w.optimization_tools;d=c.panel;c.open()
        d.cpu_info.setText('AMD Ryzen 7 9800X3D · 물리 코어 8개 / 논리 프로세서 16개 (미리보기)')
        d.split.clear();d.split.addItem('게임 7개 + 백그라운드 물리 코어 1개',7)
        d.adapter.clear();d.adapter.addItem('이더넷 (미리보기)','12345678-1234-1234-1234-123456789abc')
        def save(name):
            for _ in range(6): app.processEvents()
            assert w.grab().save(str(out/name))
        try:
            save('optimization.png')
            d.tabs.setCurrentIndex(1);save('fps.png')
            w.resize(720,800);save('fps_narrow.png')
            d.tabs.setCurrentIndex(0);save('optimization_narrow.png')
            w.resize(1000,960)
            w._tabs.setCurrentWidget(w._tracker_tabs);w._tracker_tabs.setCurrentIndex(0);save('combat_comparison.png')
            creator[0]=False;c.refresh_access();save('noncreator.png')
            assert not boundary.violations,boundary.violations
        finally:
            w._force_quit=True;w.close();app.processEvents()
    print(out)


if __name__=='__main__': main()
