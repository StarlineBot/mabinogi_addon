"""사용 준비 상태. 저장된 좌표의 존재와 현재 검출 성공은 구분한다."""

from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Feature:
    key: str
    name: str
    section: str
    default_enabled: bool
    guidance: str
    automatic: bool = True
    beta: bool = False


FEATURES = (
    Feature("buff", "버프 트래커", "buffTracker", True,
            "기준 버프와 추적할 버프의 아이콘·남은 시간이 들어오는지 확인하세요."),
    Feature("debuff", "디버프 트래커", "debuffTracker", True,
            "보스바 위 디버프 줄이 들어오는지 확인하세요. 아이콘이 없어도 등록할 수 있습니다."),
    Feature("tuarim", "투아림", "tuarim", False,
            "숫자와 %가 모두 들어오는지 확인하세요. 판독값은 적용 후 투아림 탭에서 확인하세요."),
    Feature("boss", "보스 패턴 알림", "bossPattern", False,
            "보스 이름과 체력 비율이 모두 들어오는지 확인하세요."),
    Feature("stat_bars", "체력바", "statBars", False,
            "생명력·마나·스태미나가 들어오고 경험치 바는 빠졌는지 확인하세요.", beta=True),
    Feature("skillbar", "단축바", "skillbar", False,
            "첫 칸부터 마지막 그룹까지 잘리지 않았는지 확인하세요. 그룹별 복제는 유지됩니다.", beta=True),
    Feature("custom", "커스텀 오버레이", "customOverlay", True,
            "개별 설정에서 복제할 영역을 직접 추가하세요.", automatic=False),
    Feature("memo", "메모", "memo", True,
            "개별 설정에서 표시 위치와 너비를 직접 지정하세요.", automatic=False),
)
BY_KEY = {feature.key: feature for feature in FEATURES}


def section(raw, name):
    value = raw.get(name)
    return value if isinstance(value, dict) else {}


def valid_box(value):
    return (isinstance(value, dict)
            and all(type(value.get(k)) is int for k in ("x", "y", "w", "h"))
            and value["w"] > 0 and value["h"] > 0)


def enabled(key, raw=None):
    raw = config._read_local_config() if raw is None else raw
    feature = BY_KEY[key]
    return bool(section(raw, feature.section).get("enabled", feature.default_enabled))


def save_enabled(key, value):
    raw = config._read_local_config()
    feature = BY_KEY[key]
    target = dict(section(raw, feature.section))
    target["enabled"] = bool(value)
    raw[feature.section] = target
    config._write_local_config(raw)


def remember_order(key, checked):
    raw = config._read_local_config()
    general = dict(section(raw, "general"))
    previous = general.get("setupOrder")
    previous = previous if isinstance(previous, list) else [f.key for f in FEATURES if enabled(f.key, raw) and f.key != key]
    order = [item for item in previous if isinstance(item, str) and item in BY_KEY and item != key]
    if checked:
        order.append(key)
    if previous == order:
        return
    general["setupOrder"] = order
    raw["general"] = general
    config._write_local_config(raw)


def missing(key, raw=None):
    raw = config._read_local_config() if raw is None else raw
    target = section(raw, BY_KEY[key].section)
    if key in ("buff", "debuff"):
        result = [] if valid_box(target.get("captureRegion")) else [key]
        if key == "debuff" and section(raw, "general").get("debuffGateMode") == "percent":
            if not valid_box(section(raw, "bossPattern").get("box")):
                result.append("boss")
        return result
    if key == "skillbar":
        anchor = target.get("anchor")
        return [] if (isinstance(anchor, dict)
                      and all(type(anchor.get(k)) is int for k in ("x", "y"))) else [key]
    if key == "custom":
        items = target.get("overlays")
        return [] if isinstance(items, list) and any(valid_box(item) for item in items) else [key]
    if key == "memo":
        box = section(raw, "memoTracker").get("captureRegion")
    else:
        box = target.get("box")
    result = [] if valid_box(box) else [key]
    if key == "stat_bars":
        bars = section(target, "bars")
        if any(
            section(a, "alert").get("on") for a in bars.values() if isinstance(a, dict)
        ) and not valid_box(section(raw, "bossPattern").get("box")):
            result.append("boss")
    return result


def pending(raw=None, *, automatic_only=False):
    raw = config._read_local_config() if raw is None else raw
    result = []
    saved_order = section(raw, "general").get("setupOrder")
    order = [key for key in saved_order if isinstance(key, str) and key in BY_KEY] if isinstance(saved_order, list) else []
    order += [feature.key for feature in FEATURES if feature.key not in order]
    for key in order:
        feature = BY_KEY[key]
        if enabled(feature.key, raw):
            for key in missing(feature.key, raw):
                if key not in result and (not automatic_only or BY_KEY[key].automatic):
                    result.append(key)
    return result


def needs_start_screen(raw=None):
    raw = config._read_local_config() if raw is None else raw
    if section(raw, "general").get("skipSetup") is True:
        return False
    return bool(pending(raw) or (
        any(enabled(f.key, raw) for f in FEATURES)
        and not section(raw, "general").get("gameExe")))
