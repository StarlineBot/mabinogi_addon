"""Local alpha eligibility; ordinary Discord login does not grant alpha access."""

from . import config

CREATOR_DISCORD_ID = "280290004926857216"


def blackbox_available() -> bool:
    """블랙박스(0.16.0 베타): 디스코드 로그인 사용자. 다른 베타 기능과 같은 판정(로그인 여부)."""
    user = config.load_discord_user()
    return isinstance(user, dict) and bool(user.get("id"))


def is_creator() -> bool:
    user = config.load_discord_user()
    return (isinstance(CREATOR_DISCORD_ID, str) and CREATOR_DISCORD_ID.isdecimal()
            and isinstance(user, dict) and user.get("id") == CREATOR_DISCORD_ID)
