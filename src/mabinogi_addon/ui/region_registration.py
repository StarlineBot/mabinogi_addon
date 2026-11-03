"""Transactional region removal and generation guards for modal registrations."""

from copy import deepcopy
import weakref

from PySide6.QtWidgets import QMessageBox, QPushButton
from shiboken6 import isValid

from .. import config
from ..setup_state import section, valid_box
from .settings_layout import danger_style

REGIONS = {
    "buff": ("buffTracker", "captureRegion", "버프 판독"),
    "debuff": ("debuffTracker", "captureRegion", "디버프 판독"),
    "boss": ("bossPattern", "box", "공유 보스 체력바"),
    'halo_timer': ('haloTimer','box','전투 제한 시간'),
    "stat_bars": ("statBars", "box", "체력·마나·스태미나 판독"),
    "skillbar": ("skillbar", "anchor", "단축바 원본"),
    "dorcha": ("dorcha", "box", "도르카 숫자 판독"),
    "tuarim": ("tuarim", "box", "투아림 % 판독"),
    "memo": ("memoTracker", "captureRegion", "메모 표시 위치·너비"),
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
    from ..autofind_state import epoch
    return _epochs.get(REGIONS[key][:2], 0) + epoch(key)


def invalidate_region(key):
    _epochs[REGIONS[key][:2]] = _epochs.get(REGIONS[key][:2],0) + 1
    from .. import autofind_state
    autofind_state._epochs[key] = autofind_state.epoch(key) + 1


def generation(owner):
    return (getattr(owner, "_region_generation", 0),
            tuple(region_generation(key) for key in getattr(owner, "_region_keys", ())))


def editing_allowed(owner):
    if not isValid(owner) or getattr(owner, "_shutting_down", False):
        return False
    window = owner.window()
    return not (getattr(window, "_closing", False) or getattr(window, "_config_pending_restart", False))


def connect_selection(owner, selector, callback):
    for key in getattr(owner,"_region_keys",()): invalidate_region(key)
    stamp = generation(owner)

    def apply(*box):
        if not editing_allowed(owner) or generation(owner) != stamp:
            return
        try:
            callback(*box)
        except OSError:
            QMessageBox.warning(owner, "영역 저장 실패", "기존 등록 영역을 유지해요.")

    selector.selected.connect(apply)


def clear_button(owner, key, changed):
    name, field, label = REGIONS[key]
    button = QPushButton("지정 해제", owner)
    button.setStyleSheet(danger_style())
    button.setEnabled(section(config._read_local_config(), name).get(field) is not None)
    owner._region_keys = tuple(dict.fromkeys((*getattr(owner, "_region_keys", ()), key)))
    button.setToolTip(label + " 영역만 지워요. 세부 설정은 유지해요.")
    reference = weakref.ref(owner)
    method_name = changed.__name__

    def remove():
        owner = reference()
        if owner is None or not editing_allowed(owner):
            return
        raw = config._read_local_config()
        before = deepcopy(section(raw, name).get(field))
        if before is None:
            return
        impacts = ('디버프 보스 확인' if owner.__class__.__name__=='DebuffTab' else '보스 패턴 알림') if key=='boss' else label
        answer = confirm_clear(owner, label + " 지정 해제",
            impacts + "을 지정 해제할까요?\n"
            "해당 영역의 판독·표시·알림이 중단돼요.\n"
            "다른 영역과 아이콘·표시·배치·알림·소리 설정은 유지해요.")
        if answer != QMessageBox.StandardButton.Yes or not editing_allowed(owner):
            return
        latest = config._read_local_config()
        if section(latest, name).get(field) != before:
            warn(owner, "영역 변경됨", "확인 중 영역이 변경됐어요. 현재 영역을 확인한 뒤 다시 시도하세요.")
            return
        try:
            if key in ('boss','debuff','halo_timer'):
                from .. import autofind_state as state
                state.select('debuff' if key=='boss' and owner.__class__.__name__=='DebuffTab' else key,False)
                window=owner.window()
                external = bool(getattr(getattr(window,'blackbox_tools',None),'wants_boss_presence',lambda:False)())
                state.release_unused_boss(external=external)
            else:
                target = dict(section(latest, name))
                target[field] = None
                latest[name] = target
                auto = dict(section(latest,"autofind"))
                auto["selected"] = {**section(auto,"selected"),key:False}
                latest["autofind"] = auto
                config._write_local_config(latest)
        except OSError:
            warn(owner, "지정 해제 실패", "영역을 저장하지 못했어요. 기존 영역과 동작을 유지해요.")
            return
        owner._region_generation = getattr(owner, "_region_generation", 0) + 1
        invalidate_region(key)
        selector = getattr(owner, "_selector", None)
        if selector is not None and isValid(selector):
            selector.close()
        getattr(owner,method_name)()
        if key == "boss" and hasattr(owner,"reload_region"):
            owner.reload_region()

    button.clicked.connect(remove)
    return button


def save_boxes(owner, boxes):
    from ..autofind_state import migrate
    raw = config._read_local_config()
    migrate(raw)
    for key, box in boxes.items():
        name, field, _ = REGIONS[key]
        target = dict(section(raw, name))
        target[field] = dict(zip(("x", "y", "w", "h"), box))
        if key=="boss" and owner.__class__.__name__=="BossTab" or key=="debuff" and owner.__class__.__name__=="DebuffTab":
            target["use"]=True
        raw[name] = target
    try:
        config._write_local_config(raw)
    except OSError:
        warn(owner, "영역 저장 실패", "기존 등록 영역을 유지해요.")
        return False
    return True
