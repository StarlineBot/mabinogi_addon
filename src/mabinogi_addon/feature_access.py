"""기능 접근 판정. 2026-10-28부터 사용 기능은 모두 공개, 수집·진단만 로그인·제작자 제한(기능 공개 정책 7절).
로그인·등급은 0.46.0부터 서버가 서명한 토큰으로(계정 관리 명세 3.2) — current_user·is_logged_in·tier·is_creator."""

from . import config

CREATOR_DISCORD_ID = "280290004926857216"


def blackbox_available() -> bool:
    """블랙박스: 모든 사용자(2026-10-28 기능 공개 정책 7절 — 사용 기능은 로그인 없이 공개). 호출부 호환용으로 남긴다."""
    return True


def optimization_available() -> bool:
    """게임 최적화: 모든 사용자(기능 공개 정책 7절). FPS 수집 모드는 제작자만(is_creator)."""
    return True


def cursor_fx_available() -> bool:
    """마우스 커서 표시: 모든 사용자(0.37.0 사용자 결정 — 기능 공개 정책 7절과 같음. 0.36.x는 제작자만). 호출부 호환용으로 남긴다."""
    return True


# ---- 등급 판정(계정 관리 명세 3.2) — 앱 안 로그인·제작자 판정은 모두 여기로 모은다 ----
def current_user() -> dict | None:
    """로그인 사용자 {id, name, tier} 또는 None. 서버가 서명한 토큰으로만(config.load_discord_user)."""
    user = config.load_discord_user()
    return user if isinstance(user, dict) and user.get("id") else None


def is_logged_in() -> bool:
    return current_user() is not None


def tier() -> str | None:
    """'user' · 'creator' · None(비로그인)."""
    user = current_user()
    return None if user is None else (user.get("tier") or "user")


def is_creator() -> bool:
    """제작자 = **토큰 등급**이 creator. config.json에 제작자 ID를 적어도 제작자가 아니다(서명 없는 값은 로그인도 아님).
    CREATOR_DISCORD_ID는 화면 표시(제작자 캐릭터 등)에만 남긴다."""
    return tier() == "creator"


class Recheck:
    """권한 판정을 interval초 동안 재사용한다(0.17.2). 판정은 config.json을 읽고 해석하므로, 프레임·루프마다 부르면
    그 자체가 CPU를 쓴다(FPS 줄 분당 2만 개 중 95%가 설정 읽기였음). 로그인 변경(login_changed)에는 invalidate()로
    바로 다시 확인하고, 그 밖의 변경(설정 파일 교체 등)은 interval 안에 반영된다.

    check는 부를 때마다 이름으로 찾는 lambda로 넘겨 테스트의 함수 교체가 그대로 적용되게 한다.
    INTERVAL은 기본 재사용 시간이다(기존 기능 테스트는 conftest에서 0으로 두고, 캐시 동작은 전용 테스트가 확인)."""

    INTERVAL = 1.0

    def __init__(self, check, interval=None, clock=None):
        import time
        self._check, self._interval = check, interval
        self._clock = clock or time.monotonic
        self._value, self._at = None, None

    def __call__(self):
        now = self._clock()
        interval = Recheck.INTERVAL if self._interval is None else self._interval
        if self._at is None or now - self._at >= interval or now < self._at:
            self._value, self._at = self._check(), now
        return self._value

    def invalidate(self):
        self._at = None
