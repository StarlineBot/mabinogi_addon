"""문의 자료 회차(문의 자동 진단 명세 6.2·6.3) — 화면과 무관한 부분.

문의하기 › 문제 신고에서 카드 하나를 고르면 회차가 만들어진다. 회차는
- 무작위 회차 ID(다시 보내기는 같은 ID → 받는 쪽에서 재전송임을 안다),
- 문의 전용 임시 폴더(`<사용자 데이터>/inquiry/<회차 ID>`)에 모은 자료(PNG·자동 찾기 기록 ZIP),
- 상한(60초·20장·8MiB, 변경 프레임만·초당 1장)
을 관리하고, 보낼 때 ZIP 하나(이미지·로그·진단 요약·본문 전체·info.json)를 만든다.
보내기를 누르기 전에는 아무것도 밖으로 나가지 않는다. 성공·취소·창 닫기 때 폴더를 지우고, 비정상 종료 잔여물은
다음 시작 때 24시간 넘은 것만 지운다(기존 수동 수집 폴더는 건드리지 않음).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import io
import json
from pathlib import Path
import re
import shutil
import threading
import time
import uuid
import zipfile

import numpy as np

from . import config, image_io, paths

CATEGORIES = ("문제 신고", "기능 요청", "기타")
BUG = CATEGORIES[0]
LIMIT_SECONDS = 60
LIMIT_FRAMES = 20
LIMIT_BYTES = 8 * 1024 * 1024      # 회차 자료 합계·최종 ZIP 상한(웹훅 실제 제한은 배포 전에 확인)
MIN_INTERVAL = 1.0                  # 변경 프레임도 초당 최대 1장
COUNTDOWN = 5                       # 게임 1장: 창을 접고 이만큼 기다렸다 찍는다
STALE_SECONDS = 24 * 3600


@dataclass(frozen=True)
class Card:
    key: str
    title: str
    desc: str
    mode: str                 # collect(영역 60초) | snapshot(버프·디버프 영역 + 게임 1장) | autofind(기록 + 게임 1장) | game(게임 1장)
    regions: tuple[str, ...]  # collect·snapshot이 읽는 영역 이름(REGION_LABELS)
    ask: str                  # 자료 모으기 화면 큰 안내
    detail: str               # 그 아래 작은 안내


CARDS = (
    Card("boss", "보스 체력바 · 패턴 알림", "보스 이름·체력바를 최대 60초 모아요.", "collect", ("boss",),
         "보스 체력이 바뀌는 장면을 다시 보여 주세요",
         "게임을 맨 앞에 두고 평소처럼 플레이해 주세요. 이 창은 작게 접히고, 게임 위에 진행 표시만 떠요."),
    Card("stat", "내 체력바", "생명력·마나·스태미나 영역을 최대 60초 모아요.", "collect", ("stat",),
         "생명력·마나·스태미나가 바뀌는 장면을 보여 주세요",
         "게임을 맨 앞에 두고 평소처럼 플레이해 주세요. 이 창은 작게 접히고, 게임 위에 진행 표시만 떠요."),
    Card("dorcha", "도르카 · 투아림 숫자", "도르카·투아림 영역을 최대 60초 모아요.", "collect", ("dorcha", "tuarim"),
         "도르카·투아림 숫자가 바뀌는 장면을 보여 주세요",
         "게임을 맨 앞에 두고 평소처럼 플레이해 주세요. 이 창은 작게 접히고, 게임 위에 진행 표시만 떠요."),
    Card("buff", "버프 · 디버프", "버프·디버프 영역과 게임 화면 1장을 준비해요.", "snapshot", ("buff", "debuff"),
         "버프·디버프 창이 보이게 게임을 맨 앞에 두세요",
         "5초 뒤 버프·디버프 영역과 게임 화면 1장을 찍어요. 이 창은 그동안 접혀요."),
    Card("autofind", "자동 찾기 · 영역 지정", "최근 자동 찾기 기록과 게임 화면 1장을 준비해요.", "autofind", (),
         "찾으려던 화면이 보이게 게임을 맨 앞에 두세요",
         "최근 자동 찾기 기록을 붙이고, 5초 뒤 게임 화면 1장을 찍어요. 이 창은 그동안 접혀요."),
    Card("cooldown", "쿨타임 오버레이", "단축바 영역을 최대 60초 모아요.", "collect", ("cooldown",),
         "쿨타임이 이상한 장면을 다시 보여 주세요",
         "스킬을 쓰고 쿨이 끝날 때까지 평소처럼 플레이해 주세요. 이 창은 작게 접혀요."),
    Card("other", "그 밖의 문제 · 잘 모르겠어요", "5초 뒤 게임 화면 1장을 찍어요.", "game", (),
         "문제가 보이는 게임 화면을 맨 앞에 두세요",
         "5초 뒤 게임 화면 1장을 찍어요. 이 창은 그동안 접혀요. 애드온 표시(오버레이)는 사진에 안 나올 수 있어요."),
)
CARD_BY_KEY = {c.key: c for c in CARDS}
REGION_LABELS = {"boss": "보스 HP바", "stat": "체력바", "dorcha": "도르카", "tuarim": "투아림",
                 "buff": "버프", "debuff": "디버프", "game": "게임 화면", "cooldown": "쿨타임 칸"}
_CHANGE = {"boss": 4.0, "stat": 5.0, "dorcha": 6.0, "tuarim": 6.0, "cooldown": 4.0}  # 기존 수집 모드와 같은 영상 차이 기준
COOLDOWN_LOG_LINES = 200


def region_of(name: str) -> dict | None:
    """그 기능이 지금 읽는 자리(논리 좌표) — 자동 찾기가 찾은 자리, 못 찾았으면 저장된 영역(v1), 직접 지정 고정이면 그 영역.
    없거나 잘못됐으면 None. 설정을 바꾸지 않는다(자동 찾기를 몰래 돌리지 않음)."""
    try:
        if name == "boss":
            box = config.load_boss_bar_region()
        elif name == "stat":
            box = config.load_stat_bars().get("box")
        elif name == "dorcha":
            box = config.load_dorcha().get("box")
        elif name == "tuarim":
            box = config.load_tuarim().get("box")
        elif name in ("buff", "debuff"):
            box = config.load_capture_region("buffTracker" if name == "buff" else "debuffTracker")
        elif name == "cooldown":
            box = cooldown_region()
        else:
            return None
    except Exception:  # noqa: BLE001 — 설정이 깨졌으면 '미설정'으로
        return None
    key = {"stat": "stat_bars"}.get(name, name)
    from . import autofind_regions
    if key in autofind_regions.KEYS:
        box = autofind_regions.current_region(key, box if isinstance(box, dict) else None)
    if isinstance(box, dict) and all(isinstance(box.get(k), int) for k in ("x", "y", "w", "h")) \
            and box["w"] > 0 and box["h"] > 0:
        return {k: int(box[k]) for k in ("x", "y", "w", "h")}
    return None


def _autofind_state() -> dict:
    """자동 찾기 상태(항목별 자리·출처 last/search/v1/user·마지막 실패 이유, first-use-v3 6절 6). 실패해도 문의는 보낸다."""
    try:
        from . import autofind_regions
        return autofind_regions.snapshot()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def cooldown_region() -> dict | None:
    """쿨타임 카드 영역(논리 좌표): 등록 칸 + 두 페이지 선택기 자리(화살표 포함)를 덮는 사각형 — 쿨타임 관측과 같은 공유 캡처 범위.
    등록 칸이 없으면 위쪽 단축바 영역(단축바 미러 원본 1168×89)으로 대신."""
    from .ui.dpi import to_logical
    slots = config.load_cooldown().get("slots") or []
    rects = []
    for slot in slots:
        rect = slot.get("rect")
        if isinstance(rect, (list, tuple)) and len(rect) == 4:
            rects.append(list(rect))
        from .ui.cooldown_section import _with_arrows
        selectors = ([slot["page_rect"]] if slot.get("page_rect") else []) + list((slot.get("page_rects") or {}).values())
        rects += [_with_arrows(r) for r in selectors if isinstance(r, (list, tuple)) and len(r) == 4]
    if rects:
        x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
        x1, y1 = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
        return dict(zip(("x", "y", "w", "h"), to_logical(x0, y0, x1 - x0, y1 - y0)))  # 칸 좌표는 물리 픽셀
    anchor = config.load_skillbar().get("anchor")
    if isinstance(anchor, dict) and all(isinstance(anchor.get(k), int) for k in ("x", "y")):
        from .ui.skillbar_mirror import SRC_H, SRC_W
        return {"x": anchor["x"], "y": anchor["y"], "w": SRC_W, "h": SRC_H}
    return None


def has_cooldown_slots() -> bool:
    return bool(config.load_cooldown().get("slots"))


def attach_cooldown(session: "Session") -> None:
    """쿨타임 카드 함께 첨부: 칸 목록(페이지 서명 원문 제외)·등록 칸 아이콘 PNG·app.log '쿨타임 칸' 줄(최근 200줄 — 수집 동안 칸 상태 변화 포함)."""
    cfg = config.load_cooldown()
    slots = [{"id": s.get("id"), "label": s.get("label"), "rect": s.get("rect"), "set": s.get("set", 1), "row": s.get("row"),
              "block": s.get("block"), "page_block": s.get("page_block"), "page": bool(s.get("page")),
              "page_rects": s.get("page_rects"), "icon_ok": bool(s.get("icon_ok"))} for s in cfg.get("slots") or []]
    data = {"enabled": bool(cfg.get("enabled")), "slots": slots}
    target = session.folder / "cooldown_slots.json"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    session.add_file(target, target.name, "쿨타임 칸 목록")
    if not slots:
        session.notes.append("쿨타임: 등록한 칸이 없어요 — 위쪽 단축바 영역으로 대신 모음")
    from .ui.cooldown_section import icon_path
    for slot in slots:
        icon = icon_path(str(slot["id"]))
        if icon.exists():
            session.add_file(icon, f"cooldown_icon_{slot['id']}.png", f"쿨타임 아이콘 {slot['label']}")


BUFF_GONE_LOG_LINES = 200


def buff_gone_dir() -> Path:
    return paths.user_data_dir() / "logs" / "buff-gone"


def attach_buff_gone(session: "Session") -> None:
    """'버프 · 디버프' 문의(0.47.1): 사라짐 경고 확정 순간 버프 영역 PNG(최근 10장, 이 PC에만 있던 것)와
    app.log의 사라짐·포커스 진단 줄(최근 200줄)을 함께 붙인다."""
    try:
        pngs = sorted(buff_gone_dir().glob("*.png"))[-10:]
    except OSError:
        pngs = []
    for png in pngs:
        session.add_file(png, f"buff_gone_{png.name}", "사라짐 경고 순간 버프 영역")
    try:
        lines = _app_log().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    picked = [line for line in lines if "[사라짐" in line or "[포커스]" in line][-BUFF_GONE_LOG_LINES:]
    if picked:
        target = session.folder / "buff_gone_log.txt"
        target.write_text("\n".join(picked) + "\n", encoding="utf-8")
        session.add_file(target, target.name, "사라짐 경고 기록(app.log)")


def _app_log() -> Path:
    return paths.user_data_dir() / "logs" / "app.log"


def finish_cooldown(session: "Session") -> None:
    """수집 끝: app.log의 '쿨타임 칸' 줄(최근 200줄)을 붙인다(수집 동안의 칸 상태 변화 포함)."""
    try:
        lines = _app_log().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    picked = [line for line in lines if "쿨타임 칸" in line][-COOLDOWN_LOG_LINES:]
    target = session.folder / "cooldown_log.txt"
    target.write_text("\n".join(picked) + ("\n" if picked else ""), encoding="utf-8")
    session.add_file(target, target.name, "쿨타임 기록(app.log)")


def install_id() -> str:
    """설치 ID(처음 부를 때 무작위로 만들어 config에 보관 — 개인정보 아님). 비로그인 문의의 보낸 사람 구분."""
    data = config._read_local_config()
    value = data.get("installId")
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{16,32}", value):
        return value
    value = uuid.uuid4().hex
    data["installId"] = value
    config._write_local_config(data)
    return value


def sender(user: dict | None = None) -> dict:
    """보낸 사람 — 디스코드 로그인이면 ID·이름, 아니면 guest-설치ID앞8자."""
    from . import feature_access
    user = feature_access.current_user() if user is None else user
    iid = install_id()
    if user:
        return {"discord_id": str(user.get("id")), "discord_name": str(user.get("name") or ""), "install_id": iid,
                "label": str(user.get("name") or user.get("id"))}
    return {"discord_id": None, "discord_name": None, "install_id": iid, "label": f"guest-{iid[:8]}"}


def safe_name(text: str) -> str:
    """파일 이름에 쓸 수 없는 글자(\\ / : * ? \" < > | 제어 문자)는 _로."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", text).strip(" .")
    return cleaned[:40] or "unknown"


def zip_name(who: dict, session_id: str, when: datetime) -> str:
    return f"문의_{when:%Y%m%d-%H%M}_{safe_name(who['label'])}_{session_id[:6]}.zip"


def header_line(who: dict, session_id: str, category: str, card: Card | None) -> str:
    """디스코드 메시지 첫 줄 — ZIP을 열지 않고도 구분(보낸 사람 · 회차 ID · 문의 종류 · 카드)."""
    parts = [who["label"], f"회차 {session_id[:6]}", category]
    if card is not None:
        parts.append(card.title)
    return " · ".join(parts)


@dataclass
class Attachment:
    name: str          # ZIP 안 파일 이름
    label: str         # 썸네일 아래 이름(보스 HP바 1)
    path: Path
    size: int
    kind: str = "image"   # image | file


@dataclass
class Session:
    card: Card | None
    root: Path | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    attachments: list[Attachment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # 진단 요약에 넣을 사실(영역 미설정·게임 미발견 등)
    started: datetime | None = None
    ended: datetime | None = None
    removed: set[str] = field(default_factory=set)    # 사용자가 지운 자료(다시 자동 첨부하지 않음)

    def __post_init__(self):
        self._lock = threading.Lock()
        self._last: dict[str, np.ndarray] = {}
        self._last_at: dict[str, float] = {}
        self._counts: dict[str, int] = {}
        self.folder.mkdir(parents=True, exist_ok=True)

    @property
    def folder(self) -> Path:
        base = self.root if self.root is not None else paths.user_data_dir() / "inquiry"
        return base / self.id

    # ---- 상한·집계 ---------------------------------------------------------------------------
    @property
    def images(self) -> list[Attachment]:
        return [a for a in self.attachments if a.kind == "image"]

    @property
    def total_bytes(self) -> int:
        return sum(a.size for a in self.attachments)

    def full(self) -> bool:
        return len(self.images) >= LIMIT_FRAMES or self.total_bytes >= LIMIT_BYTES

    # ---- 자료 넣기 ---------------------------------------------------------------------------
    def add_frame(self, region: str, frame: np.ndarray, now: float | None = None, *, force: bool = False) -> Attachment | None:
        """영역 프레임 — 상한 안에서, 직전 저장과 눈에 띄게 다르고(기존 수집 모드 기준) 1초 지났을 때만 PNG로 저장.
        force=True는 한 번 찍기(버프·디버프·게임 1장). 작업 스레드에서 불러도 된다."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if self.full():
                return None
            if not force:
                if now - self._last_at.get(region, -1e9) < MIN_INTERVAL:
                    return None
                prev = self._last.get(region)
                if prev is not None and prev.shape == frame.shape:
                    diff = np.abs(frame.astype(np.int16) - prev.astype(np.int16))
                    if float(diff.mean()) < _CHANGE.get(region, 4.0):
                        return None
            number = self._counts.get(region, 0) + 1
            name = f"{region}_{number:02d}.png"
            path = self.folder / name
            if not image_io.imwrite(path, frame):
                return None
            size = path.stat().st_size
            if self.total_bytes + size > LIMIT_BYTES:
                path.unlink(missing_ok=True)
                return None
            self._counts[region] = number
            self._last[region], self._last_at[region] = frame, now
            item = Attachment(name, f"{REGION_LABELS.get(region, region)} {number}", path, size)
            self.attachments.append(item)
            return item

    def add_file(self, source: Path, name: str, label: str) -> Attachment | None:
        with self._lock:
            size = source.stat().st_size
            if self.total_bytes + size > LIMIT_BYTES:
                self.notes.append(f"{label}: 용량 상한을 넘어 빼고 보냄")
                return None
            target = self.folder / name
            if source.resolve() != target.resolve():
                shutil.copyfile(source, target)
            item = Attachment(name, label, target, size, kind="file")
            self.attachments.append(item)
            return item

    def remove(self, item: Attachment) -> None:
        with self._lock:
            if item in self.attachments:
                self.attachments.remove(item)
                self.removed.add(item.name)
                item.path.unlink(missing_ok=True)

    def clear(self) -> None:
        for item in list(self.attachments):
            self.remove(item)

    # ---- 보내기 -----------------------------------------------------------------------------
    def info(self, *, category: str, who: dict, title: str) -> dict:
        from .version import display_version
        return {
            "session_id": self.id, "install_id": who["install_id"], "discord_id": who["discord_id"],
            "discord_name": who["discord_name"], "app_version": display_version(), "category": category,
            "card": self.card.key if self.card else None, "card_title": self.card.title if self.card else None,
            "title": title,
            "collect_started": self.started.isoformat(timespec="seconds") if self.started else None,
            "collect_ended": self.ended.isoformat(timespec="seconds") if self.ended else None,
            "notes": list(self.notes),
            "attachments": [{"name": a.name, "label": a.label, "bytes": a.size, "kind": a.kind} for a in self.attachments],
            "autofind": _autofind_state(),
        }

    def build_zip(self, *, category: str, who: dict, title: str, content: str, logs: str,
                  when: datetime | None = None) -> tuple[str, bytes]:
        """(ZIP 이름, 바이트). 이미지·기록은 이미 압축돼 있어 STORED, 글은 DEFLATED. 8MiB를 넘으면 ValueError."""
        when = when or datetime.now()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            info = self.info(category=category, who=who, title=title)
            archive.writestr("info.json", json.dumps(info, ensure_ascii=False, indent=2))
            archive.writestr("본문.txt", f"{header_line(who, self.id, category, self.card)}\n\n제목: {title}\n\n{content}\n")
            archive.writestr("logs.txt", logs)
            for item in self.attachments:
                archive.write(item.path, item.name, compress_type=zipfile.ZIP_STORED)
        data = buffer.getvalue()
        if len(data) > LIMIT_BYTES:
            raise ValueError("자료가 8MB를 넘어요 — 사진을 몇 장 지워 주세요")
        return zip_name(who, self.id, when), data

    def cleanup(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)


def cleanup_stale(root: Path | None = None, *, now: float | None = None, max_age: float = STALE_SECONDS) -> int:
    """비정상 종료로 남은 문의 임시 폴더 중 max_age 넘은 것만 지운다(문의 폴더 밖은 건드리지 않음)."""
    root = root if root is not None else paths.user_data_dir() / "inquiry"
    now = time.time() if now is None else now
    removed = 0
    try:
        children = list(root.iterdir())
    except OSError:
        return 0
    for child in children:
        if child.is_dir() and re.fullmatch(r"[0-9a-f]{32}", child.name):
            try:
                if now - child.stat().st_mtime > max_age:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
    return removed


def grab_region(box: dict) -> np.ndarray | None:
    """저장된 영역(논리 좌표)을 지금 찍는다(mss, 스레드마다 새로 — 1초 1번이라 충분히 가볍다)."""
    from .ui.dpi import to_physical
    x, y, w, h = to_physical(box)
    return grab_physical((x, y, w, h))


def grab_physical(rect) -> np.ndarray | None:
    x, y, w, h = rect
    try:
        import mss
        with mss.mss() as sct:
            shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
        return np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[:, :, :3].copy()
    except Exception:  # noqa: BLE001 — 캡처 불가 → 이번 장 건너뜀
        return None
