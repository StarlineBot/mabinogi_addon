"""Render proposed beta controls and actual resource drawing without IO/devices."""

from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel,
                              QPushButton, QSpinBox, QVBoxLayout, QWidget)

from mabinogi_addon.ui.dorcha_overlay import DorchaOverlay
from mabinogi_addon.ui.stat_overlay import StatBarOverlay
from mabinogi_addon.ui.dorcha_tab import DorchaTab
from mabinogi_addon import config


def main():
    out = Path('/tmp/dorcha-preview')
    out.mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet('QWidget{background:#24262a;color:#edf0f4;font-size:14px;}'
                     'QPushButton,QSpinBox{padding:7px;border:1px solid #676d76;border-radius:4px;}'
                     'QLabel#title{font-size:20px;font-weight:600;}'
                     'QLabel#beta{color:#e7b765;}')
    window = QWidget()
    window.setFixedSize(780,540)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(24,20,24,24)
    layout.setSpacing(18)
    title = QLabel('편의기능  /  도르카 (베타)')
    title.setObjectName('title')
    layout.addWidget(title)
    beta = QLabel('베타 · Discord 로그인 사용자')
    beta.setObjectName('beta')
    layout.addWidget(beta)
    region = QHBoxLayout()
    for text in ('자동 찾기','직접 지정','영역 보기'):
        region.addWidget(QPushButton(text))
    region.addStretch()
    layout.addLayout(region)
    layout.addWidget(QLabel('등록 영역  941, 948  /  28 × 23'))
    row = QHBoxLayout()
    row.addWidget(QCheckBox('도르카 오버레이 사용'))
    row.addStretch()
    row.addWidget(QLabel('전체 배율'))
    scale = QSpinBox()
    scale.setRange(50,300)
    scale.setValue(150)
    scale.setSuffix(' %')
    row.addWidget(scale)
    lock = QCheckBox('위치 고정')
    lock.setChecked(True)
    row.addWidget(lock)
    layout.addLayout(row)
    layout.addWidget(QLabel('표시 미리보기'))
    preview = QLabel()
    preview.setMinimumHeight(100)
    dorcha = DorchaOverlay()
    dorcha.set_value(13)
    dorcha.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
    pm = dorcha.grab()
    preview.setPixmap(pm)
    layout.addWidget(preview)
    layout.addWidget(QLabel('현재 판독  13 / 15'))
    layout.addStretch()
    window.show()
    app.processEvents()
    assert window.grab().save(str(out/'settings.png'))
    # Render the integrated controls too, with a sample value and no live capture.
    class Watcher:
        def is_game_active(self): return False
        def is_self_active(self): return False
    with patch.object(config,'_read_local_config',return_value={
            'dorcha':{'box':dict(x=941,y=948,w=28,h=23)}}), \
            patch.object(config,'load_discord_user',return_value={'id':'render-only'}):
        actual = DorchaTab(Watcher())
        actual._timer.stop()
        actual._set_value(13)
        actual.resize(780,540)
        actual.show()
        app.processEvents()
        assert actual.grab().save(str(out/'integrated-settings.png'))
        actual.shutdown()
        actual.close()
        actual.deleteLater()
    sheet = QImage(780,420,QImage.Format.Format_RGB32)
    sheet.fill(QColor('#202429'))
    painter = QPainter(sheet)
    painter.setPen(QColor('white'))
    painter.drawText(24,24,'HP 150%')
    stat = StatBarOverlay('hp')
    stat._locked = True
    stat._relayout()
    stat.set_value(.85)
    painter.drawPixmap(24,34,stat.grab())
    for index,value in enumerate((0,13,15,None)):
        dorcha.set_value(value)
        painter.drawText(24,105+index*76,'DORCHA' if value is not None else 'UNREADABLE')
        painter.drawPixmap(170,76+index*76,dorcha.grab())
    painter.end()
    assert sheet.save(str(out/'comparison.png'))
    for widget in (dorcha,stat,window):
        widget.close()
        widget.deleteLater()
    app.processEvents()
    print(out)


if __name__ == '__main__':
    main()
