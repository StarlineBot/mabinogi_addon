"""앱 색 이름 8가지(안내·도움말 명세 14절 6항, 0.29.0).

화면마다 값을 직접 적어 생긴 비슷한 색들을 이름으로 모은다. 화면 코드는 값 대신 이름만 쓴다
(다음 차수 강조색 개인화의 기반). 값은 그 시점의 테마(다크/라이트)로 고른다.

대상 밖: 배경·일반 글자(Windows 시스템 색), 홈 전용 남색 배경·상자, 게임 위 오버레이 색, 메모 글씨 강조색.
홈은 테마와 관계없이 어두운 디자인이라 color(name, dark=True)로 다크 값을 쓴다.

모듈을 불러오는 시점에는 테마가 아직 정해지지 않았으므로, 모듈·클래스 상수로 값을 굳히지 말고
쓰는 순간 color()를 부르거나 Named(이름 표)를 쓴다.
"""
from __future__ import annotations

# 이름: (다크, 라이트)
COLORS = {
    "accent": ("#00C9A2", "#00A884"),       # 1단 탭·밑줄, 잠금됨, 스위치, 링크
    "on-accent": ("#062F28", "#FFFFFF"),    # 민트 버튼 안 글자
    "accent-soft": ("#8FDCCC", "#1F8A7A"),  # 2단 탭 선택 글자
    "muted": ("#8A8F98", "#6B7280"),        # 안내 문구, 선택 안 된 탭, 꺼짐·대기
    "ok": ("#2ECC71", "#1E9E57"),           # 켜짐·추적 중 점
    "warn": ("#E67E22", "#C2610F"),         # 영역 지정 필요, 경고 상자
    "danger": ("#E5534B", "#C0392B"),       # 일시정지, 삭제·초기화
    "brand": ("#3A0729", "#3A0729"),        # 제작자 캐릭터 테두리
}
# 2단 탭 밑줄(명세 14.1 목업 값 — 이름 표에는 글자색만)
SUBTAB_UNDERLINE = ("#3F8F82", "#8FCFC4")


# 테마 개인화(테마 개인화 명세 5절): 개인화 중이면 theme_colors.compute 결과를 쓴다. None이면 다크/라이트 값.
_custom: dict | None = None


def set_custom(result: dict | None) -> None:
    global _custom
    _custom = result


def custom() -> dict | None:
    return _custom


def _dark(dark):
    if dark is not None:
        return bool(dark)
    from .theme import is_dark
    return is_dark()


def _use_custom(dark) -> bool:
    # 개인화 중이면 내용 칸 톤과 같은 쪽을 물을 때(또는 묻지 않을 때) 개인화 값
    return _custom is not None and (dark is None or bool(dark) == (_custom["tone"] == "dark"))


def color(name: str, dark: bool | None = None) -> str:
    """이름의 색 값. dark를 주지 않으면 지금 적용 중인 테마로(개인화 중이면 개인화 값)."""
    if _use_custom(dark):
        return _custom["names"][name]
    pair = COLORS[name]
    return pair[0] if _dark(dark) else pair[1]


def subtab_underline(dark: bool | None = None) -> str:
    if _use_custom(dark):
        return _custom["subtab_underline"]
    return SUBTAB_UNDERLINE[0] if _dark(dark) else SUBTAB_UNDERLINE[1]


def on_frame(value: str) -> str:
    """틀(머리줄·1단 탭 줄) 위에 쓰는 색: 개인화 중이면 그 색 이름의 틀 대비 조정값, 아니면 그대로."""
    if _custom is None:
        return value
    for name, current in _custom["names"].items():
        if current.upper() == str(value).upper() and name in _custom["on_frame"]:
            return _custom["on_frame"][name]
    return value


def snapshot() -> dict:
    """지금 이름 색 값(다시 칠하기 전후 비교용)."""
    return {name: color(name) for name in COLORS}


def restyle(before: dict, after: dict, widgets) -> int:
    """이름 색을 쓰는 화면 전체를 다시 칠한다(테마 개인화 명세 6절 — 재시작 없이 즉시).

    화면 코드는 만들 때 color()로 값을 스타일시트·서식 글자에 넣어 두므로, 바뀐 이름의 옛 값을 새 값으로 바꿔 끼운다.
    이름 값은 서로 겹치지 않는다(theme_colors._unique). 강조 위 글자(흰색일 수 있음)는 강조 바탕이 함께 있는 스타일에서만 바꾼다.
    """
    import re
    changes = {before[n].upper(): after[n] for n in before if before[n].upper() != after[n].upper() and n != "on-accent"}
    on_accent = (before["on-accent"].upper(), after["on-accent"]) if before["on-accent"].upper() != after["on-accent"].upper() else None
    accent_old = before["accent"].upper()
    if not changes and on_accent is None:
        return 0
    keys = list(changes) + ([on_accent[0]] if on_accent else [])
    pattern = re.compile("|".join(re.escape(k) for k in sorted(set(keys), key=len, reverse=True)), re.I)

    def swap(text):
        has_accent = accent_old in text.upper()

        def one(match):
            key = match.group(0).upper()
            if on_accent and key == on_accent[0] and key not in changes:
                return on_accent[1] if has_accent else match.group(0)
            return changes.get(key, match.group(0))
        return pattern.sub(one, text)

    count = 0
    from PySide6.QtWidgets import QLabel
    for widget in widgets:
        sheet = widget.styleSheet()
        if sheet and pattern.search(sheet):
            widget.setStyleSheet(swap(sheet))
            count += 1
        if isinstance(widget, QLabel):
            text = widget.text()
            if "style=" in text and pattern.search(text):
                widget.setText(swap(text))
                count += 1
    return count


class Named:
    """키 → 색 이름 표. 꺼낼 때 지금 테마 값으로 바꿔 준다(모듈 상수로 값이 굳지 않게)."""

    def __init__(self, names: dict):
        self._names = dict(names)

    def __getitem__(self, key):
        return color(self._names[key])

    def get(self, key, default=None):
        return color(self._names[key]) if key in self._names else default

    def __contains__(self, key):
        return key in self._names

    def keys(self):
        return self._names.keys()
