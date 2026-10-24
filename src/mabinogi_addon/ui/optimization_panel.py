"""Embedded creator alpha pages using the application's shared form sections."""
from PySide6.QtWidgets import (QCheckBox,QComboBox,QFormLayout,QGroupBox,QHBoxLayout,
    QLabel,QLineEdit,QPushButton,QSpinBox,QTabWidget,QVBoxLayout,QWidget)
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
        # 최적화 명세 13.7: 게임 프로세스 우선순위 '높음'(기본 켬). 실시간·다른 프로그램 우선순위 변경은 하지 않는다.
        self.priority=QCheckBox('게임 우선순위 높음');self.priority.setChecked(True);group.addWidget(self.priority)
        group.addWidget(_label('무거운 장면에서 Windows가 게임을 먼저 실행해요. 끄거나 세션이 끝나면 원래 값으로 되돌려요.\n'
                               '다른 도구가 우선순위를 바꾸면 덮어쓰지 않아요.'))
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
        # 토글 하나(명세 13.5, 렌더 2안): 꺼짐 '최적화 시작' → 켜짐 '최적화 적용 중'(민트). 켜진 상태에서 누르면 중단·원복.
        from PySide6.QtCore import Qt
        from .settings_layout import LOCK_STYLE
        self.toggle=QPushButton('최적화 시작');self.toggle.setCheckable(True);self.toggle.setStyleSheet(LOCK_STYLE)
        group.addWidget(self.toggle,0,Qt.AlignmentFlag.AlignLeft)
        self.status=_label('시작 전 · 시스템 설정을 변경하지 않았어요.');group.addWidget(self.status)
        self.results=_label('');group.addWidget(self.results);body.addStretch()
        self.tabs.addTab(_scrolled(page),'최적화')
        page=QWidget();body=QVBoxLayout(page)
        body.addWidget(FeatureHeader('FPS 측정','마비노기의 프레임을 측정해 현재 FPS를 보여줘요.'))
        # 표시와 수집 분리(FPS 명세 8.3, 2026-10-23 지금 적용): 위는 게임에 FPS 표시 켜기·끄기 하나, 파일 수집은 아래 베타 묶음.
        group=_group('게임에 FPS 표시',body)
        group.addWidget(_label('켜 두면 게임 화면에 FPS를 보여줘요. 파일로 남기지 않아요.\n'
                               '게임의 제출 프레임 기준이며, 모니터에 실제 표시된 FPS·통신 지연과는 달라요.'))
        from PySide6.QtCore import Qt
        from .settings_layout import LOCK_STYLE
        self.frames_toggle=QPushButton('FPS 표시');self.frames_toggle.setCheckable(True);self.frames_toggle.setStyleSheet(LOCK_STYLE)
        self.frames_toggle.toggled.connect(lambda on: self.frames_toggle.setText('FPS 표시 중' if on else 'FPS 표시'))
        group.addWidget(self.frames_toggle,0,Qt.AlignmentFlag.AlignLeft)
        group=_group('오버레이',body)
        self.lock=QCheckBox('위치 잠금');self.lock.setChecked(True);group.addWidget(self.lock)
        self.scale=QSpinBox();self.scale.setRange(50,300);self.scale.setValue(100);self.scale.setSuffix(' %')
        form=QFormLayout();form.addRow('표시 배율',self.scale);group.addLayout(form)
        # 표시 항목(FPS 명세 8.4): 기본은 FPS만. 표시만 바꾸며 구간 요약·수집에는 영향 없음.
        row=QHBoxLayout();self.metric_boxes={}
        for key, text in (('fps','FPS'),('cpu','CPU'),('gpu','GPU'),('memory','메모리')):
            self.metric_boxes[key]=QCheckBox(text);row.addWidget(self.metric_boxes[key])
        row.addStretch();form.addRow('표시 항목',row)
        group.addWidget(_label('CPU: 가장 바쁜 논리 코어 사용률 · GPU: 작업 관리자와 같은 엔진 사용률 · '
                               '메모리: 게임 전용 메모리\n1초마다 읽기만 해요. 실제 Windows 수치 확인 전이라 정확도를 보증하지 않아요.'))
        group=_group('상태 · 수집 품질',body)
        self.frames_status=_label('꺼짐 · 표시 안 함');group.addWidget(self.frames_status)
        group.addWidget(_label('앱을 다시 실행해도 FPS 표시 설정은 유지돼요. 수집 모드는 매번 꺼진 상태로 시작해요.\n전투 보조 일시정지는 FPS 표시만 숨겨요.'))
        group=_group('프레임 수집(베타)',body)
        group.addWidget(_label('수집 모드를 켜 두면 FPS 표시와 관계없이 게임이 앞에 있는 동안 구간 요약을 파일로 남겨요.\n'
                               'CPU·GPU 사용률과 게임의 CPU 선호도·우선순위도 함께 기록해요. 매 프레임 원본은 저장하지 않아요.'))
        row=QHBoxLayout()
        self.summary_save=QPushButton('요약 저장');row.addWidget(self.summary_save)
        self.summary_folder=QPushButton('폴더 열기');row.addWidget(self.summary_folder)
        self.summary_conditions=QPushButton('조건별 정리');row.addWidget(self.summary_conditions)
        from .widgets import checkbox, CapturePathLabel
        self.summary_collect=checkbox('수집 모드(구간 요약 자동 저장)');row.addWidget(self.summary_collect,1)
        group.addLayout(row)
        self.summary_path=CapturePathLabel();group.addWidget(self.summary_path)
        # 앱이 알 수 없는 조건(FPS 제한·렌더링 엔진·외부 도구·장면)을 측정마다 남긴다(FPS 7절).
        self.condition=QLineEdit();self.condition.setMaxLength(48)
        self.condition.setPlaceholderText('예: 7+1 SMT끔 · Vulkan · 제한없음')
        self.condition.setToolTip('입력을 마치면(Enter 또는 다른 곳 클릭) 바로 적용돼요. 기록 중이면 구간을 끊고 새 이름으로 이어서 기록해요.')
        form=QFormLayout();form.addRow('측정 조건',self.condition);group.addLayout(form)
        self.summary_select=QComboBox();self.summary_select.addItem('현재 구간',None)
        group.addWidget(self.summary_select)
        self.summary_result=_label('측정값 없음 · 1% low는 유효 간격 100개부터 표시해요.')
        group.addWidget(self.summary_result)
        self.condition_result=_label('');self.condition_result.hide();group.addWidget(self.condition_result)
        group.addWidget(_label('1% low: 느린 상위 1% 간격의 평균을 FPS로 환산해요(P99 아님).\n긴 간격: 해당 구간 중앙값의 2배 초과. 최적화 효과 판정이 아니며 같은 장면·조건에서 비교해 주세요.'))
        body.addStretch();self.tabs.addTab(_scrolled(page),'FPS 측정')
        for combo in (self.split,self.adapter):
            combo.setMinimumContentsLength(16)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
