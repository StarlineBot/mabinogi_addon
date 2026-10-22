"""실패 자료 복구/명시적 폐기 전용 대화상자. 기존 클립은 삭제하지 않는다."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox


class BlackboxRecovery(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle('블랙박스 저장 내역·복구')
        self.resize(570, 340)
        layout = QVBoxLayout(self)
        label = QLabel('실패 자료와 원본은 자동으로 삭제하지 않아요.\n재시도는 처음 요청한 구간을 사용해요.')
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

    def refresh(self):
        previous = self.items.currentIndex()
        previous_ticket = self.entries[previous][1] if hasattr(self, 'entries') and 0 <= previous < len(self.entries) else None
        previous_session = self.sessions.currentText()
        self.sessions.clear()
        for session_id in self.service.runtimes:
            self.sessions.addItem(session_id)
        if previous_session:
            self.sessions.setCurrentText(previous_session)
        self.save_previous.setEnabled(self.service._allowed() and not self.service._closing)
        self.entries = self.service.recoveries() + [(None, source, None) for source in self.service.orphan_sources()]
        self.items.clear()
        for runtime, ticket, result in self.entries:
            if runtime is None:
                self.items.addItem(f'{ticket[:8]} · 미완성 캡처 자료')
                continue
            self.items.addItem(f'{ticket[:8]} · ' + ('저장 진행 중' if result is None else
                ('저장 완료 · 정리 대기' if result.completed else '저장 실패')))
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
            self.service.retry_cleanup()
        except Exception as exc:
            QMessageBox.warning(self, '정리 실패', str(exc))
        self.refresh()

    def _save_previous(self):
        import time
        try:
            self.service.request_saved_session(self.sessions.currentText(), time.perf_counter_ns() // 1000)
        except Exception as exc:
            QMessageBox.warning(self, '저장 요청 실패', str(exc))
        self.refresh()
