"""블랙박스 저장 단축키 규칙(0.16.0). OS·Qt 없이 판정한다.

수식 마스크는 RegisterHotKey와 같다(Alt=1, Ctrl=2, Shift=4, Win=8). 키는 Windows 가상 키 코드.
규칙: Ctrl·Alt·Shift 중 하나 이상 + 수식 키가 아닌 키 하나. Win 키 조합은 쓰지 않는다(시스템 단축키와 겹침).
"""
from __future__ import annotations

ALT, CTRL, SHIFT, WIN = 1, 2, 4, 8
DEFAULT = (CTRL | ALT, 0x2C)  # Ctrl+Alt+PrintScreen
# 수식 키 자체(좌우 구분 포함)와 Win 키, 마우스 버튼은 '나머지 키'가 될 수 없다.
MODIFIER_VKS = frozenset({0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C})
_NOT_KEYS = frozenset({0x01, 0x02, 0x03, 0x04, 0x05, 0x06})


def check(modifiers, vk):
    """(상태, 문구). 상태: 'ok' | 'incomplete'(수식 키만 누름) | 'invalid'."""
    if type(modifiers) is not int or modifiers & ~0xF:
        return 'invalid', '알 수 없는 조합이에요.'
    if modifiers & WIN:
        return 'invalid', 'Windows 키가 들어간 조합은 쓸 수 없어요.'
    if vk is None or vk in MODIFIER_VKS:
        if not modifiers & (CTRL | ALT | SHIFT):
            return 'incomplete', 'Ctrl·Alt·Shift 중 하나 이상과 다른 키 하나를 함께 눌러 주세요.'
        return 'incomplete', '함께 누를 키 하나를 더 눌러 주세요.'
    if type(vk) is not int or not 1 <= vk <= 254 or vk in _NOT_KEYS:
        return 'invalid', '쓸 수 없는 키예요.'
    if not modifiers & (CTRL | ALT | SHIFT):
        return 'invalid', 'Ctrl·Alt·Shift 중 하나 이상을 함께 눌러 주세요.'
    return 'ok', '사용할 수 있는 조합이에요.'


def valid(modifiers, vk) -> bool:
    return check(modifiers, vk)[0] == 'ok'


# 가상 키 코드 → 사용자가 아는 키 이름. 'VK 79'처럼 16진 코드로 보이면 실제 키(F10)를 알 수 없다.
_KEY_NAMES = {0x08: 'Backspace', 0x09: 'Tab', 0x0D: 'Enter', 0x13: 'Pause', 0x14: 'CapsLock',
              0x1B: 'Esc', 0x20: 'Space', 0x21: 'PageUp', 0x22: 'PageDown', 0x23: 'End',
              0x24: 'Home', 0x25: '←', 0x26: '↑', 0x27: '→', 0x28: '↓', 0x2C: 'PrintScreen',
              0x2D: 'Insert', 0x2E: 'Delete', 0x6A: 'Num *', 0x6B: 'Num +', 0x6D: 'Num -',
              0x6E: 'Num .', 0x6F: 'Num /', 0x90: 'NumLock', 0x91: 'ScrollLock', 0xBA: ';',
              0xBB: '=', 0xBC: ',', 0xBD: '-', 0xBE: '.', 0xBF: '/', 0xC0: '`', 0xDB: '[',
              0xDC: '\\', 0xDD: ']', 0xDE: "'"}


def key_name(vk):
    if 0x70 <= vk <= 0x87:
        return f'F{vk - 0x6F}'
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f'Num {vk - 0x60}'
    return _KEY_NAMES.get(vk, f'키 코드 0x{vk:02X}')


def hotkey_text(modifiers, vk):
    """RegisterHotKey 수식 마스크(Alt=1, Ctrl=2, Shift=4, Win=8)와 키 코드를 'Ctrl+Alt+F10' 형식으로."""
    keys = [name for mask, name in ((2, 'Ctrl'), (1, 'Alt'), (4, 'Shift'), (8, 'Win')) if modifiers & mask]
    return '+'.join(keys + [key_name(vk)])
