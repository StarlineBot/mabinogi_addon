"""계정(서버) 일 — 토큰 새로 받기·로그아웃 알림·설정 동기화(계정 관리 명세 3.2·3.3).

코드 → 런타임 동작 → 시스템 영향:
- 네트워크·압축·파일 일은 모두 작업 스레드 하나(ThreadPoolExecutor)에서 — 화면 스레드는 신호만 받는다(16ms 규칙, 커서 꼬리 끊김 방지).
- **비로그인이면 아무것도 보내지 않는다**(시작·저장·종료 모두 로그인 확인 먼저).
- 토큰: 시작할 때 + 켜진 동안 하루 1번 `/me`로 새 토큰. 서버가 꺼져 있으면 마지막 확인 뒤 7일 유지(account), 401·403이면 비로그인.
- 동기화: 설정 파일이 바뀌면(config 쓰기 알림) 30초 뒤 한 번(연달아 바꾸면 마지막 것만) + 앱을 끌 때 한 번 올림.
  올리기 전에 '빼는 값을 뺀 내용 지문'을 비교해 그대로면 보내지 않는다.
- 시작할 때: 이 PC에 동기화 기록이 없고 서버에 설정이 있으면(새 PC·재설치) 물음, 서버가 더 새것이면 받아 오고,
  둘 다 바뀌었거나 올리다 409(충돌)면 같은 물음 → `불러오기` / `이 PC 설정 쓰기`.
- 받아 적용한 설정은 앱을 다시 켜야 전부 반영된다(가져오기와 같음) — `applied` 신호로 안내.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from .. import account, cloud_sync, config, feature_access

_log = logging.getLogger("mabinogi_addon.account")

DEBOUNCE_MS = 30_000
REFRESH_CHECK_MS = 60 * 60 * 1000  # 1시간마다 '하루 지났나' 확인(자는 동안 놓친 갱신도 깨어나면 바로)
FLUSH_TIMEOUT = 5.0  # 종료 때 올리기 최대 대기(초)


class AccountController(QObject):
    changed = Signal()                # 로그인·동기화 상태가 바뀜(설정 › 계정 표시 갱신)
    ask = Signal(dict, str)           # (서버 설정 정보, 이유 'new_pc'|'both_changed'|'conflict') → 물음
    applied = Signal(bool)            # 서버 설정을 적용함(위치까지 적용했나) → 다시 켜기 안내
    logged_out = Signal()             # 서버가 토큰을 거절해 비로그인으로
    _wrote = Signal()                 # 설정 파일 쓰기(어느 스레드든) → 화면 스레드에서 30초 모으기
    _done = Signal(object)            # 작업 결과 → 화면 스레드

    def __init__(self, parent=None, *, client_factory=None, executor=None, clock=time.time,
                 resolution_fn=None, app_version: str = "") -> None:
        super().__init__(parent)
        self._client = client_factory or (lambda token: account.Client(token))
        self._executor = executor
        self._clock = clock
        self._resolution_fn = resolution_fn or _screen_resolution
        self._resolution = ""
        self._app_version = app_version
        self._pending_ask = None
        self.closed = False
        self.started = False
        self.busy = False
        self.last_error = ""
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self.upload_now)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_CHECK_MS)
        self._refresh_timer.timeout.connect(self._maybe_refresh)
        self._wrote.connect(self._schedule)
        self._done.connect(self._on_done)
        self._last_refresh = None

    # ---- 시작·끝 -------------------------------------------------------------------------------
    def start(self) -> None:
        """앱 시작(또는 로그인 직후). 비로그인이면 통신 0회."""
        if self.started or self.closed:
            return
        self.started = True
        self._resolution = self._resolution_fn() or ""
        config.add_write_listener(self._on_write)
        self._refresh_timer.start()
        if self._token() is None:
            return
        self._submit("refresh", self._job_refresh)
        if self.sync_enabled():
            self._submit("startup", self._job_startup)

    def shutdown(self, *, flush: bool = True) -> None:
        """앱 종료: 바뀐 설정이 있으면 한 번 올리고(최대 FLUSH_TIMEOUT초), 작업 스레드를 닫는다."""
        if self.closed:
            return
        self.closed = True
        config.remove_write_listener(self._on_write)
        self._debounce.stop()
        self._refresh_timer.stop()
        if flush and self._token() is not None and self.sync_enabled():
            future = self._executor_or_new().submit(self._job_upload, None, False)
            try:
                future.result(timeout=FLUSH_TIMEOUT)
            except Exception:  # noqa: BLE001 — 끄는 중: 실패는 다음 실행 때 다시
                _log.warning("[동기화] 종료 때 올리기 실패", exc_info=True)
        if self._executor is not None and not getattr(self._executor, "inline", False):
            self._executor.shutdown(wait=False)

    # ---- 상태 ---------------------------------------------------------------------------------
    def _token(self) -> str | None:
        if not feature_access.is_logged_in():
            return None
        return config.load_account_token()

    def sync_enabled(self) -> bool:
        return cloud_sync.enabled(config._read_local_config())

    def set_sync_enabled(self, on: bool) -> None:
        cloud_sync.save_record(enabled=bool(on))
        if on:
            self._schedule()
        self.changed.emit()

    def last_sync(self) -> float | None:
        at = cloud_sync.record(config._read_local_config()).get("at")
        return at if isinstance(at, (int, float)) else None

    # ---- 로그인·로그아웃 -------------------------------------------------------------------------
    def logged_in(self, token: str) -> None:
        """로그인 직후(토큰 서명 확인됨): 저장하고 동기화를 시작."""
        config.save_account_token(token, now=self._clock())
        self.changed.emit()
        if self.sync_enabled():
            self._submit("startup", self._job_startup)

    def logout(self) -> None:
        """토큰을 지우고 서버에 한 번 알린다(실패해도 로그아웃은 됨)."""
        token = config.load_account_token()
        config.clear_discord_user()
        self._debounce.stop()
        if token:
            self._submit("logout", lambda: self._client(token).logout())
        self.changed.emit()

    # ---- 바뀜 → 30초 모으기 ----------------------------------------------------------------------
    def _on_write(self, path) -> None:
        if path == config.LOCAL_CONFIG_PATH:
            self._wrote.emit()  # 어느 스레드에서 불려도 화면 스레드로(Qt 대기열)

    def _schedule(self) -> None:
        if self.closed or self._token() is None or not self.sync_enabled():
            return
        self._debounce.start()  # 다시 시작 = 마지막 변경 뒤 30초

    def upload_now(self) -> None:
        if self.closed or self._token() is None or not self.sync_enabled():
            return
        self._submit("upload", lambda: self._job_upload(None, False))

    # ---- 물음 답 ---------------------------------------------------------------------------------
    def resolve(self, choice: str) -> None:
        """'load' = 서버 설정 불러오기, 'keep' = 이 PC 설정으로 서버를 덮기."""
        info, self._pending_ask = self._pending_ask, None
        if info is None or self._token() is None:
            return
        if choice == "load":
            self._submit("download", lambda: self._job_download(info))
        else:
            self._submit("upload", lambda: self._job_upload(info.get("rev"), True))

    # ---- 작업(작업 스레드) ------------------------------------------------------------------------
    def _executor_or_new(self):
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="account")
        return self._executor

    def _submit(self, kind: str, fn) -> None:
        if self.closed:
            return
        self.busy = True

        def run():
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 — 결과로 넘겨 화면 스레드에서 처리
                result = exc
            self._done.emit((kind, result))
        future = self._executor_or_new().submit(run)
        if getattr(self._executor, "inline", False):
            future.result()

    def _job_refresh(self):
        token = config.load_account_token()
        if not token:
            return None
        try:
            new = self._client(token).me()
        except account.AuthError:
            config.clear_discord_user()
            return "logged_out"
        except account.ServerError as exc:
            _log.info("[계정] 서버 확인 못 함(유예 7일 안이면 로그인 유지): %s", exc)
            return None
        if account.verify_token(new) is None:
            _log.warning("[계정] /me 새 토큰 서명 확인 실패 — 지난 토큰 유지")
            return None
        config.save_account_token(new, now=self._clock())
        return "refreshed"

    def _job_startup(self):
        token = config.load_account_token()
        client = self._client(token)
        try:
            info = client.settings_info()
        except account.NotFound:
            info = None
        raw, digest = cloud_sync.local_state()
        rec = cloud_sync.record(raw)
        if info is None:
            return self._job_upload(0, True)
        if not isinstance(rec.get("rev"), int):
            return ("ask", info, "new_pc")
        if info["rev"] == rec["rev"]:
            return self._job_upload(rec["rev"], False) if digest != rec.get("hash") else ("same", info)
        if info["rev"] > rec["rev"]:
            return self._job_download(info) if digest == rec.get("hash") else ("ask", info, "both_changed")
        return self._job_upload(rec["rev"], False)

    def _job_upload(self, rev, force: bool):
        token = config.load_account_token()
        if not token or not feature_access.is_logged_in():
            return None
        raw, digest = cloud_sync.local_state()
        rec = cloud_sync.record(raw)
        if not force and digest == rec.get("hash") and isinstance(rec.get("rev"), int):
            return ("same", None)
        base_rev = rev if rev is not None else rec.get("rev", 0)
        blob, digest = cloud_sync.build_blob(resolution=self._resolution, device=cloud_sync.device_name(),
                                             app_version=self._app_version)
        try:
            info = self._client(token).put_settings(blob, rev=int(base_rev or 0), device=cloud_sync.device_name(),
                                                    resolution=self._resolution)
        except account.Conflict as exc:
            # 409 본문은 {detail, rev}뿐 — 물음에 '마지막 저장: 날짜 · PC'를 보이려고 한 번 더 읽는다(실패하면 rev만)
            info = dict(exc.info)
            try:
                info.update(self._client(token).settings_info())
            except (account.ServerError, account.NotFound):
                pass
            return ("ask", info, "conflict")
        cloud_sync.save_record(rev=info["rev"], hash=digest, at=self._clock(), device=cloud_sync.device_name())
        return ("uploaded", info)

    def _job_download(self, info):
        token = config.load_account_token()
        blob = self._client(token).settings_blob()
        same = cloud_sync.apply_blob(blob, resolution=self._resolution)
        _raw, digest = cloud_sync.local_state()
        cloud_sync.save_record(rev=info.get("rev"), hash=digest, at=self._clock())
        return ("downloaded", same)

    # ---- 결과(화면 스레드) -------------------------------------------------------------------------
    def _on_done(self, payload) -> None:
        kind, result = payload
        self.busy = False
        if isinstance(result, account.AuthError):
            config.clear_discord_user()
            result = "logged_out"
        if isinstance(result, Exception):
            self.last_error = str(result) if not isinstance(result, account.ServerError) else "서버에 연결하지 못했어요"
            _log.warning("[동기화] %s 실패: %r", kind, result)
            self.changed.emit()
            return
        self.last_error = ""
        if kind == "refresh":
            self._last_refresh = self._clock()
        if result == "logged_out":
            _log.info("[계정] 서버가 토큰을 거절 — 비로그인으로")
            self.logged_out.emit()
        elif isinstance(result, tuple) and result[0] == "ask":
            self._pending_ask = result[1] or {}
            self.ask.emit(dict(self._pending_ask), result[2])
        elif isinstance(result, tuple) and result[0] == "downloaded":
            _log.info("[동기화] 서버 설정을 받아 적용(위치 %s)", "적용" if result[1] else "이 PC 유지(해상도 다름)")
            self.applied.emit(bool(result[1]))
        elif isinstance(result, tuple) and result[0] == "uploaded":
            _log.info("[동기화] 올림 rev %s", (result[1] or {}).get("rev"))
        self.changed.emit()

    def _maybe_refresh(self) -> None:
        if self.closed or self._token() is None:
            return
        if self._last_refresh is None or self._clock() - self._last_refresh >= account.REFRESH_SECONDS:
            self._submit("refresh", self._job_refresh)


def _screen_resolution() -> str:
    """주 화면 물리 해상도 '가로x세로' — 오버레이 위치를 같은 해상도에서만 적용하는 기준."""
    try:
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return ""
        size, ratio = screen.geometry().size(), screen.devicePixelRatio() or 1.0
        return f"{round(size.width() * ratio)}x{round(size.height() * ratio)}"
    except Exception:  # noqa: BLE001
        return ""
