"""Embedded creator alpha pages using the application's shared form sections."""
from PySide6.QtWidgets import (QCheckBox,QComboBox,QFormLayout,QGroupBox,QHBoxLayout,
    QLabel,QPushButton,QSpinBox,QTabWidget,QVBoxLayout,QWidget)
from .widgets import FeatureHeader


def _label(text):
    widget=QLabel(text);widget.setWordWrap(True)
    return widget


def _group(title,body):
    box=QGroupBox(title);layout=QVBoxLayout(box)
    body.addWidget(box)
    return layout


class OptimizationPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        from .main_window import _scrolled
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0)
        self.tabs=QTabWidget();root.addWidget(self.tabs)
        page=QWidget();body=QVBoxLayout(page)
        body.addWidget(FeatureHeader('게임 최적화','선택한 CPU 배치와 네트워크 설정을 적용하고, 변경 전 값으로 되돌릴 수 있어요.'))
        group=_group('환경 확인',body)
        self.cpu_info=_label('최적화 탭을 열면 CPU 구조와 네트워크 어댑터를 자동으로 읽어요. 읽기만 하고 설정은 바꾸지 않아요.')
        group.addWidget(self.cpu_info)
        self.inspect=QPushButton('다시 확인');row=QHBoxLayout();row.addWidget(self.inspect);row.addStretch();group.addLayout(row)
        group=_group('CPU 배치',body)
        self.cpu=QCheckBox('게임·백그라운드 CPU 배치');self.cpu.setChecked(True);group.addWidget(self.cpu)
        self.split=QComboBox();self.split.addItem('CPU 구조를 먼저 확인해 주세요.',None)
        form=QFormLayout();form.addRow('물리 코어 배분',self.split);group.addLayout(form)
        group=_group('네트워크',body)
        self.adapter=QComboBox();self.adapter.addItem('네트워크 어댑터를 선택해 주세요.',None)
        form=QFormLayout();form.addRow('네트워크 어댑터',self.adapter);group.addLayout(form)
        self.tcp=QCheckBox('패스트핑 · TCP 자동 조정 Normal')
        self.rss=QCheckBox('RSS 수신 처리를 백그라운드 코어에 배치')
        group.addWidget(self.tcp);group.addWidget(self.rss)
        self.notice=_label('TCP·RSS는 다른 앱의 통신에도 영향을 줄 수 있고 관리자 권한·재연결이 필요해요.\n게임 실행 중 시작하면 네트워크는 미루고 CPU만 적용해요.\n성능이 좋아졌다는 의미는 아니에요. 효과는 별도 계측으로 비교해 주세요.')
        group.addWidget(self.notice)
        group=_group('적용 · 복구',body)
        # 원복은 버튼 하나: 적용했던 CPU·네트워크를 한 번에 되돌린다(네트워크가 있으면 연결 끊김 확인 1회).
        self.start=QPushButton('최적화 시작');self.stop=QPushButton('중단 · 원복')
        row=QHBoxLayout()
        for button in (self.start,self.stop): row.addWidget(button)
        group.addLayout(row)
        self.status=_label('시작 전 · 시스템 설정을 변경하지 않았어요.');group.addWidget(self.status)
        self.results=_label('');group.addWidget(self.results);body.addStretch()
        self.tabs.addTab(_scrolled(page),'최적화')
        page=QWidget();body=QVBoxLayout(page)
        body.addWidget(FeatureHeader('FPS 측정','마비노기의 프레임을 측정해 현재 FPS를 보여줘요.'))
        group=_group('대상 · 측정',body)
        group.addWidget(_label('측정 시작을 누르면 등록한 게임창을 대상으로 프레임을 수집해요.\n게임의 제출 프레임 기준이며, 모니터에 실제 표시된 FPS·통신 지연과는 달라요.'))
        self.source=QComboBox();self.source.addItem('렌더링 대상: 측정 준비 중',None)
        form=QFormLayout();form.addRow('렌더링 대상',self.source);group.addLayout(form)
        self.frames_start=QPushButton('FPS 측정 시작');self.frames_stop=QPushButton('측정 중단')
        row=QHBoxLayout();row.addWidget(self.frames_start);row.addWidget(self.frames_stop);row.addStretch();group.addLayout(row)
        group=_group('오버레이',body)
        self.lock=QCheckBox('위치 잠금');self.lock.setChecked(True);group.addWidget(self.lock)
        self.scale=QSpinBox();self.scale.setRange(50,300);self.scale.setValue(100);self.scale.setSuffix(' %')
        form=QFormLayout();form.addRow('표시 배율',self.scale);group.addLayout(form)
        group=_group('상태 · 수집 품질',body)
        self.frames_status=_label('중단됨 · 측정값 없음');group.addWidget(self.frames_status)
        group.addWidget(_label('Windows 권한이 부족하면 측정을 시작하지 못할 수 있어요. 자동으로 관리자 권한을 요청하지 않아요.'))
        group.addWidget(_label('앱을 다시 실행하면 자동으로 측정하지 않아요. 전투 보조 일시정지는 FPS 표시만 숨겨요.'))
        group=_group('프레임 수집 · 구간 요약',body)
        group.addWidget(_label('FPS 측정 중 자동으로 집계해요. 수집 모드를 켜면 구간 요약을 파일로 남겨요. 매 프레임 원본은 저장하지 않아요.'))
        row=QHBoxLayout()
        self.summary_save=QPushButton('요약 저장');row.addWidget(self.summary_save)
        self.summary_folder=QPushButton('폴더 열기');row.addWidget(self.summary_folder)
        from .widgets import checkbox, CapturePathLabel
        self.summary_collect=checkbox('수집 모드(구간 요약 자동 저장)');row.addWidget(self.summary_collect,1)
        group.addLayout(row)
        self.summary_path=CapturePathLabel();group.addWidget(self.summary_path)
        self.summary_select=QComboBox();self.summary_select.addItem('현재 구간',None)
        group.addWidget(self.summary_select)
        self.summary_result=_label('측정값 없음 · 1% low는 유효 간격 100개부터 표시해요.')
        group.addWidget(self.summary_result)
        group.addWidget(_label('1% low: 느린 상위 1% 간격의 평균을 FPS로 환산해요(P99 아님).\n긴 간격: 해당 구간 중앙값의 2배 초과. 최적화 효과 판정이 아니며 같은 장면·조건에서 비교해 주세요.'))
        body.addStretch();self.tabs.addTab(_scrolled(page),'FPS 측정')
        for combo in (self.split,self.adapter,self.source):
            combo.setMinimumContentsLength(16)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
