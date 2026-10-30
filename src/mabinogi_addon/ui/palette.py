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


def _dark(dark):
    if dark is not None:
        return bool(dark)
    from .theme import is_dark
    return is_dark()


def color(name: str, dark: bool | None = None) -> str:
    """이름의 색 값. dark를 주지 않으면 지금 적용 중인 테마로."""
    pair = COLORS[name]
    return pair[0] if _dark(dark) else pair[1]


def subtab_underline(dark: bool | None = None) -> str:
    return SUBTAB_UNDERLINE[0] if _dark(dark) else SUBTAB_UNDERLINE[1]


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
