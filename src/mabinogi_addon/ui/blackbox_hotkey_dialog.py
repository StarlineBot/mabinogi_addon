"""블랙박스 저장 단축키 변경 창(0.16.0). 누른 조합을 보여주고 규칙(blackbox_shortcut.check)으로 판정한다.

키 입력은 이 창이 받는 Qt 이벤트만 쓴다(전역 훅·입력 생성 없음). Windows에서 PrintScreen은 누름 없이 뗌만 오는 경우가 있어
뗌도 처리하고, 키 코드는 nativeVirtualKey()(Windows 가상 키)를 우선 쓴다. 다른 OS(렌더·테스트)는 Qt 키 표로 바꾼다.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from . import palette
from ..blackbox_shortcut import ALT, CTRL, DEFAULT, SHIFT, WIN, check, hotkey_text

K = Qt.Key
_QT_VK = {K.Key_Print: 0x2C, K.Key_Pause: 0x13, K.Key_ScrollLock: 0x91, K.Key_Insert: 0x2D, K.Key_Delete: 0x2E,
          K.Key_Home: 0x24, K.Key_End: 0x23, K.Key_PageUp: 0x21, K.Key_PageDown: 0x22, K.Key_Left: 0x25,
          K.Key_Up: 0x26, K.Key_Right: 0x27, K.Key_Down: 0x28, K.Key_Space: 0x20, K.Key_Tab: 0x09,
          K.Key_Return: 0x0D, K.Key_Enter: 0x0D, K.Key_Backspace: 0x08, K.Key_Minus: 0xBD, K.Key_Equal: 0xBB,
          K.Key_Comma: 0xBC, K.Key_Period: 0xBE, K.Key_Slash: 0xBF, K.Key_Semicolon: 0xBA, K.Key_Apostrophe: 0xDE,
          K.Key_BracketLeft: 0xDB, K.Key_BracketRight: 0xDD, K.Key_Backslash: 0xDC, K.Key_QuoteLeft: 0xC0,
          K.Key_Control: 0x11, K.Key_Alt: 0x12, K.Key_Shift: 0x10, K.Key_Meta: 0x5B, K.Key_CapsLock: 0x14,
          K.Key_NumLock: 0x90}
_MODIFIER_KEYS = {K.Key_Control, K.Key_Alt, K.Key_Shift, K.Key_Meta, K.Key_AltGr}


def event_vk(event):
    """키 이벤트 → Windows 가상 키 코드(수식 키만이면 None)."""
    key = event.key()
    if key in _MODIFIER_KEYS:
        return None
    native = event.nativeVirtualKey() if sys.platform == 'win32' else 0
    if native:
        return int(native)
    if K.Key_A <= key <= K.Key_Z or K.Key_0 <= key <= K.Key_9:
        return int(key)
    if K.Key_F1 <= key <= K.Key_F24:
        return 0x70 + int(key) - int(K.Key_F1)
    return _QT_VK.get(key)


def event_modifiers(event):
    flags = event.modifiers()
    mods = 0
    for flag, mask in ((Qt.KeyboardModifier.ControlModifier, CTRL), (Qt.KeyboardModifier.AltModifier, ALT),
                       (Qt.KeyboardModifier.ShiftModifier, SHIFT), (Qt.KeyboardModifier.MetaModifier, WIN)):
        if flags & flag:
            mods |= mask
    # 수식 키 자체의 누름/뗌은 modifiers()에 아직(이미) 반영되지 않은 경우가 있어 키로 보정한다.
    key = {K.Key_Control: CTRL, K.Key_Alt: ALT, K.Key_Shift: SHIFT, K.Key_Meta: WIN}.get(event.key(), 0)
    if event.type() == QEvent.Type.KeyPress:
        mods |= key
    return mods


class HotkeyDialog(QDialog):
    def __init__(self, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle('저장 단축키 변경')
        self.setMinimumWidth(420)
        self.result_hotkey = None
        self._current = tuple(current)
        self._value = None   # (수식, 키) — 마지막으로 누른 조합(미완성이면 키 None)
        self._done = True    # 완성 조합(처음엔 지금 쓰는 조합)을 받은 뒤 다음 누름은 새 조합으로 시작
        self._pressed = set()  # 누름을 받은 일반 키(뗌만 오는 키와 구분)
        body = QVBoxLayout(self)
        body.setSpacing(10)
        body.addWidget(QLabel('새 단축키를 눌러 주세요.'))
        self.field = QLineEdit()
        self.field.setReadOnly(True)
        self.field.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont(self.font())
        font.setPixelSize(20)
        font.setBold(True)
        self.field.setFont(font)
        self.field.setMinimumHeight(48)
        body.addWidget(self.field)
        self.verdict = QLabel('')
        self.verdict.setWordWrap(True)
        body.addWidget(self.verdict)
        help_text = QLabel('Ctrl·Alt·Shift 중 하나 이상과 다른 키 하나를 함께 눌러요. 키 입력은 게임에도 그대로 전달되니, '
                           '게임에서 쓰지 않는 조합을 고르세요.')
        help_text.setWordWrap(True)
        help_text.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        body.addWidget(help_text)
        row = QHBoxLayout()
        self.default = QPushButton(f'기본값({hotkey_text(*DEFAULT)})')
        self.cancel = QPushButton('취소')
        self.save = QPushButton('저장')
        for button in (self.default, self.cancel, self.save):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 키 입력(Space·Enter)이 버튼으로 가지 않게
            button.setAutoDefault(False)
        row.addWidget(self.default)
        row.addStretch()
        row.addWidget(self.cancel)
        row.addWidget(self.save)
        body.addLayout(row)
        self.default.clicked.connect(lambda: self.feed(True, DEFAULT[1], DEFAULT[0]))
        self.cancel.clicked.connect(self.reject)
        self.save.clicked.connect(self._save)
        self._show(self._current, initial=True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ---- 판정 ----
    def feed(self, pressed, vk, modifiers):
        """키 누름/뗌 하나를 반영한다. vk None은 수식 키. 뗌은 누름 없이 온 일반 키(PrintScreen)만 조합으로 받는다."""
        if pressed:
            if vk is None:
                if self._done or self._value is None or self._value[1] is None:
                    self._done = False
                    self._show((modifiers, None))
                return
            self._pressed.add(vk)
            self._done = True
            self._show((modifiers, vk))
        elif vk is not None:
            if vk in self._pressed:
                self._pressed.discard(vk)  # 누름에서 이미 받은 키: 떼는 순서(수식 키 먼저 등)로 조합을 바꾸지 않는다
                return
            self._done = True  # 뗌만 온 키(Windows PrintScreen): 뗄 때의 수식 키로 조합을 받는다
            self._show((modifiers, vk))

    def _show(self, value, initial=False):
        self._value = value
        modifiers, vk = value
        names = [name for mask, name in ((CTRL, 'Ctrl'), (ALT, 'Alt'), (SHIFT, 'Shift'), (WIN, 'Win')) if modifiers & mask]
        self.field.setText(hotkey_text(modifiers, vk) if vk is not None else '+'.join(names + ['…']) if names else '')
        state, message = check(modifiers, vk)
        if initial:
            state, message = 'current', '지금 쓰는 단축키예요.'
        color = {'ok': palette.color('ok'), 'invalid': palette.color('danger')}.get(state)
        self.verdict.setStyleSheet(f'color:{color};' if color else '')
        # 판정 색(초록·빨강)은 흐린 안내 글자 역할을 쓰지 않아야 제 색으로 보인다
        self.verdict.setForegroundRole(QPalette.ColorRole.WindowText if color else QPalette.ColorRole.PlaceholderText)
        self.verdict.setText(message)
        self.state = state
        self.save.setEnabled(state == 'ok' and value != self._current)

    def _save(self):
        if self.state == 'ok':
            self.result_hotkey = self._value
            self.accept()

    # ---- Qt 키 이벤트 ----
    def event(self, event):
        # Tab·Enter 같은 키도 포커스 이동·기본 버튼 대신 조합으로 받는다.
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and not event.isAutoRepeat():
            if event.type() == QEvent.Type.KeyPress and event.key() == K.Key_Escape and not event.modifiers():
                self.reject()
                return True
            self.feed(event.type() == QEvent.Type.KeyPress, event_vk(event), event_modifiers(event))
            return True
        return super().event(event)
