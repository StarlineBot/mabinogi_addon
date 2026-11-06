"""자동 찾기 v2 — 런타임 영역 제공자(docs/autofind-v2-creator-spec.md 2절).

각 탭이 영역을 읽는 한 곳. v2가 꺼져 있으면(비제작자 포함) 저장된 영역을 그대로 돌려줘 동작이 같다.
v2가 켜져 있으면 저장된 영역을 위치로 쓰지 않고 이번 실행에서 찾은 자리를 준다(못 찾았으면 None — 그 기능은 쉰다).
저장된 영역은 읽기만 하고 덮지 않는다. 탭에서 직접 지정·자동 찾기를 하면 그 실행 동안은 사용자 지정(저장 영역)이 이긴다.

영역은 저장 영역과 같은 논리 좌표 dict {x, y, w, h}(단축바는 {x, y}). 모든 호출은 화면 스레드.
"""
from __future__ import annotations

KEYS = ("buff", "debuff", "boss", "halo_timer", "stat_bars", "skillbar", "dorcha", "tuarim")
# 사용 값(2.1절) — v2 켜짐일 때만: 영역과 별개로 '이 기능을 쓰나'. 꺼지면 영역은 두고 읽기·알림·오버레이 멈춤(영역 None).
USE_KEYS = ("buff", "debuff", "boss", "halo_timer", "skillbar")

_active = False
_runtime: dict[str, dict] = {}
_user: set[str] = set()
_listeners: list = []
_reporter = None
_use: dict[str, bool] = {}
_boss_extra = None  # 보스바를 쓰는 다른 소비자(체력바 보스전 알림·블랙박스)가 지금 켜졌나


def activate(on: bool) -> None:
    """앱 시작 때 한 번(제작자 + v2 켜짐). 바꾸면 다음 실행부터."""
    global _active
    _active = bool(on)
    if not _active:
        _runtime.clear()
        _user.clear()
        _use.clear()


def active() -> bool:
    return _active


def region_for(key: str, saved):
    """기능이 쓸 영역. v2 꺼짐 = 저장 영역. v2 켜짐: 사용 꺼짐이면 None(그 기능은 쉰다 — CPU 0),
    사용자 지정이면 저장 영역, 아니면 찾은 자리(없으면 None)."""
    if not _active:
        return saved
    if not wanted(key):
        return None
    if key in _user:
        return saved
    box = _runtime.get(key)
    return dict(box) if box is not None else None


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
    """탭 표시용 — 지금 쓰는 영역이 v2가 찾은 자리인지('자동(v2)')."""
    return _active and key not in _user and key in _runtime


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


def user_set(key: str) -> None:
    """탭에서 직접 지정·자동 찾기·해제 → 이번 실행 동안 사용자 지정이 이긴다."""
    if not _active or key in _user:
        return
    _user.add(key)
    _runtime.pop(key, None)
    _notify(key, user=True)


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
    """기능이 자기 영역을 한 번 읽은 결과(찾기 엔진의 다시 찾기·확정 판단용). v2 꺼짐이면 아무것도 안 함(비용 0)."""
    if _active and _reporter is not None:
        _reporter(key, bool(ok), frame_id)


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
    global _reporter, _boss_extra
    activate(False)
    _listeners.clear()
    _reporter = None
    _boss_extra = None
