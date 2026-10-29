"""Embedded creator alpha pages using the application's shared form sections."""
from PySide6.QtWidgets import (QCheckBox,QComboBox,QFormLayout,QGroupBox,QHBoxLayout,
    QLabel,QLineEdit,QPushButton,QSpinBox,QTabWidget,QVBoxLayout,QWidget)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QStyledItemDelegate
from .widgets import FeatureHeader

# '자세히 보기 ▸'·'상세 설정 ▸': 펼쳐도 눌린 버튼처럼 보이지 않는 글자 버튼(13.13·13.14)
DISCLOSURE_STYLE = ('QPushButton { border:none; background:transparent; text-align:left; padding:2px 4px; }'
                    'QPushButton:hover { text-decoration:underline; }')
POPUP_ROLE = Qt.ItemDataRole.UserRole + 1  # 펼친 목록 문구(이름 + 배분 두 줄). 닫힌 목록은 DisplayRole


class _TwoLineDelegate(QStyledItemDelegate):
    """CPU 배치 펼친 목록(13.11): 항목마다 첫 줄 이름(맨 위 추천), 둘째 줄 실제 배분(회색).
    스타일은 항목 글자를 한 줄로만 그려 두 줄을 직접 그린다(선택 배경은 스타일 그대로)."""

    def paint(self, painter, option, index):
        popup = index.data(POPUP_ROLE)
        if not popup:
            return super().paint(painter, option, index)
        from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        item.text = ''
        style = item.widget.style() if item.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, item.widget)
        name, _, detail = popup.partition('\n')
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        palette = option.palette
        rect = option.rect.adjusted(8, 3, -8, -3)
        half = rect.height() // 2
        painter.save()
        painter.setPen(palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text))
        painter.drawText(rect.adjusted(0, 0, 0, -half), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        painter.setPen(palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.PlaceholderText))
        painter.drawText(rect.adjusted(0, half, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, detail)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if index.data(POPUP_ROLE):
            size.setHeight(option.fontMetrics.height() * 2 + 10)
        return size


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
        page=QWidget();body=QVBoxLayout(page);body.setContentsMargins(12,12,12,12)  # 다른 탭과 같은 여백(앱 문구 명세 10절)
        from .feature_copy import HELP
        from .help_dialog import help_button
        body.addWidget(FeatureHeader('게임 최적화','선택한 CPU 배치와 네트워크 설정을 적용하고, 변경 전 값으로 되돌릴 수 있어요.',
                                     help_button('게임 최적화 사용법',HELP['게임 최적화'],self)))
        group=_group('환경 확인',body)
        self.cpu_info=_label('최적화 탭을 열면 CPU 구조와 네트워크 어댑터를 자동으로 읽어요. 읽기만 하고 설정은 바꾸지 않아요.')
        group.addWidget(self.cpu_info)
        self.inspect=QPushButton('다시 확인');row=QHBoxLayout();row.addWidget(self.inspect);row.addStretch();group.addLayout(row)
        from .settings_layout import LOCK_STYLE
        # 13.14 추천 최적화(시안 사용자 확인): 환경 확인 바로 아래. 예전 '적용 · 복구' 구역을 합쳐 시작 버튼은 하나.
        group=_group('추천 최적화',body)
        self.recommend=_label('이 PC 추천: 환경을 확인하면 보여줘요.');self.recommend.setStyleSheet('font-weight:bold;')
        group.addWidget(self.recommend)
        # 토글 하나(13.5): 꺼짐 '추천 설정으로 최적화'(직접 고르면 '선택한 설정으로 최적화') → 켜짐 '최적화 적용 중'(민트). 켜진 상태에서 누르면 중단·원복.
        self.toggle=QPushButton('추천 설정으로 최적화');self.toggle.setCheckable(True);self.toggle.setStyleSheet(LOCK_STYLE)
        group.addWidget(self.toggle,0,Qt.AlignmentFlag.AlignLeft)
        # 13.10 자동 적용(기본 꺼짐): 우선순위·CPU 배치만. 네트워크는 자동으로 바꾸지 않는다.
        self.auto=QCheckBox('마비노기를 켜면 자동 적용');group.addWidget(self.auto)
        self.auto_note=_label('켜 두면 앱을 켤 때부터 게임을 기다렸다가 우선순위·CPU 배치를 걸고, 게임을 끄면 그 게임에 건 값만 되돌려요.\n'
                              '패스트핑(네트워크)은 자동으로 바꾸지 않아요.')
        self.auto_note.setForegroundRole(QPalette.ColorRole.PlaceholderText);group.addWidget(self.auto_note)
        # 13.13 결과 요약: 지금 상태 한 줄(굵게·색) + 항목마다 한 줄. 상세(세션 기록)는 접힌 '자세히 보기'와 app.log.
        self.status=_label('시작 전 · 시스템 설정을 변경하지 않았어요.');group.addWidget(self.status)
        self.results=_label('');group.addWidget(self.results)
        self.details_toggle=QPushButton('자세히 보기 ▸');self.details_toggle.setFlat(True);self.details_toggle.setCheckable(True)
        self.details_toggle.setCursor(Qt.CursorShape.PointingHandCursor);self.details_toggle.setStyleSheet(DISCLOSURE_STYLE)
        group.addWidget(self.details_toggle,0,Qt.AlignmentFlag.AlignLeft)
        self.details=_label('');self.details.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);self.details.hide()
        group.addWidget(self.details)
        self.details_toggle.toggled.connect(self._toggle_details)
        # '상세 설정 ▸'는 구역 테두리 밖 바로 아래(사용자 수정: 안에 있으면 그 안에서 펼쳐질 것처럼 보임). 펼침 상태는 저장.
        self.advanced_toggle=QPushButton('상세 설정 ▸');self.advanced_toggle.setFlat(True);self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setCursor(Qt.CursorShape.PointingHandCursor);self.advanced_toggle.setStyleSheet(DISCLOSURE_STYLE)
        body.addWidget(self.advanced_toggle,0,Qt.AlignmentFlag.AlignLeft)
        self.advanced=QWidget();advanced=QVBoxLayout(self.advanced);advanced.setContentsMargins(0,0,0,0)
        body.addWidget(self.advanced)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        group=_group('CPU 배치',advanced)
        # 최적화 명세 13.7: 게임 프로세스 우선순위 '높음'(기본 켬). 실시간·다른 프로그램 우선순위 변경은 하지 않는다.
        self.priority=QCheckBox('게임 우선순위 높음');self.priority.setChecked(True);group.addWidget(self.priority)
        group.addWidget(_label('무거운 장면에서 Windows가 게임을 먼저 실행해요. 끄거나 세션이 끝나면 원래 값으로 되돌려요.\n'
                               '다른 도구가 우선순위를 바꾸면 덮어쓰지 않아요.'))
        # 13.11(렌더 시안 사용자 확인): 체크박스 대신 '배치 안 함' 항목. 닫힌 목록은 `이름 (추천) · 6+2`, 아래 회색 두 줄에 실제 배분과 근거,
        # 펼친 목록은 항목마다 이름 + 배분 한 줄. 목록은 감지한 CPU 구조로 만들고 추천 순으로 정렬한다.
        self.split=QComboBox();self.split.addItem('CPU 구조를 먼저 확인해 주세요.',None)
        self.split.setItemDelegate(_TwoLineDelegate(self.split))
        form=QFormLayout();form.addRow('CPU 배치',self.split);group.addLayout(form)
        self.split_detail=_label('');self.split_detail.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        group.addWidget(self.split_detail)
        group=_group('네트워크',advanced)
        # 13.12: 이름 '패스트핑'(사용자 결정) → 적용할 연결(인터넷 기본 경로 어댑터 자동 선택) → 설명. 13.9: TcpAckFrequency, 13.8: RSS 없음.
        self.tcp=QCheckBox('패스트핑');group.addWidget(self.tcp)
        self.adapter=QComboBox();self.adapter.addItem('적용할 연결을 선택해 주세요.',None)
        self.adapter_label=QLabel('');self.adapter_label.hide()
        connection=QHBoxLayout();connection.addWidget(self.adapter,1);connection.addWidget(self.adapter_label,1)
        form=QFormLayout();form.addRow('적용할 연결',connection);group.addLayout(form)
        self.notice=_label('TCP 응답을 모아 보내지 않고 바로 보내요(TcpAckFrequency) · 수신 창 자동 조정은 기본값(Normal)으로 둬요.\n'
                           '다른 앱의 통신에도 영향을 줄 수 있고 관리자 권한·재연결이 필요해요. 게임 실행 중이면 네트워크는 미뤄요.\n'
                           '성능이 좋아졌다는 의미는 아니에요. 효과는 별도 계측으로 비교해 주세요.')
        self.notice.setForegroundRole(QPalette.ColorRole.PlaceholderText);group.addWidget(self.notice)
        group=_group('그래픽',advanced)
        # 13.6(화면 확정): 체크 · 그래픽카드 이름과 상한 · 회색 설명. NVIDIA가 아니면 체크 비활성 + 이유.
        self.graphics=QCheckBox('그래픽 효율 최적화');group.addWidget(self.graphics)
        self.gpu_label=QLabel('환경을 확인하면 보여줘요.')
        form=QFormLayout();form.addRow('그래픽카드',self.gpu_label);group.addLayout(form)
        self.graphics_notice=_label('로딩·캐릭터 선택처럼 헛도는 순간만 최대 프레임을 400으로 막아 전력·발열을 줄여요.\n'
                                    '이미 400 이하로 제한해 뒀으면 그대로 두고, 수직 동기화는 바꾸지 않아요. NVIDIA 그래픽카드만 지원해요.')
        self.graphics_notice.setForegroundRole(QPalette.ColorRole.PlaceholderText);group.addWidget(self.graphics_notice)
        # 13.14: 추천과 다르게 고르면 상세 끝에 보인다.
        self.reset_recommended=QPushButton('추천 설정으로 되돌리기');self.reset_recommended.hide()
        advanced.addWidget(self.reset_recommended,0,Qt.AlignmentFlag.AlignLeft)
        self.advanced.hide()
        body.addStretch()
        self.tabs.addTab(_scrolled(page),'최적화')
        page=QWidget();body=QVBoxLayout(page);body.setContentsMargins(12,12,12,12)  # 다른 탭과 같은 여백(앱 문구 명세 10절)
        body.addWidget(FeatureHeader('FPS 측정','마비노기의 프레임을 측정해 현재 FPS를 보여줘요.'))
        # 표시와 수집 분리(FPS 명세 8.3, 2026-10-23 지금 적용): 위는 게임에 FPS 표시 켜기·끄기 하나, 파일 수집은 아래 베타 묶음.
        group=_group('게임에 FPS 표시',body)
        group.addWidget(_label('켜 두면 게임 화면에 FPS를 보여줘요. 파일로 남기지 않아요.\n'
                               '게임의 제출 프레임 기준이며, 모니터에 실제 표시된 FPS·통신 지연과는 달라요.'))
        from .settings_layout import LOCK_STYLE
        self.frames_toggle=QPushButton('FPS 표시');self.frames_toggle.setCheckable(True);self.frames_toggle.setStyleSheet(LOCK_STYLE)
        self.frames_toggle.toggled.connect(lambda on: self.frames_toggle.setText('FPS 표시 중' if on else 'FPS 표시'))
        group.addWidget(self.frames_toggle,0,Qt.AlignmentFlag.AlignLeft)
        group=_group('오버레이',body)
        # 다른 탭과 같은 잠금 버튼(잠금됨 = 초록, 앱 문구 명세 10절). 체크 상태 API는 체크박스와 같다.
        from .settings_layout import lock_button, set_lock_text
        self.lock=lock_button(True)  # 앱 전체 같은 글자·폭(명세 13.1)
        self.lock.toggled.connect(lambda on: set_lock_text(self.lock, on))
        self.lock.setChecked(True);group.addWidget(self.lock,0,Qt.AlignmentFlag.AlignLeft)
        self.scale=QSpinBox();self.scale.setRange(50,300);self.scale.setValue(100);self.scale.setSuffix(' %')
        form=QFormLayout();form.addRow('표시 배율',self.scale);group.addLayout(form)
        # 표시 항목(FPS 명세 8.4): 기본은 FPS만. 표시만 바꾸며 구간 요약·수집에는 영향 없음.
        row=QHBoxLayout();self.metric_boxes={}
        for key, text in (('fps','FPS'),('cpu','게임 CPU'),('gpu','GPU'),('memory','게임 메모리')):
            self.metric_boxes[key]=QCheckBox(text);row.addWidget(self.metric_boxes[key])
        row.addStretch();form.addRow('표시 항목',row)
        # FPS 명세 10.4 D안·10.5 읽는 법(문구만 변경, 배치는 현행 유지 10.3)
        group.addWidget(_label('게임 CPU: 마비노기에서 가장 바쁜 작업이 코어 하나를 얼마나 쓰는지 · GPU: 작업 관리자와 같은 엔진 사용률 · '
                               '게임 메모리: 마비노기가 차지한 메모리\n1초마다 읽기만 해요. 작업 관리자는 PC 전체 기준이라 숫자가 달라요.'))
        group=_group('상태 · 수집 품질',body)
        self.frames_status=_label('꺼짐 · 표시 안 함');group.addWidget(self.frames_status)
        group.addWidget(_label('앱을 다시 실행해도 FPS 표시 설정은 유지돼요.\n전투 보조 일시정지는 FPS 표시만 숨겨요.'))
        group=_group('프레임 수집',body)
        self.collect_box=group.parentWidget()  # 13.15: 수집 모드는 제작자만 보임
        group.addWidget(_label('수집 모드를 켜 두면 FPS 표시와 관계없이 게임이 앞에 있는 동안 구간 요약을 파일로 남겨요.\n'
                               '게임 CPU·GPU 사용률과 게임의 CPU 선호도·우선순위도 함께 기록해요. 매 프레임 원본은 저장하지 않아요.\n'
                               '수집 모드는 앱을 실행할 때마다 꺼진 상태로 시작해요.'))
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

    def _toggle_details(self, on):
        self.details.setVisible(on)
        self.details_toggle.setText('자세히 보기 ▾' if on else '자세히 보기 ▸')

    def _toggle_advanced(self, on):
        self.advanced.setVisible(on)
        self.advanced_toggle.setText('상세 설정 ▾' if on else '상세 설정 ▸')
