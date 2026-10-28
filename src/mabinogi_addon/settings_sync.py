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
    payload_bytes: bytes,
    *,
    filename: str = "섯다라인_설정.zip",
    username: str | None = None,
    timeout: float = 5.0,
    urlopen=urllib.request.urlopen,
) -> None:
    """설정 백업(zip 바이트)을 릴레이 웹훅에 첨부로 전송. 실패 시 예외.

    설정 JSON만으론 커스텀 버프 아이콘 등 자산이 빠지므로, 설정+자산을 묶은
    zip 번들을 보낸다. 섯다라인 봇이 멘션을 보고 작성자에게 DM으로 relay한다.
    """
    if not webhook_url:
        raise ValueError("설정 백업 채널(웹훅)이 설정되지 않았습니다")
    if not user_id:
        raise ValueError("디스코드 로그인이 필요합니다")
    if len(payload_bytes) > BACKUP_UPLOAD_BUDGET:
        raise ValueError('앱의 전송 크기 한도를 넘었어요. 파일로 저장해 주세요.')
    payload: dict = {"content": f"[설정백업] <@{user_id}>"}
    if username:
        payload["username"] = username[:80]
    # 웹훅 멀티파트 전송(User-Agent·상태확인 포함)은 inquiry._post 재사용.
    inquiry._post(
        webhook_url,
        payload,
        (filename, payload_bytes),
        timeout,
        urlopen,
    )


# Application upload budget, not a claim about every Discord/guild attachment limit.
# Keep source and ZIP below this budget before compression/transport. Server 413 is
# still authoritative; callers can change the budget when transport policy changes.
BACKUP_UPLOAD_BUDGET = 8 * 1024 * 1024


def send_config_backup_file(webhook_url, user_id, path, *, filename='섯다라인_설정.zip',
                            username=None, timeout=5.0, cancelled=None,
                            upload_budget=BACKUP_UPLOAD_BUDGET, urlopen=urllib.request.urlopen):
    """Stream a bounded disk multipart request; relay acceptance is not DM delivery."""
    import json
    import tempfile
    import uuid
    import urllib.error
    from pathlib import Path
    from .config import BundleCancelled
    if not webhook_url or not user_id: raise ValueError('설정 백업 채널과 디스코드 로그인이 필요해요.')
    path = Path(path)
    if path.stat().st_size > upload_budget: raise ValueError('앱의 전송 크기 한도를 넘었어요. 파일로 저장해 주세요.')
    boundary = '----mabi' + uuid.uuid4().hex
    payload = {'content': f'[설정백업] <@{user_id}>'}
    if username: payload['username'] = username[:80]
    def check():
        if cancelled and cancelled(): raise BundleCancelled('설정 내보내기를 취소했어요.')
    check()
    with tempfile.TemporaryFile() as body:
        body.write((f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
                    'Content-Type: application/json\r\n\r\n').encode())
        body.write(json.dumps(payload).encode())
        body.write((f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; '
                    f'filename="{filename}"\r\nContent-Type: application/zip\r\n\r\n').encode())
        count = 0
        with path.open('rb') as source:
            while chunk := source.read(64*1024):
                check()
                count += len(chunk)
                if count > upload_budget: raise ValueError('앱의 전송 크기 한도를 넘었어요.')
                body.write(chunk)
        body.write(f'\r\n--{boundary}--\r\n'.encode())
        length = body.tell()
        body.seek(0)
        check()
        request = urllib.request.Request(webhook_url, data=body, method='POST', headers={
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(length), 'User-Agent': inquiry._USER_AGENT,
        })
        try:
            with urlopen(request, timeout=timeout) as response:
                status = getattr(response, 'status', None)
                if status is not None and status not in (200,204):
                    raise ValueError(f'설정 백업 릴레이 응답 오류 ({status})')
        except urllib.error.HTTPError as exc:
            if exc.code == 413:
                raise ValueError('서버의 첨부 크기 한도를 넘었어요. 파일로 저장해 주세요.') from None
            raise ValueError(f'설정 백업 릴레이 응답 오류 ({exc.code})') from None
        except (urllib.error.URLError, OSError):
            raise ValueError('설정 백업 릴레이에 연결하지 못했어요.') from None
