"""Local alpha eligibility; ordinary Discord login does not grant alpha access."""

from . import config

CREATOR_DISCORD_ID = "280290004926857216"


def blackbox_available() -> bool:
    """블랙박스(0.16.0 베타): 디스코드 로그인 사용자. 다른 베타 기능과 같은 판정(로그인 여부)."""
    user = config.load_discord_user()
    return isinstance(user, dict) and bool(user.get("id"))


def optimization_available() -> bool:
    """최적화(13.15, 2026-10-25 사용자 결정): 블랙박스와 같은 판정 — 디스코드 로그인 사용자. FPS 수집 모드는 제작자만(is_creator)."""
    return blackbox_available()


def is_creator() -> bool:
    user = config.load_discord_user()
    return (isinstance(CREATOR_DISCORD_ID, str) and CREATOR_DISCORD_ID.isdecimal()
            and isinstance(user, dict) and user.get("id") == CREATOR_DISCORD_ID)


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
