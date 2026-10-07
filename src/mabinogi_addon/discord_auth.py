"""Discord 로그인 (OAuth2 Implicit Grant).

애드온 사용자가 Discord로 로그인해 자신의 user_id를 앱에 넘긴다 → 문의 글에 그
user_id가 실려, 제작자가 디스코드에서 답하면 봇이 그 사용자에게 DM으로 전달한다.

Implicit grant(response_type=token)를 쓰므로 **client secret이 필요 없다**(배포 앱에
비밀을 넣지 않는다). 토큰은 리다이렉트 URL의 fragment(#...)로 와서 서버가 직접 못
읽으므로, 콜백 페이지의 작은 JS가 fragment를 질의문자열로 바꿔 로컬 서버에 되돌린다.

로그인 흐름 전체가 사용자 PC(localhost)에서 일어난다. 네트워크 호출(사용자 조회)이
있으므로 UI 스레드가 아니라 백그라운드 스레드에서 login()을 호출한다.
"""

from __future__ import annotations

import http.server
import json
import secrets
import socketserver
import threading
import urllib.parse
import urllib.request
import webbrowser

# 공개값(비밀 아님). 포털 OAuth2 → Redirects에 REDIRECT_URI를 '똑같이' 등록해야 한다.
CLIENT_ID = "1172437289339727913"
PORT = 53123
REDIRECT_URI = f"http://localhost:{PORT}/callback"

AUTH_BASE = "https://discord.com/api/oauth2/authorize"
USER_URL = "https://discord.com/api/users/@me"

# 로그인 성공 시 브라우저에 보여줄 페이지(라이트/다크 모두 대응하는 카드).
_SUCCESS_BODY = """
<title>로그인 완료</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center;
    justify-content:center; padding:24px;
    background:#1e1f24; color:#eef0f4;
    font-family:'Malgun Gothic','Apple SD Gothic Neo',system-ui,sans-serif; }
  .card { width:100%; max-width:360px; background:#26272e;
    border:1px solid #33343c; border-radius:16px; padding:40px 36px;
    text-align:center; box-shadow:0 10px 34px rgba(0,0,0,.4); }
  .check { width:66px; height:66px; border-radius:50%; background:#00B894;
    display:flex; align-items:center; justify-content:center;
    margin:0 auto 22px; font-size:36px; line-height:1; color:#fff; }
  h1 { margin:0 0 10px; font-size:22px; font-weight:700; }
  p { margin:0; color:#a7acb6; font-size:15px; line-height:1.55; }
  .app { margin-top:24px; font-size:13px; color:#6f7580; }
</style>
<div class="card">
  <div class="check">&#10003;</div>
  <h1>로그인 완료</h1>
  <p>디스코드 계정이 연결되었습니다.<br>이 창을 닫고 앱으로 돌아가세요.</p>
  <div class="app">섯다라인 마비노기 애드온</div>
</div>
"""


def authorize_url(state: str) -> str:
    """Discord 인증 페이지 URL(implicit: 토큰을 fragment로 돌려줌)."""
    query = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "token",
            "scope": "identify",
            "state": state,
        }
    )
    return f"{AUTH_BASE}?{query}"


def fetch_user(
    access_token: str, *, urlopen=urllib.request.urlopen, timeout: float = 5.0
) -> tuple[str, str]:
    """액세스 토큰으로 내 (user_id, 표시이름) 조회."""
    req = urllib.request.Request(
        USER_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            # Discord API는 User-Agent를 요구(없으면 Cloudflare 403).
            "User-Agent": (
                "mabinogi-addon "
                "(https://github.com/StarlineBot/mabinogi_addon, 1.0)"
            ),
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    uid = str(data.get("id", ""))
    name = data.get("global_name") or data.get("username") or uid
    return uid, name


def login(*, open_browser=webbrowser.open, timeout: float = 120.0):
    """브라우저로 Discord 로그인 → (user_id, 이름). 실패/취소 시 None.

    로컬 루프백 서버를 잠깐 띄워 콜백을 받고, 사용자 조회까지 마친 뒤 닫는다.
    """
    state = secrets.token_urlsafe(16)
    captured: dict[str, str | None] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # 서버 로그 끔
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                # fragment(#access_token=...)는 서버가 못 보므로 JS로 질의문자열화해 재요청.
                self._send(
                    "<script>location.replace('/token?'"
                    "+location.hash.substring(1))</script>"
                )
            elif parsed.path == "/token":
                params = urllib.parse.parse_qs(parsed.query)
                captured["access_token"] = (params.get("access_token") or [None])[0]
                captured["state"] = (params.get("state") or [None])[0]
                self._send(_SUCCESS_BODY)
                done.set()
            else:
                self.send_response(404)
                self.end_headers()

        def _send(self, body: str):
            data = f"<!doctype html><meta charset=utf-8>{body}".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    server.timeout = 1.0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        open_browser(authorize_url(state))
        if not done.wait(timeout):
            return None  # 시간 초과(사용자가 승인 안 함)
        token = captured.get("access_token")
        if not token or captured.get("state") != state:
            return None  # 토큰 없음/상태 불일치(변조 방지)
        return fetch_user(token)
    finally:
        server.shutdown()
        server.server_close()
