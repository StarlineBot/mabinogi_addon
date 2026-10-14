"""실행별 자동찾기 입력 보존, 제한된 백그라운드 저장, 무손실 ZIP 내보내기."""

from __future__ import annotations

from concurrent.futures import Future
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
from queue import Queue, Full
import re
import shutil
import threading
from uuid import uuid4
from zipfile import ZipFile, ZIP_STORED

import numpy as np

from . import config, image_io, logbuffer, paths, version

capture_info: ContextVar[dict | None] = ContextVar("autofind_capture_info", default=None)
_log = logging.getLogger(__name__)
_SECRET = re.compile(r"token|webhook|password|secret|api.?key|authorization|credential|cookie", re.I)
_URL = re.compile(r"https?://[^\s\"'<>]+", re.I)
_CREDENTIAL = re.compile(r"((?:token|password|secret|api[_-]?key|authorization)\s*[:=]\s*)(?:Bearer\s+)?[^\s,;]+", re.I)
MAX_RUNS = 20
MAX_DISK_BYTES = 256 * 1024 * 1024
MAX_MEMORY_BYTES = 128 * 1024 * 1024


def _secret_values(value) -> list[str]:
    out = []
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET.search(str(key)) and isinstance(item, str) and item:
                out.append(item)
            else:
                out.extend(_secret_values(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_secret_values(item))
    return out


def sanitize(value, secrets: list[str] = ()):
    if isinstance(value, dict):
        return {str(k): sanitize(v, secrets) for k, v in value.items() if not _SECRET.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, secrets) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, str):
        for secret in sorted(set(secrets), key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = _URL.sub("[URL REDACTED]", value)
        return _CREDENTIAL.sub(r"\1[REDACTED]", value)
    return value


class BackgroundIO:
    """대기 작업 수가 제한된 단일 daemon 워커. Qt 객체에는 접근하지 않는다."""

    def __init__(self):
        self._queue = Queue(maxsize=3)
        self._thread = threading.Thread(target=self._work, name="diagnostic-io", daemon=True)
        self._thread.start()

    def submit(self, fn, *args) -> Future:
        future = Future()
        try:
            self._queue.put_nowait((future, fn, args))
        except Full:
            future.set_exception(RuntimeError("진단 저장 대기열이 가득 찼습니다. 잠시 후 다시 시도하세요."))
        return future

    def _work(self):
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                future, fn, args = item
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(fn(*args))
                    except Exception as exc:
                        future.set_exception(exc)
            finally:
                self._queue.task_done()
                item = future = fn = args = None

    def wait(self):
        self._queue.join()

    def close(self):
        self._queue.put(None)
        self._thread.join()


@dataclass
class RunRecord:
    metadata: dict
    frame: np.ndarray | None = None
    assets: dict[str, np.ndarray] = field(default_factory=dict)
    logs: str = ""
    directory: Path | None = None
    storage_error: str = ""
    pending: bool = True
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def id(self):
        return self.metadata["run_id"]

    @property
    def memory_bytes(self):
        return (0 if self.frame is None else self.frame.nbytes) + sum(a.nbytes for a in self.assets.values())


class DiagnosticStore:
    def __init__(self, root: Path | None = None, *, max_runs=MAX_RUNS,
                 max_bytes=MAX_DISK_BYTES, max_memory=MAX_MEMORY_BYTES):
        self.root = root
        self.max_runs, self.max_bytes, self.max_memory = max_runs, max_bytes, max_memory
        self.io = BackgroundIO()
        self._records: dict[str, RunRecord] = {}
        self._lock = threading.RLock()

    def _root(self):
        return self.root if self.root is not None else paths.user_data_dir() / "autofind_diagnostics"

    def add(self, record: RunRecord, *, copy_input: bool = True):
        with self._lock:
            # 원본은 재캡처하지 않는다. 상한 초과 시 메타데이터에 누락 원인을 남긴다.
            used = sum(r.memory_bytes for r in self._records.values())
            if record.memory_bytes + used > self.max_memory:
                record.frame, record.assets = None, {}
                record.metadata["input_error"] = "진단 메모리 상한 초과: 원본 이미지 보관 불가"
            elif copy_input:
                record.frame = None if record.frame is None else record.frame.copy()
                record.assets = {k: v.copy() for k, v in record.assets.items()}
            self._records[record.id] = record
            self._trim_memory()
        future = self.io.submit(self._persist, record)
        if future.done() and future.exception() is not None:
            record.pending = False
            record.storage_error = str(future.exception())
            with self._lock:
                self._trim_memory()

    def _trim_memory(self):
        removable = sorted((r for r in self._records.values() if not r.pending), key=lambda r: r.id)
        while len(self._records) > self.max_runs and removable:
            old = removable.pop(0)
            if old.frame is not None or old.assets:
                old.metadata = {**old.metadata, "input_error": "보관 개수 상한으로 메모리 원본이 삭제되었습니다"}
            old.frame, old.assets = None, {}
            self._records.pop(old.id, None)

    def recent(self) -> list[RunRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda r: r.id, reverse=True)

    def refresh(self):
        root = self._root()
        if root.exists():
            for folder in sorted(root.iterdir(), reverse=True):
                if not folder.is_dir():
                    continue
                if folder.name.startswith("."):
                    shutil.rmtree(folder, ignore_errors=True)
                    continue
                try:
                    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
                    if (not isinstance(metadata, dict) or metadata.get("schema") != 1
                            or metadata.get("run_id") != folder.name
                            or not isinstance(metadata.get("started_at"), str)
                            or not isinstance(metadata.get("feature"), str)
                            or not isinstance(metadata.get("success"), bool)
                            or "failure_stage" not in metadata):
                        continue
                    datetime.fromisoformat(metadata["started_at"])
                    with self._lock:
                        self._records.setdefault(folder.name, RunRecord(metadata, directory=folder, pending=False))
                except (OSError, ValueError, KeyError, TypeError):
                    continue
            self._prune(root)
        return self.recent()

    def _write(self, record: RunRecord, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        metadata = deepcopy(record.metadata)
        files, errors = {}, []
        images = dict(record.assets)
        if record.frame is not None:
            images["input"] = record.frame
        for name, frame in images.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
                errors.append("진단 이미지 이름 오류")
                continue
            filename = f"{name}.png"
            try:
                if not image_io.imwrite(folder / filename, frame):
                    raise OSError("PNG 인코딩/쓰기 실패")
                files[filename] = hashlib.sha256((folder / filename).read_bytes()).hexdigest()
            except Exception as exc:
                errors.append(f"{filename}: {type(exc).__name__}: {exc}")
                (folder / filename).unlink(missing_ok=True)
        metadata["files_sha256"] = files
        metadata["image_errors"] = sanitize(errors)
        metadata["storage_error"] = sanitize(record.storage_error)
        (folder / "logs.txt").write_text(record.logs, encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata

    def _persist(self, record):
        staging = None
        try:
            root = self._root()
            staging = root / ("." + record.id)
            with record.lock:
                metadata = self._write(record, staging)
                destination = root / record.id
                staging.replace(destination)
                record.metadata, record.directory = metadata, destination
                record.frame, record.assets = None, {}
            self._prune(root)
        except Exception as exc:
            record.storage_error = sanitize(f"{type(exc).__name__}: {exc}")
            _log.warning("자동찾기 진단 저장 실패: %s", record.storage_error)
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            record.pending = False
            with self._lock:
                self._trim_memory()

    def _prune(self, root):
        folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        sizes = {p: sum(f.stat().st_size for f in p.iterdir() if f.is_file()) for p in folders}
        total = sum(sizes.values())
        keep = sorted(folders, reverse=True)
        while keep and (len(keep) > self.max_runs or total > self.max_bytes):
            old = keep.pop()
            shutil.rmtree(old)
            total -= sizes[old]
            with self._lock:
                self._records.pop(old.name, None)
        with self._lock:
            self._trim_memory()

    def export(self, record: RunRecord, destination: Path) -> Path:
        """같은 워커에서 기록 저장 다음에 호출. ZIP은 임시 파일 후 원자적으로 교체."""
        from tempfile import TemporaryDirectory

        tmp = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
        try:
            with record.lock, TemporaryDirectory(prefix="autofind-export-") as scratch:
                folder = record.directory
                if folder is None or not folder.exists():
                    if record.frame is None and "input.png" in record.metadata.get("files_sha256", {}):
                        raise FileNotFoundError("선택한 기록이 보관 상한으로 삭제되었습니다. 목록을 새로 고침하세요.")
                    folder = Path(scratch)
                    self._write(record, folder)
                metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
                names = ["metadata.json", "logs.txt"]
                for name, digest in metadata.get("files_sha256", {}).items():
                    if not re.fullmatch(r"[a-zA-Z0-9_-]+\.png", name):
                        raise ValueError("진단 PNG 파일명 오류")
                    if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
                        raise ValueError(f"원본 PNG 무결성 검사 실패: {name}")
                    names.append(name)
                if destination.resolve() in {(folder / name).resolve() for name in names}:
                    raise ValueError("원본 진단 파일을 ZIP으로 덮어쓸 수 없습니다")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with ZipFile(tmp, "w", ZIP_STORED) as archive:
                    for name in sorted(names):
                        archive.write(folder / name, name)
                tmp.replace(destination)
            return destination
        finally:
            tmp.unlink(missing_ok=True)


_store: DiagnosticStore | None = None
_store_lock = threading.Lock()


def store() -> DiagnosticStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = DiagnosticStore()
    return _store


def perform_autofind(feature: str, capture, *, detect=None, assets=None, descriptor=None, storage=None):
    """캡처 1회 + 그 입력으로 검출 + 실행별 진단. 새 검출기도 이 경로를 사용한다."""
    from .autofind_replay import detector_assets, run_detector

    logbuffer.install()
    started = datetime.now(timezone.utc)
    run = started.strftime("%Y%m%dT%H%M%S%fZ_") + uuid4().hex[:8]
    metadata = {"schema": 1, "run_id": run, "feature": feature, "started_at": started.isoformat(),
                "app_version": version.__version__, "platform": platform.platform(),
                "success": False, "failure_stage": "capture", "capture": {},
                "detector": deepcopy(descriptor) if descriptor else {"id": feature}, "result": None}
    secrets = []
    try:
        raw = config._read_local_config()
        secrets = _secret_values(raw) + [v for k, v in os.environ.items() if _SECRET.search(k) and v]
        related = ("buffTracker", "debuffTracker", "tuarim", "bossPattern", "statBars", "skillbar", "general")
        metadata["settings"] = sanitize({k: raw[k] for k in related if k in raw}, secrets)
    except Exception as exc:
        metadata["settings_error"] = sanitize(str(exc), secrets)
    before = logbuffer.recent_logs(12000, exclude_runs=True)
    token = logbuffer.run_id.set(run)
    capture_token = capture_info.set(metadata["capture"])
    frame = None
    original = None
    ox = oy = 0
    box = None
    saved_assets = {}
    original_assets = {}
    try:
        _log.info("자동찾기 시작 feature=%s run=%s", feature, run)
        frame, ox, oy = capture()
        metadata["capture"]["offset_physical"] = [ox, oy]
        if frame is not None:
            try:
                if frame.nbytes <= MAX_MEMORY_BYTES:
                    original = frame.copy()
                else:
                    metadata["input_error"] = "원본 프레임이 진단 메모리 상한을 초과합니다"
            except Exception as exc:
                metadata["input_error"] = f"원본 보관 실패: {type(exc).__name__}: {exc}"
            metadata["input"] = {"shape": list(frame.shape), "dtype": str(frame.dtype),
                                 "color_order": "BGR", "region": [0, 0, frame.shape[1], frame.shape[0]]}
            metadata["failure_stage"] = "detector_setup"
            saved_assets = detector_assets(feature) if assets is None else assets
            metadata["asset_names"] = list(saved_assets)
            try:
                original_assets = {k: v.copy() for k, v in saved_assets.items()}
            except Exception as exc:
                metadata["asset_error"] = f"템플릿 보관 실패: {type(exc).__name__}: {exc}"
            metadata["failure_stage"] = "detect"
            trace = {}
            metadata["detector"]["trace"] = trace
            box = run_detector(feature, frame, saved_assets, trace) if detect is None else detect(frame, trace, saved_assets)
            metadata["result"] = None if box is None else list(box)
            if box is not None:
                metadata["result_global_physical"] = [box[0] + ox, box[1] + oy, box[2], box[3]]
            metadata["success"] = box is not None
            metadata["failure_stage"] = None if box is not None else "detect"
        else:
            metadata["error"] = "캡처 백엔드가 이미지를 반환하지 않았습니다"
    except Exception as exc:
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        _log.exception("자동찾기 실행 실패")
    finally:
        metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
        _log.info("자동찾기 종료 success=%s stage=%s", metadata["success"], metadata["failure_stage"])
        logs = ("=== CONTEXT BEFORE (non-autofind) ===\n" + before
                + "\n=== THIS RUN ===\n" + logbuffer.recent_logs(scope=run)
                + "\n=== CONTEXT AFTER (non-autofind) ===\n" + logbuffer.recent_logs(12000, exclude_runs=True))
        capture_info.reset(capture_token)
        logbuffer.run_id.reset(token)
        record = RunRecord(sanitize(metadata, secrets), original, original_assets, sanitize(logs, secrets))
        try:
            (storage or store()).add(record, copy_input=False)
        except Exception:
            _log.exception("자동찾기 진단 대기열 등록 실패")
    return frame, ox, oy, box
