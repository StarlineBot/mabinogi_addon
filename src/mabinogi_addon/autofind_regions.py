"""자동 찾기 — 런타임 영역 제공자(docs/autofind-v2-creator-spec.md 2절, docs/first-use-v3-spec.md 4.1·6절).

각 탭이 영역을 읽는 한 곳. 0.45.0부터 모든 사용자에게 항상 켬(숨은 비상 값 config `autofind.disabled`면 꺼짐 = 저장 영역 그대로).
켜져 있으면 쓰는 순서(6절 v1 대비책):
  1. 직접 지정 고정 — 기능 화면에서 직접 지정·탭 자동 찾기를 하면 그 기능은 저장 영역(v1)이 1순위(다음 실행에도, `자동으로 돌아가기`로 해제)
  2. 자동으로 찾은 자리(지난 자리·화면 전체 찾기 — 찾기 엔진이 set_region)
  3. 못 찾음 → 저장 영역(v1)이 있으면 그 자리('저장된 영역 사용 · 자동으로 못 찾음'). 엔진은 계속 찾고, 찾아 3초 확인되면 2로
  4. 없으면 None(그 기능은 쉰다)
저장된 영역은 읽기만 하고 덮지 않는다.

공유 영역: 보스바 = 보스 패턴·디버프(보스 확인)·보스바 오버레이·체력바 보스전 알림이 같은 'boss' 하나를 쓴다 — 고정도 하나.
디버프 줄은 따로 고정할 수 있고, 고정 안 했으면 자동 보스바에서 계산(보스바만 고정했으면 고정한 보스바에서 계산).

영역은 저장 영역과 같은 논리 좌표 dict {x, y, w, h}(단축바는 {x, y}). 모든 호출은 화면 스레드.
"""
from __future__ import annotations

KEYS = ("buff", "debuff", "boss", "halo_timer", "stat_bars", "skillbar", "dorcha", "tuarim")
# 사용 값(2.1절) — v2 켜짐일 때만: 영역과 별개로 '이 기능을 쓰나'. 꺼지면 영역은 두고 읽기·알림·오버레이 멈춤(영역 None).
USE_KEYS = ("buff", "debuff", "boss", "halo_timer", "skillbar", "stat_bars")  # 체력바도(QA 0429c66 — 바별 표시만으론 저절로 켜졌음)

_active = False
_runtime: dict[str, dict] = {}
_user: set[str] = set()
_listeners: list = []
_reporter = None
_use: dict[str, bool] = {}
_boss_extra = None  # 보스바를 쓰는 다른 소비자(체력바 보스전 알림·블랙박스)가 지금 켜졌나
_saved: dict[str, dict | None] = {}  # 기능이 마지막으로 넘긴 저장 영역(v1) — 상태 문구·디버프 계산용
_fixed_saver = None  # 직접 지정 고정 목록 저장(config autofindV2.fixed) — 앱이 연결
_use_saver = None    # 사용 값 저장(config autofindV2.use) — 직접 지정으로 사용을 켤 때
_state_fn = None     # 찾기 엔진 항목 상태(컨트롤러) — place() 문구용
_detail_fn = None    # 찾기 엔진 항목 자세히(컨트롤러) — 문의 info.json용


def activate(on: bool, fixed=()) -> None:
    """앱 시작 때 한 번. fixed = 지난 실행까지의 직접 지정 고정 항목(config autofindV2.fixed)."""
    global _active
    _active = bool(on)
    _runtime.clear()
    _user.clear()
    _saved.clear()
    if not _active:
        _use.clear()
        return
    _user.update(k for k in fixed if k in KEYS)


def set_fixed_saver(fn) -> None:
    """fn(sorted keys) — 직접 지정 고정이 바뀌면 저장(다음 실행에도 유지)."""
    global _fixed_saver
    _fixed_saver = fn


def set_use_saver(fn) -> None:
    """fn(key, on) — 기능 화면에서 직접 지정해 그 기능 사용을 켤 때 저장."""
    global _use_saver
    _use_saver = fn


def _save_fixed() -> None:
    if _fixed_saver is not None:
        try:
            _fixed_saver(sorted(_user))
        except Exception:  # noqa: BLE001 — 저장 실패해도 이번 실행 동작은 유지
            import logging
            logging.getLogger(__name__).warning("직접 지정 고정 저장 실패", exc_info=True)


def active() -> bool:
    return _active


def region_for(key: str, saved):
    """기능이 쓸 영역. 자동 찾기 꺼짐(비상 값) = 저장 영역. 켜짐: 사용 꺼짐이면 None(그 기능은 쉰다 — CPU 0),
    직접 지정 고정이면 저장 영역, 아니면 찾은 자리, 못 찾았으면 저장 영역(v1, 없으면 None)."""
    if not _active:
        return saved
    _saved[key] = dict(saved) if isinstance(saved, dict) else None
    if not wanted(key):
        return None
    return _resolve(key, saved)


def current_region(key: str, saved):
    """사용 값과 상관없이 지금 그 기능이 읽을 자리(문의 자료 모으기 등) — 고정 → 자동 → 저장 영역(v1). 꺼짐이면 저장 영역."""
    if not _active:
        return saved
    _saved[key] = dict(saved) if isinstance(saved, dict) else None
    return _resolve(key, saved)


def _resolve(key: str, saved):
    if key in _user:
        return saved
    box = _runtime.get(key)
    if box is not None:
        return dict(box)
    if key == "debuff" and "boss" in _user and _saved.get("boss"):
        return _debuff_from_boss(_saved["boss"])  # 보스바만 고정 → 고정한 보스바 위 띠
    return dict(saved) if isinstance(saved, dict) else saved


def _debuff_from_boss(boss: dict) -> dict:
    """보스바 위 디버프 줄 — 컨트롤러 debuff_from_boss와 같은 규칙(논리 좌표)."""
    x, y, w, h = (boss[k] for k in ("x", "y", "w", "h"))
    top = max(0, y - int(h * 1.4))
    return {"x": x, "y": top, "w": w, "h": y + h - top}


def source(key: str) -> str | None:
    """지금 쓰는 자리의 출처 — 'user'(직접 지정 고정) · 'auto'(자동으로 찾음) · 'v1'(못 찾아 저장 영역) · None(쓸 자리 없음).
    자동 찾기 꺼짐(비상 값)이면 저장 영역이 있으면 'v1'."""
    if not _active:
        return "v1" if _saved.get(key) else None
    if key in _user:
        return "user"
    if key in _runtime:
        return "auto"
    if key == "debuff" and "boss" in _user and _saved.get("boss"):
        return "user"
    return "v1" if _saved.get(key) else None


def set_use_values(values: dict, boss_extra=None) -> None:
    """앱 시작 때(v2 켜짐) 사용 값과 보스바의 다른 소비자 콜백."""
    global _boss_extra
    _use.clear()
    _use.update({k: bool(values.get(k)) for k in USE_KEYS})
    _boss_extra = boss_extra


def use_on(key: str) -> bool:
    """사용 값(v2 켜짐일 때만 의미). 대상이 아닌 기능은 True(각자 자기 사용 값을 따른다)."""
    return not _active or key not in USE_KEYS or _use.get(key, False)


def set_use(key: str, on: bool) -> None:
    """홈 스위치 등에서 사용 값을 바꿈 → 영역이 달라지는 기능에 알림(다시 시작)."""
    if key not in USE_KEYS or _use.get(key) == bool(on):
        return
    _use[key] = bool(on)
    _notify(key)
    if key != "boss":
        _notify("boss")  # 보스바 소비자가 바뀌었을 수 있음


def wanted(key: str) -> bool:
    """이 기능이 지금 영역을 읽어야 하나(v2 켜짐). 보스바: 디버프·보스 패턴·1분 헤일로·체력바 보스전 알림·블랙박스 중 하나라도."""
    if not _active:
        return True
    if key == "boss":
        if any(_use.get(k, False) for k in ("boss", "debuff", "halo_timer")):
            return True
        try:
            return bool(_boss_extra and _boss_extra())
        except Exception:  # noqa: BLE001
            return False
    return use_on(key)


def is_auto(key: str) -> bool:
    """탭 표시용 — 지금 쓰는 영역이 자동으로 찾은 자리인지."""
    return _active and key not in _user and key in _runtime


def set_state_source(fn) -> None:
    """fn(key) → 'found'|'waiting'|'hidden'|'missing'|'searching' (찾기 엔진 상태, 컨트롤러가 연결)."""
    global _state_fn
    _state_fn = fn


def set_detail_source(fn) -> None:
    """fn() → {'phase': …, 'ui_hidden': …, 'items': {key: {status, source, box, failures, reason, seconds}}}."""
    global _detail_fn
    _detail_fn = fn


def snapshot() -> dict:
    """문의 ZIP info.json의 자동 찾기 상태(first-use-v3 6절 6): 항목별 자리·출처(last/search/research/appear/v1/user)·마지막 실패 이유."""
    out = {"enabled": _active, "fixed": sorted(_user), "use": {k: _use.get(k, False) for k in USE_KEYS} if _active else {}}
    if not _active:
        return out
    try:
        detail = _detail_fn() if _detail_fn is not None else {}
    except Exception:  # noqa: BLE001 — 문의 보내기를 막지 않게
        detail = {"error": "엔진 상태를 읽지 못함"}
    engine_items = detail.get("items", {}) if isinstance(detail, dict) else {}
    out["phase"] = detail.get("phase") if isinstance(detail, dict) else None
    out["ui_hidden"] = detail.get("ui_hidden") if isinstance(detail, dict) else None
    items = {}
    for key in KEYS:
        eng = engine_items.get("boss" if key == "debuff" else key, {})
        uses = source(key)
        if uses == "user":
            origin = "user"
        elif uses == "v1":
            origin = "v1"
        else:
            origin = eng.get("source") or None
        box = _runtime.get(key) if uses == "auto" else _saved.get(key)
        items[key] = {"place": place(key), "uses": uses, "source": origin, "box": dict(box) if box else None,
                      "wanted": wanted(key), "status": eng.get("status"), "failures": eng.get("failures"),
                      "last_failure": eng.get("reason") or None}
    out["items"] = items
    return out


def place(key: str) -> str | None:
    """화면 문구용 위치 상태 — 'user'(직접 지정) · 'found'(위치 찾음) · 'wait'(화면에 보이면 찾아요) · 'hidden'(게임 UI 안 보임 — 접속하면 찾아요) ·
    'v1'(저장된 영역 사용 · 자동으로 못 찾음) · 'missing'(못 찾음) · 'searching'(찾는 중). 자동 찾기 꺼짐이면 None. 디버프 줄은 보스바 상태를 따른다."""
    if not _active:
        return None
    if key in _user:
        return "user"
    if key in _runtime:
        return "found"
    lookup = "boss" if key == "debuff" else key
    if key == "debuff" and "boss" in _user and _saved.get("boss"):
        return "user"
    try:
        state = _state_fn(lookup) if _state_fn is not None else "searching"
    except Exception:  # noqa: BLE001
        state = "searching"
    if state == "found":
        return "found"
    if _saved.get(key):
        return "v1"
    return {"waiting": "wait", "hidden": "hidden", "missing": "missing"}.get(state, "searching")


def is_fixed(key: str) -> bool:
    """직접 지정 고정(자동이 덮지 않음 — 다음 실행에도)."""
    return _active and key in _user


def set_region(key: str, box) -> None:
    """찾기 엔진이 찾은(또는 확정·시험 중인) 자리를 반영. None이면 비움."""
    if not _active or key in _user:
        return
    before = _runtime.get(key)
    if box is None:
        _runtime.pop(key, None)
    else:
        _runtime[key] = dict(box)
    if _runtime.get(key) != before:
        _notify(key)


def user_set(key: str, enable: str | None = "") -> None:
    """기능 화면에서 직접 지정·탭 자동 찾기 → 그 기능은 직접 지정 고정(자동이 덮지 않음, 다음 실행에도 유지).
    그 화면의 기능을 쓰려는 것이므로 사용 값도 켠다(enable — 기본은 key, 디버프 화면에서 공유 보스바를 지정하면 'debuff', None이면 안 켬)."""
    if not _active:
        return
    use_key = key if enable == "" else enable
    if use_key in USE_KEYS and not _use.get(use_key, False):
        if _use_saver is not None:
            try:
                _use_saver(use_key, True)
            except Exception:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning("사용 값 저장 실패: %s", use_key, exc_info=True)
        set_use(use_key, True)
    if key in _user:
        return
    _user.add(key)
    _runtime.pop(key, None)
    _save_fixed()
    _notify(key, user=True)


def auto_return(key: str) -> None:
    """`자동으로 돌아가기`·영역 지정 해제 → 고정을 풀고 자동으로 찾은 자리로(엔진이 바로 다시 찾는다)."""
    if not _active or key not in _user:
        return
    _user.discard(key)
    _save_fixed()
    _notify(key, user=False)


def user_set_key(key: str) -> bool:
    """직접 지정 고정인가(자동 찾기 켜짐일 때만 의미)."""
    return key in _user


def user_keys() -> set[str]:
    return set(_user)


def subscribe(fn) -> None:
    """fn(key, user: bool) — 자리가 바뀌면 해당 기능을 다시 시작하게."""
    if fn not in _listeners:
        _listeners.append(fn)


def _notify(key: str, user: bool = False) -> None:
    for fn in list(_listeners):
        try:
            fn(key, user)
        except Exception:  # noqa: BLE001 — 한 구독자 실패가 나머지를 막지 않게
            import logging
            logging.getLogger(__name__).exception("자동 찾기 v2 영역 알림 실패: %s", key)


def set_reporter(fn) -> None:
    global _reporter
    _reporter = fn


def report(key: str, ok: bool, frame_id=None) -> None:
    """기능이 자기 영역을 한 번 읽은 결과(찾기 엔진의 다시 찾기·확정 판단용). 꺼짐이면 아무것도 안 함(비용 0).
    자동으로 찾은 자리가 아닌 데서(직접 지정 고정·저장 영역 v1) 읽은 결과는 'UI 보임' 신호로만 쓴다(auto=False)."""
    if _active and _reporter is not None:
        _reporter(key, bool(ok), frame_id, source(key) == "auto" or key not in _saved)


def region_property(key: str, attr: str = "_region"):
    """탭 클래스의 `_region`(단축바는 `_anchor`)을 이 제공자로 읽게 하는 속성.
    읽기 = 쓸 영역(v2 꺼짐이면 저장 영역 그대로), 쓰기 = 저장 영역 값만 바꾼다(_save가 config에 쓰는 값 — 찾은 자리가 저장되지 않게)."""
    store = "_saved" + attr

    def getter(self):
        return region_for(key, self.__dict__.get(store))

    def setter(self, value):
        self.__dict__[store] = value
    return property(getter, setter)


def saved_of(owner, attr: str = "_region"):
    """탭이 가진 저장 영역 값(찾은 자리 말고)."""
    return owner.__dict__.get("_saved" + attr)


def reset_for_tests() -> None:
    global _reporter, _boss_extra, _fixed_saver, _use_saver, _state_fn, _detail_fn
    activate(False)
    _fixed_saver = _use_saver = _state_fn = _detail_fn = None
    _listeners.clear()
    _reporter = None
    _boss_extra = None
