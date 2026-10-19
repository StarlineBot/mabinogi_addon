"""Local alpha eligibility; ordinary Discord login does not grant alpha access."""

from . import config

CREATOR_DISCORD_ID = "280290004926857216"


def is_creator() -> bool:
    user = config.load_discord_user()
    return (isinstance(CREATOR_DISCORD_ID, str) and CREATOR_DISCORD_ID.isdecimal()
            and isinstance(user, dict) and user.get("id") == CREATOR_DISCORD_ID)
