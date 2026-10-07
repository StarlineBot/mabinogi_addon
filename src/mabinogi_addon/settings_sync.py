"""설정 백업을 디스코드로 내보내기 (DM 릴레이).

로그인한 사용자의 설정(JSON)을 '설정 릴레이' 웹훅 채널에 첨부파일로 올린다.
섯다라인 봇이 그 메시지의 멘션(user_id)을 보고 첨부 설정 파일을 작성자에게 DM한다.
→ DM이라 사용자마다 사생활이 보장되고(남의 설정 안 보임), 봇이 유일한 '읽기' 주체.

앱은 디스코드를 읽을 수 없으므로(봇 토큰 없음) '가져오기'는 DM으로 받은 파일을
'설정 가져오기(파일)'로 적용한다.
"""

from __future__ import annotations

import urllib.request

from . import inquiry


def send_config_backup(
    webhook_url: str,
    user_id: str,
    config_json: str,
    *,
    username: str | None = None,
    timeout: float = 5.0,
    urlopen=urllib.request.urlopen,
) -> None:
    """설정 JSON을 릴레이 웹훅에 config.json 첨부로 전송. 실패 시 예외."""
    if not webhook_url:
        raise ValueError("설정 백업 채널(웹훅)이 설정되지 않았습니다")
    if not user_id:
        raise ValueError("디스코드 로그인이 필요합니다")
    payload: dict = {"content": f"[설정백업] <@{user_id}>"}
    if username:
        payload["username"] = username[:80]
    # 웹훅 멀티파트 전송(User-Agent·상태확인 포함)은 inquiry._post 재사용.
    inquiry._post(
        webhook_url,
        payload,
        ("config.json", config_json.encode("utf-8")),
        timeout,
        urlopen,
    )
