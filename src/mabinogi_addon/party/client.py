"""넥슨 거뿔 API 클라이언트.

GET https://open.api.nexon.com/mabinogi/v1/horn-bugle-world/history?server_name=하프
헤더: x-nxopen-api-key: {키}
표준 라이브러리 urllib만 사용(의존성 추가 없음).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

API_BASE = "https://open.api.nexon.com"
HORN_BUGLE_PATH = "/mabinogi/v1/horn-bugle-world/history"
DEFAULT_SERVER = "하프"
# 선택 가능한 서버(현황판 상단 콤보에 노출). 기본은 하프.
SERVERS = ("하프", "류트", "만돌린", "울프")


def fetch_horn_bugle(
    api_key: str,
    server_name: str = DEFAULT_SERVER,
    *,
    timeout: float = 3.0,
    urlopen=urllib.request.urlopen,
) -> list[dict]:
    """거뿔 외침 기록을 반환. 응답의 horn_bugle_world_history 배열.

    urlopen은 테스트에서 가짜로 주입할 수 있다.
    """
    query = urllib.parse.urlencode({"server_name": server_name})
    url = f"{API_BASE}{HORN_BUGLE_PATH}?{query}"
    req = urllib.request.Request(url, headers={"x-nxopen-api-key": api_key})
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("horn_bugle_world_history", []) or []
