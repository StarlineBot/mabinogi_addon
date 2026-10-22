"""실패 자료 복구/명시적 폐기 전용 대화상자. 기존 클립은 삭제하지 않는다."""
from datetime import datetime

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox


def clock_text(timestamp, now=None):
    """'오후 3:42'(오늘) / '10월 23일 오후 3:42'. 내부 ID 대신 사용자가 알아볼 시각으로 표시한다."""
    if timestamp is None:
        return '시각 확인 불가'
    try:
        t = datetime.fromtimestamp(timestamp)
    except (OverflowError, OSError, ValueError):
        return '시각 확인 불가'
    now = now or datetime.now()
    text = f"{'오전' if t.hour < 12 else '오후'} {t.hour % 12 or 12}:{t.minute:02d}"
    return text if t.date() == now.date() else f'{t.month}월 {t.day}일 {text}'


def session_text(session_id, now=None):
    """'PID:프로세스 생성 FILETIME' 실행 ID를 '오후 3:10에 시작한 게임 실행'으로."""
    try:
        created = int(str(session_id).split(':', 1)[1])
        return f'{clock_text((created - 116444736000000000) / 10_000_000, now)}에 시작한 게임 실행'
    except (IndexError, ValueError):
        return '게임 실행'


class BlackboxRecovery(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle('블랙박스 저장 내역·복구')
        self.resize(570, 340)
        layout = QVBoxLayout(self)
        label = QLabel('저장하지 못한 자료는 앱을 닫을 때 자동으로 정리해요.\n'
                       '그 전까지는 같은 구간을 다시 저장하거나 직접 폐기할 수 있어요.')
        label.setWordWrap(True); layout.addWidget(label)
        self.items = QComboBox(); layout.addWidget(self.items)
        self.detail = QLabel(); self.detail.setWordWrap(True); layout.addWidget(self.detail)
        self.retry = QPushButton('같은 구간 다시 저장'); layout.addWidget(self.retry)
        self.discard = QPushButton('선택한 실패 자료 폐기'); layout.addWidget(self.discard)
        self.cancel = QPushButton('선택한 저장 중단'); layout.addWidget(self.cancel)
        self.cancel.clicked.connect(self._cancel)
        self.cleanup = QPushButton('원본 정리 다시 시도'); layout.addWidget(self.cleanup)
        self.cleanup.clicked.connect(self._cleanup)
        self.sessions = QComboBox(); layout.addWidget(self.sessions)
        self.save_previous = QPushButton('선택한 게임 실행의 최근 영상 저장'); layout.addWidget(self.save_previous)
        self.save_previous.clicked.connect(self._save_previous)
        self.close_button = QPushButton('닫기'); layout.addWidget(self.close_button)
        self.retry.clicked.connect(self._retry)
        self.discard.clicked.connect(self._discard)
        self.close_button.clicked.connect(self.close)
        self.items.currentIndexChanged.connect(self._detail)
        self.refresh()

    def _label(self, runtime, ticket, result):
        if runtime is None:
            created = getattr(getattr(self.service, 'spool', None), 'created', lambda source: None)
            return f'{clock_text(created(ticket))} 녹화 · 미완성 캡처 자료'
        when = clock_text(getattr(runtime, 'requested_at', {}).get(ticket))
        return f'{when} 녹화 · ' + ('저장 진행 중' if result is None else
            ('저장 완료 · 정리 대기' if result.completed else '저장 실패'))

    def _view(self, sessions, entries, allowed):
        """화면에 보이는 내용(바뀔 때만 다시 그린다)."""
        return (sessions, allowed, tuple(
            (self._label(*entry), entry[1], entry[0] is None, None if entry[2] is None else
             (entry[2].completed, entry[2].error, entry[2].cleanup_error)) for entry in entries))

    def refresh(self):
        """컨트롤러 타이머가 창이 보이는 동안 100ms마다 부른다. 매번 목록을 비우고 버튼을 껐다 켜면
        누르는 중 클릭이 취소돼(폐기 무반응) 내용이 바뀔 때만 다시 그린다."""
        sessions = tuple(self.service.runtimes)
        entries = self.service.recoveries() + [(None, source, None) for source in self.service.orphan_sources()]
        allowed = self.service._allowed() and not self.service._closing
        view = self._view(sessions, entries, allowed)
        if view == getattr(self, '_shown', None):
            self.entries = entries  # 최신 객체 참조만 갱신(버튼·선택 상태는 그대로)
            return
        self._shown = view
        previous = self.items.currentIndex()
        previous_ticket = self.entries[previous][1] if hasattr(self, 'entries') and 0 <= previous < len(self.entries) else None
        previous_session = self.sessions.currentData()
        self.sessions.clear()
        for session_id in self.service.runtimes:
            self.sessions.addItem(session_text(session_id), session_id)  # 표시는 시각, 데이터는 실행 ID
        if previous_session is not None and self.sessions.findData(previous_session) >= 0:
            self.sessions.setCurrentIndex(self.sessions.findData(previous_session))
        self.save_previous.setEnabled(allowed)
        self.entries = entries
        self.items.blockSignals(True)
        self.items.clear()
        for entry in self.entries:
            self.items.addItem(self._label(*entry))
        self.items.blockSignals(False)
        for index, (_, ticket, _) in enumerate(self.entries):
            if ticket == previous_ticket:
                self.items.setCurrentIndex(index)
                break
        self._detail()

    def _detail(self):
        index = self.items.currentIndex()
        self.cancel.setEnabled(False)
        if not 0 <= index < len(self.entries):
            self.detail.setText('복구 대기 중인 저장 작업이 없어요.')
            self.retry.setEnabled(False); self.discard.setEnabled(False)
            return
        result = self.entries[index][2]
        if result is None and self.entries[index][0] is not None:
            self.detail.setText('저장 처리 또는 대기 중이에요. 중단해도 실패 자료는 명시적 폐기 전까지 보존해요.')
            self.retry.setEnabled(False); self.discard.setEnabled(False); self.cancel.setEnabled(True)
            return
        if result is None:
            self.detail.setText('완결 영상으로 등록되지 않은 자료예요. 자동 재생·복구를 보증하지 않아요.')
            self.retry.setEnabled(False); self.discard.setEnabled(True)
            return
        self.detail.setText(result.error or result.cleanup_error or '이전 실패 자료가 남아 있어요.')
        self.retry.setEnabled(not result.completed)
        self.discard.setEnabled(True)

    def _cancel(self):
        index = self.items.currentIndex()
        if not 0 <= index < len(self.entries):
            return
        runtime, ticket, result = self.entries[index]
        if runtime is None or result is not None:
            return
        try:
            self.service.cancel_save(runtime, ticket)
        except Exception as exc:
            QMessageBox.warning(self, '중단 요청 실패', str(exc))
        self.refresh()

    def _retry(self):
        index = self.items.currentIndex()
        if not 0 <= index < len(self.entries):
            return
        runtime, ticket, _ = self.entries[index]
        from uuid import uuid4
        output = self.service.settings.output_folder / f'blackbox-{uuid4().hex}.mp4'
        try:
            runtime.retry_failed(ticket, output)
        except Exception as exc:
            QMessageBox.warning(self, '재시도 실패', str(exc))
        self.refresh()

    def _discard(self):
        index = self.items.currentIndex()
        if not 0 <= index < len(self.entries):
            return
        runtime, ticket, result = self.entries[index]
        answer = QMessageBox.question(self, '실패 자료 폐기',
            '선택한 작업의 미완성·실패 파일을 삭제할까요?\n이미 저장한 클립과 현재 보관 중인 원본은 유지해요.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if runtime is None:
                self.service.spool.discard(ticket)
            elif result.completed:
                runtime.queue.discard_partial(ticket)
                runtime.accept_completed(ticket)
            else:
                runtime.discard_failed(ticket)
        except Exception as exc:
            QMessageBox.warning(self, '정리 실패', str(exc))
        self.refresh()

    def _cleanup(self):
        try:
            cleaned = self.service.retry_cleanup()
        except Exception as exc:
            QMessageBox.warning(self, '정리 실패', str(exc))
            self.refresh()
            return
        orphans = len(self.service.orphan_sources())
        lines = [f'원본 {cleaned}건을 정리했어요.' if cleaned else '정리 대기 중인 원본이 없어요.']
        if orphans:
            lines.append(f"미완성 캡처 자료 {orphans}건은 앱을 닫을 때 자동으로 정리해요. 지금 지우려면 "
                         "목록에서 선택한 뒤 '선택한 실패 자료 폐기'를 누르세요.")
        QMessageBox.information(self, '원본 정리', '\n'.join(lines))
        self.refresh()

    def _save_previous(self):
        import time
        try:
            self.service.request_saved_session(self.sessions.currentData(), time.perf_counter_ns() // 1000)
        except Exception as exc:
            QMessageBox.warning(self, '저장 요청 실패', str(exc))
        self.refresh()
