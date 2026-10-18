"""Transactional region removal and generation guards for modal registrations."""

from copy import deepcopy
import weakref

from PySide6.QtWidgets import QMessageBox, QPushButton
from shiboken6 import isValid

from .. import config
from ..setup_state import section, valid_box

REGIONS = {
    "buff": ("buffTracker", "captureRegion", "버프 판독"),
    "debuff": ("debuffTracker", "captureRegion", "디버프 판독"),
    "boss": ("bossPattern", "box", "공유 보스 체력바"),
    "stat_bars": ("statBars", "box", "체력·마나·스태미나 판독"),
    "skillbar": ("skillbar", "anchor", "단축바 원본"),
    "dorcha": ("dorcha", "box", "도르카 숫자 판독"),
    "tuarim": ("tuarim", "box", "투아림 % 판독"),
}


_epochs = {}


def confirm_clear(owner, title, text):
    dialog = QMessageBox(owner)
    dialog.setWindowTitle(title + " 지정 해제" if not title.endswith("지정 해제") else title)
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setText(text)
    dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    dialog.button(QMessageBox.StandardButton.Yes).setText("지정 해제")
    dialog.button(QMessageBox.StandardButton.No).setText("취소")
    dialog.setDefaultButton(QMessageBox.StandardButton.No)
    try:
        return dialog.exec()
    finally:
        dialog.deleteLater()


def warn(owner, title, text):
    QMessageBox.warning(owner, title, text)


def region_generation(key):
    return _epochs.get(REGIONS[key][:2], 0)


def generation(owner):
    return (getattr(owner, "_region_generation", 0),
            tuple(region_generation(key) for key in getattr(owner, "_region_keys", ())))


def editing_allowed(owner):
    if not isValid(owner) or getattr(owner, "_shutting_down", False):
        return False
    window = owner.window()
    return not (getattr(window, "_closing", False) or getattr(window, "_config_pending_restart", False))


def connect_selection(owner, selector, callback):
    stamp = generation(owner)

    def apply(*box):
        if not editing_allowed(owner) or generation(owner) != stamp:
            return
        try:
            callback(*box)
        except OSError:
            QMessageBox.warning(owner, "영역 저장 실패", "기존 등록 영역을 유지합니다.")

    selector.selected.connect(apply)


def clear_button(owner, key, changed):
    name, field, label = REGIONS[key]
    button = QPushButton("지정 해제", owner)
    owner._region_keys = tuple(dict.fromkeys((*getattr(owner, "_region_keys", ()), key)))
    button.setToolTip(label + " 영역만 지웁니다. 세부 설정은 유지합니다.")
    reference = weakref.ref(owner)
    callback = weakref.WeakMethod(changed)

    def remove():
        owner = reference()
        if owner is None or not editing_allowed(owner):
            return
        raw = config._read_local_config()
        before = deepcopy(section(raw, name).get(field))
        if before is None:
            return
        impacts = label
        if key == "boss":
            impacts = "보스 패턴 알림"
            general = section(raw, "general")
            if (valid_box(section(raw, "debuffTracker").get("captureRegion"))
                    and (general.get("debuffAutoGate") is not False or general.get("debuffGateMode") == "percent")):
                impacts += " · 디버프 보스 체력 판단"
            bars = section(section(raw, "statBars"), "bars")
            if (valid_box(section(raw, "statBars").get("box"))
                    and any(section(value, "alert").get("on") for value in bars.values() if isinstance(value, dict))):
                impacts += " · 체력바 보스전 경고"
        answer = confirm_clear(owner, label + " 지정 해제",
            impacts + "에 사용하는 영역을 지정 해제할까요?\n"
            "해당 영역의 판독·표시·알림이 중단됩니다.\n"
            "다른 영역과 아이콘·표시·배치·알림·소리 설정은 유지합니다.")
        if answer != QMessageBox.StandardButton.Yes or not editing_allowed(owner):
            return
        latest = config._read_local_config()
        if section(latest, name).get(field) != before:
            warn(owner, "영역 변경됨", "확인 중 영역이 변경됐습니다. 현재 영역을 확인한 뒤 다시 시도하세요.")
            return
        target = dict(section(latest, name))
        target[field] = None
        latest[name] = target
        try:
            config._write_local_config(latest)
        except OSError:
            warn(owner, "지정 해제 실패", "영역을 저장하지 못했습니다. 기존 영역과 동작을 유지합니다.")
            return
        owner._region_generation = getattr(owner, "_region_generation", 0) + 1
        identity = REGIONS[key][:2]
        _epochs[identity] = region_generation(key) + 1
        selector = getattr(owner, "_selector", None)
        if selector is not None:
            selector.close()
        handler = callback()
        if handler is not None:
            handler()

    button.clicked.connect(remove)
    return button


def save_boxes(owner, boxes):
    raw = config._read_local_config()
    for key, box in boxes.items():
        name, field, _ = REGIONS[key]
        target = dict(section(raw, name))
        target[field] = dict(zip(("x", "y", "w", "h"), box))
        raw[name] = target
    try:
        config._write_local_config(raw)
    except OSError:
        QMessageBox.warning(owner, "영역 저장 실패", "기존 등록 영역을 유지합니다.")
        return False
    return True
