"""자동 찾기 v2 — 화면 스레드 쪽 진행(제작자 테스트판, docs/autofind-v2-creator-spec.md 3절).

- 화면 스레드는 0.5초마다 상태만 본다(게임 창 바뀜·앞에 있음·할 일 고르기). 캡처·탐지는 전부 작업 스레드 하나(16ms 넘는 화면 스레드 일 0).
- 한 번에 한 작업만. 결과는 세대 번호로 늦은 것을 버린다.
- 찾은 자리는 autofind_regions(런타임 영역)와 config autofindV2.last에만 — 저장 영역은 읽지도 덮지도 않는다.
"""
from __future__ import annotations

import logging
import time

import numpy as np
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from .. import autofind_regions, autofind_v2 as v2, config

_log = logging.getLogger(__name__)
TICK_MS = 500
UI_CHECK_KEYS = ("skillbar", "stat_bars")


# ---- 작업 스레드 부품 ---------------------------------------------------------------------------
class NativeCapture:
    """작업 스레드 하나가 만들고 닫는 mss(스레드 사이 공유 불가)."""

    def __init__(self):
        self.sct = None

    def grab(self, x, y, w, h):
        import numpy as np
        try:
            if self.sct is None:
                import mss
                self.sct = mss.mss()
            shot = self.sct.grab(dict(left=int(x), top=int(y), width=int(w), height=int(h)))
            return np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[:, :, :3].copy()
        except Exception:  # noqa: BLE001 — 캡처 불가 → 이번 작업 건너뜀
            return None

    def close(self):
        sct, self.sct = self.sct, None
        if sct is not None:
            try:
                sct.close()
            except Exception:  # noqa: BLE001
                pass


class Finders:
    """탐지기 묶음(작업 스레드). 템플릿은 처음 한 번만 읽는다."""

    def __init__(self):
        self._assets = {}

    def _run(self, feature, frame, trace=None):
        from ..autofind_replay import detector_assets, run_detector
        if feature not in self._assets:
            self._assets[feature] = detector_assets(feature)
        return run_detector(feature, frame, self._assets[feature], {} if trace is None else trace)

    def finders(self) -> dict:
        def resources(frame):
            trace = {}
            self._run("resources", frame, trace)
            return {k: tuple(v) for k, v in (trace.get("regions") or {}).items()}
        return {"skillbar": lambda f: self._run("skillbar", f), "stat_bars": lambda f: self._run("stat_bars", f),
                "buff": lambda f: self._widen_buff(f, self._run("buff", f)), "resources": resources,
                "boss": lambda f: self._run("boss", f), "halo_timer": lambda f: self._run("halo_timer", f)}

    @staticmethod
    def _widen_buff(frame, box):
        if box is None:
            return None
        try:
            from ..detect.favorites import widen_to_favorites
            return tuple(widen_to_favorites(frame, box))  # 즐겨찾기 칸 포함
        except Exception:  # noqa: BLE001
            return tuple(box)

    def readers(self) -> dict:
        """지난 자리 확인(그 자리만 잘라 판독)."""
        def dorcha(crop):
            from ..detect.dorcha_reader import read_dorcha
            return read_dorcha(crop) is not None

        def tuarim(crop):
            from ..detect.tuarim_reader import read_observation
            return read_observation(crop) is not None

        def halo(crop):
            from ..detect.halo_timer import read_seconds
            return read_seconds(crop, max_seconds=3600) is not None

        def boss(crop):
            from ..detect.boss_bar import make_validator
            return bool(make_validator()(crop))

        def buff(crop):
            return self._run("buff", crop) is not None

        def fixed(feature):
            return lambda crop: self._run(feature, crop) is not None
        return {"dorcha": dorcha, "tuarim": tuarim, "halo_timer": halo, "boss": boss, "buff": buff,
                "skillbar": fixed("skillbar"), "stat_bars": fixed("stat_bars")}


def expected_crop(key, target):
    """나타나면 찾기 — 예상 자리(물리 좌표). 보스바: 가로 가운데·아래에서 약 190~263px, 전투 시간: 가운데 위(해상도별)."""
    _, _, x, y, w, h = target
    if key == "boss":
        top = h - (263 if h <= 1080 else 193) - 45
        return x + w // 2 - 340, y + max(0, top), 680, min(150, h - max(0, top))
    top = (146 if h <= 1080 else 173 if h >= 2000 else 136) - 35
    return x + w // 2 - 140, y + top, 280, 110


def find_expected(key, frame):
    if key == "boss":
        import numpy as np
        from ..detect.boss_bar import locate_boss_bar, make_validator
        h = frame.shape[0]
        padded = np.concatenate((np.zeros((3 * h, frame.shape[1], 3), dtype=frame.dtype), frame))  # 아래쪽 탐색 범위에 들게
        box = locate_boss_bar(padded, make_validator())
        return None if box is None else (box[0], box[1] - 3 * h, box[2], box[3])
    from ..detect.halo_timer import cells, read_seconds
    found = []
    for _, (x, y, w, h) in cells(frame):
        x0, y0 = max(0, x - 4), max(0, y - 4)
        roi = frame[y0:y + h + 4, x0:x + w + 4]
        if read_seconds(roi, max_seconds=3600) is not None:
            found.append((x0, y0, roi.shape[1], roi.shape[0]))
    return found[0] if len(found) == 1 else None


def debuff_from_boss(box):
    """보스바 위 디버프 줄(디버프 영역 = 띠 + 바) — 탭 자동 찾기와 같은 규칙."""
    x, y, w, h = box
    top = max(0, y - int(h * 1.4))
    return (x, top, w, y + h - top)


# ---- 진행 ---------------------------------------------------------------------------------------
class AutofindV2Controller(QObject):
    changed = Signal()  # 상태가 바뀜(설정 구역 표시 갱신)

    def __init__(self, watcher, wanted=None, *, target_fn=None, paused_fn=None, parent=None,
                 executor=None, capture=None, finders=None, clock=time.monotonic):
        super().__init__(parent)
        self.engine = v2.Engine()
        self._watcher = watcher
        self._wanted = wanted or (lambda key: True)
        self._target_fn = target_fn or _registered_target
        self._paused_fn = paused_fn or (lambda: False)
        self._executor = executor  # 테스트: 바로 실행하는 가짜
        self._capture = capture or NativeCapture()
        self._finders = finders or Finders()
        self._clock = clock
        self.target = None
        self.future = None
        self.job = None
        self.closed = False
        self._frame_seq = 0
        self._waiting_ui = False
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._safe_tick)
        autofind_regions.set_reporter(self.note_read)
        autofind_regions.subscribe(self._on_region_event)

    def _on_region_event(self, key, user) -> None:
        """탭에서 직접 지정·자동 찾기 → 이번 실행 동안 그 항목은 엔진이 손대지 않는다."""
        if user and key in self.engine.items:
            self.engine.user_override(key)
            self.changed.emit()

    def start(self) -> None:
        self.engine.reset(self._clock())
        self.timer.start()
        _log.info("[자동 찾기 v2] 켜짐 — 저장 영역 대신 이번 실행에서 찾은 자리로 읽어요")

    def restart(self) -> None:
        """'지금 다시 찾기' — 처음 찾기를 한 차례 다시."""
        self.engine.reset(self._clock())
        self._publish()
        self.changed.emit()

    def shutdown(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        autofind_regions.set_reporter(None)
        if self._executor is not None and not getattr(self._executor, "inline", False):
            self._executor.submit(self._capture.close)  # 작업 스레드의 mss는 그 스레드에서 닫는다
            self._executor.shutdown(wait=False)

    # ---- 화면 스레드 틱 -----------------------------------------------------------------------
    def _safe_tick(self) -> None:
        try:
            self.tick()
        except Exception:  # noqa: BLE001 — 틱 격리(앱 생존 우선)
            _log.exception("[자동 찾기 v2] 상태 갱신 실패")

    def tick(self) -> None:
        if self.closed:
            return
        now = self._clock()
        target = self._target_fn(self.target)
        if self._target_changed(target):
            if self.target is not None:
                _log.info("[자동 찾기 v2] 게임 창이 바뀌어 처음 찾기를 다시 해요(%s → %s)",
                          _size(self.target), _size(target))
            self.target = target
            self.engine.reset(now)
            self.future = self.job = None  # 진행 결과는 세대 번호로 버려진다
            self._publish()
            self.changed.emit()
        running = bool(target and self._watcher.is_game_active() and not self._paused_fn())
        self.engine.tick(now, running)
        if not running:
            return
        if self.future is not None:
            if not self.future.done():
                return
            future, job = self.future, self.job
            self.future = self.job = None
            try:
                result = future.result()
            except Exception:  # noqa: BLE001
                _log.exception("[자동 찾기 v2] 작업 실패")
                return
            self._accept(job, result, now)
            return
        if self.engine.ready_for_initial(now):
            self._start_initial()
            return
        due = self.engine.due(now, self._wanted)
        if due:
            group = "resources" if due[0] in v2.RESOURCE_KEYS else due[0]
            keys = [k for k in v2.RESOURCE_KEYS if k in due] if group == "resources" else [group]
            self._start_research(group, keys)
            return
        appear = self.engine.appear_due(now, self._wanted)
        if appear:
            keys, mode = appear
            self._start_appear(keys, mode)

    def _target_changed(self, target) -> bool:
        if target is None or self.target is None:
            return target is not self.target and (target is None) != (self.target is None)
        return tuple(target[:2]) != tuple(self.target[:2]) or tuple(target[4:]) != tuple(self.target[4:])

    def _submit(self, job, work) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="autofind-v2")
        job["generation"] = self.engine.generation
        job["target"] = self.target
        self.job = job
        self.future = self._executor.submit(work)

    # ---- 처음 찾기 ---------------------------------------------------------------------------
    def _start_initial(self) -> None:
        target = self.target
        last = self._last_boxes(target)
        finders, readers, capture = self._finders.finders(), self._finders.readers(), self._capture
        self.engine.begin_initial()
        self.changed.emit()

        def work():
            _, _, x, y, w, h = target
            frame = capture.grab(x, y, w, h)
            if frame is None:
                return {"capture_failed": True}
            # 게임 UI가 보이는지 가벼운 확인(단축바·체력바 하나라도) — 로딩·로그인·캐릭터 선택 화면이면 처음 찾기를 미룬다.
            # 지난 자리가 있어도 늘 확인(게임 재시작 뒤 로딩 화면에서 처음 찾기 → 못 찾음 → 1분 간격에 걸리던 것, QA 7b629b2).
            # 지난 자리가 있는 항목은 그 자리만 잘라 읽어 보고(수 ms), 없으면 탐지기.
            # 지난 자리가 있는 항목은 그 둘레에 여유(max(32px, 높이))를 두고 탐지기로 — 딱 맞게 자르면 탐지기가 못 찾았다
            # (72824a8 회귀: 1440에서 단축바·체력바 모두 False → '게임 화면을 기다리는 중' 고착, QA 92e9ca1).
            # 여유 자리에서 못 찾으면 전체 화면 탐지기로 한 번 더(10초에 한 번).
            early, seen = {}, False
            fh, fw = frame.shape[:2]
            for key in UI_CHECK_KEYS:
                if key not in last:
                    continue
                bx, by, bw, bh = last[key]
                m = max(32, bh)
                x0, y0 = max(0, bx - x - m), max(0, by - y - m)
                x1, y1 = min(fw, bx - x + bw + m), min(fh, by - y + bh + m)
                try:
                    if x1 > x0 and y1 > y0 and finders[key](np.ascontiguousarray(frame[y0:y1, x0:x1])):
                        seen = True
                        break
                except Exception:  # noqa: BLE001
                    pass
            if not seen:
                for key in UI_CHECK_KEYS:
                    try:
                        early[key] = finders[key](frame)
                    except Exception:  # noqa: BLE001
                        early[key] = None
                    if early[key]:
                        seen = True
                        break
            if not seen:
                return {"not_ready": True}
            reuse = dict(finders)
            for key, box in early.items():
                reuse[key] = (lambda b: (lambda f: b))(box)  # 이미 본 결과 재사용(같은 화면)
            local_last = {k: (b[0] - x, b[1] - y, b[2], b[3]) for k, b in last.items()}
            result = v2.run_initial(frame, reuse, last=local_last, readers=readers)
            result.boxes = {k: (b[0] + x, b[1] + y, b[2], b[3]) for k, b in result.boxes.items()}  # 화면(물리) 좌표로
            return {"result": result}
        self._submit({"kind": "initial"}, work)

    def _last_boxes(self, target) -> dict:
        """autofindV2.last 중 같은 게임 창 크기에서 찾은 자리(물리 좌표)."""
        from .dpi import to_physical
        raw = config._read_local_config().get("autofindV2")
        last = (raw or {}).get("last") if isinstance(raw, dict) else None
        out = {}
        for key, entry in (last or {}).items():
            if key not in v2.KEYS or not isinstance(entry, dict) or entry.get("size") != list(target[4:]):
                continue
            box = entry.get("box")
            if isinstance(box, dict) and all(type(box.get(k)) is int for k in ("x", "y", "w", "h")):
                out[key] = tuple(to_physical(box))
        return out

    # ---- 다시 찾기·나타나면 찾기 --------------------------------------------------------------
    def _start_research(self, group: str, keys: list) -> None:
        target = self.target
        finders, capture = self._finders.finders(), self._capture
        gen = self.engine.start_search(keys)
        _log.info("[자동 찾기 v2] 다시 찾기: %s", "·".join(v2.NAMES[k] for k in keys))
        self.changed.emit()

        def work():
            _, _, x, y, w, h = target
            frame = capture.grab(x, y, w, h)
            if frame is None:
                return {"capture_failed": True}
            found = finders[group](frame)
            if group == "resources":
                found = found or {}
                boxes = {k: found.get(k) for k in keys}
            else:
                boxes = {group: found}
            return {"boxes": {k: (None if b is None else (b[0] + x, b[1] + y, b[2], b[3])) for k, b in boxes.items()}}
        self._submit({"kind": "research", "keys": keys, "search_generation": gen}, work)

    def _start_appear(self, keys: list, mode: str) -> None:
        target = self.target
        finders, capture = self._finders.finders(), self._capture

        def work():
            out = {}
            for key in keys:
                if mode == "small":
                    rx, ry, rw, rh = expected_crop(key, target)
                else:
                    rx, ry, rw, rh = target[2:]
                frame = capture.grab(rx, ry, rw, rh)
                if frame is None:
                    continue
                box = find_expected(key, frame) if mode == "small" else finders[key](frame)
                out[key] = None if box is None else (box[0] + rx, box[1] + ry, box[2], box[3])
            return {"boxes": out}
        self._submit({"kind": "appear", "keys": keys, "mode": mode}, work)

    # ---- 결과 반영(화면 스레드) ---------------------------------------------------------------
    def _accept(self, job, result, now) -> None:
        if job.get("generation") != self.engine.generation or job.get("target") != self.target:
            return  # 늦은 결과(창 바뀜·다시 찾기)
        if result.get("capture_failed"):
            if job["kind"] == "initial":
                self.engine.reset(now)  # 다음 틱에 다시
            return
        if job["kind"] == "initial":
            if result.get("not_ready"):
                self.engine.ui_not_ready(now)
                if not self._waiting_ui:  # 기다리기 시작할 때 한 줄(10초마다 반복하지 않음)
                    _log.info("[자동 찾기 v2] UI 아직 안 보임 — 기다림(로딩·로그인·캐릭터 선택 화면, 10초마다 다시 확인, 실패로 세지 않음)")
                self._waiting_ui = True
            else:
                res = result["result"]
                if self._waiting_ui:
                    _log.info("[자동 찾기 v2] 게임 UI가 보여요 — 처음 찾기를 해요")
                self._waiting_ui = False
                self.engine.finish_initial(job["generation"], res, now)  # 실패 횟수 0·다음 시도는 10초 뒤부터(1분 간격에 걸려 있지 않음)
                parts = " · ".join(f"{v2.NAMES[k]} {self.engine.items[k].label()}({res.seconds.get(k, 0):.1f}초)"
                                   for k in v2.KEYS)
                _log.info("[자동 찾기 v2] %s — %s", self.engine.initial_summary, parts)
                self._save_last()
        elif job["kind"] == "research":
            for key in job["keys"]:
                box = result["boxes"].get(key)
                self.engine.search_result(job["search_generation"], key, box, now)
                if box is None:
                    _log.info("[자동 찾기 v2] 다시 찾기 못 찾음: %s(실패 %d번)", v2.NAMES[key], self.engine.items[key].failures)
        elif job["kind"] == "appear":
            for key, box in result["boxes"].items():
                before = self.engine.items[key].box
                outcome = None if box is None else self.engine.appear_result(job["generation"], key, box)
                if outcome == "found":
                    _log.info("[자동 찾기 v2] 나타나서 찾음: %s(%s)", v2.NAMES[key], "예상 자리" if job["mode"] == "small" else "화면 전체")
                elif outcome == "confirmed_last":
                    _log.info("[자동 찾기 v2] 지난 자리 확인됨: %s %s(화면 전체 확인)", v2.NAMES[key], self.engine.items[key].box)
                elif outcome == "moved":
                    _log.info("[자동 찾기 v2] 자리 바뀜: %s %s → %s(화면 전체 확인 — 게임 UI 배율 변경 등)",
                              v2.NAMES[key], before, self.engine.items[key].box)
                if outcome:
                    self._save_last()
        self._publish()
        self.changed.emit()

    def note_read(self, key: str, ok: bool, frame_id=None) -> None:
        """기능의 판독 결과(autofind_regions.report) — 확정·실패만 기록하고 표시 갱신."""
        if self.closed:
            return
        if frame_id is None:
            self._frame_seq += 1
            frame_id = self._frame_seq
        outcome = self.engine.note_read(key, ok, self._clock(), frame_id)
        if outcome == "confirmed":
            _log.info("[자동 찾기 v2] 새 자리 확정: %s %s", v2.NAMES.get(key, key), self.engine.items[key].box)
            self._save_last()
        elif outcome == "confirmed_last":
            _log.info("[자동 찾기 v2] 지난 자리 확인됨: %s %s(그 자리에서 읽힘)", v2.NAMES.get(key, key), self.engine.items[key].box)
            self._save_last()
        elif outcome == "failed":
            _log.info("[자동 찾기 v2] 새 자리에서 읽히지 않아 버림: %s", v2.NAMES.get(key, key))
        if outcome:
            self._publish()
            self.changed.emit()

    def _publish(self) -> None:
        """엔진의 자리 → 런타임 영역(논리 좌표). 단축바는 {x, y}, 디버프는 보스바 위 띠."""
        from .dpi import to_logical
        for key in v2.KEYS:
            box = self.engine.region(key)
            logical = None if box is None else dict(zip(("x", "y", "w", "h"), to_logical(*box)))
            if key == "skillbar" and logical is not None:
                logical = {"x": logical["x"], "y": logical["y"]}
            autofind_regions.set_region(key, logical)
            if key == "boss":
                debuff = None if box is None else dict(zip(("x", "y", "w", "h"), to_logical(*debuff_from_boss(box))))
                autofind_regions.set_region("debuff", debuff)

    def _save_last(self) -> None:
        """찾은 자리를 다음 실행 첫 확인 후보로만 기록(autofindV2.last) — 저장 영역은 안 건드림."""
        from datetime import datetime, timezone

        from .dpi import to_logical
        if self.target is None:
            return
        raw = config._read_local_config()
        sec = dict(raw.get("autofindV2") or {})
        last = dict(sec.get("last") or {})
        for key, it in self.engine.items.items():
            if it.status == v2.FOUND and it.box is not None and not it.user:
                last[key] = {"box": dict(zip(("x", "y", "w", "h"), to_logical(*it.box))),
                             "size": list(self.target[4:]), "at": datetime.now(timezone.utc).isoformat()}
        sec["last"] = last
        raw["autofindV2"] = sec
        try:
            config._write_local_config(raw)
        except OSError:
            _log.warning("[자동 찾기 v2] 지난 자리 기록 실패", exc_info=True)


def _size(target):
    return "없음" if target is None else f"{target[4]}×{target[5]}"


def _registered_target(previous=None):
    from ..system.window_capture import registered_game_target
    return registered_game_target(previous)
