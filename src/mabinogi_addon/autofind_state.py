"""Found locations are not active registrations. All writes run on the UI thread."""
from copy import deepcopy
from datetime import datetime, timezone
import logging

from . import config
from .setup_state import BY_KEY, section, valid_box

FIELDS = {k: (f.section, 'captureRegion' if k in ('buff', 'debuff') else
              'anchor' if k == 'skillbar' else 'box') for k, f in BY_KEY.items() if f.automatic}
SHARED = ('boss', 'halo_timer', 'debuff')
_epochs = {}
_revision = 0


def changed(before, after):
    global _revision
    _revision += 1
    for key, (name, field) in FIELDS.items():
        if (section(before, name) != section(after, name)
                or section(before, 'general').get('gameExe') != section(after, 'general').get('gameExe')
                or automatic(before) != automatic(after)
                or section(section(before,'autofind'),'selected').get(key) != section(section(after,'autofind'),'selected').get(key)
                or remembered(key,before) != remembered(key,after)):
            _epochs[key] = _epochs.get(key, 0) + 1


def revision():
    return _revision


def epoch(key):
    return _epochs.get(key, 0)


def automatic(raw=None):
    raw = config._read_local_config() if raw is None else raw
    return section(raw, 'autofind').get('enabled', True) is not False


def set_automatic(value):
    raw = config._read_local_config()
    raw['autofind'] = {**section(raw, 'autofind'), 'enabled': bool(value)}
    config._write_local_config(raw)


def box_for(key, raw):
    name, field = FIELDS[key]
    box = section(raw, name).get(field)
    if key == 'skillbar' and isinstance(box, dict):
        box = {**box, 'w': 1168, 'h': 89}
    return deepcopy(box) if valid_box(box) else None


def active(key, raw=None):
    raw = config._read_local_config() if raw is None else raw
    if key in SHARED:
        return section(raw, BY_KEY[key].section).get('use', box_for(key, raw) is not None) is True
    if key == 'stat_bars':
        bars = section(section(raw, 'statBars'), 'bars')
        return any(section(bars, sid).get('show', True) for sid in ('hp','mp','sta'))
    if key in ('dorcha','tuarim','custom'):
        return bool(section(raw, BY_KEY[key].section).get('enabled', BY_KEY[key].default_enabled))
    return box_for(key, raw) is not None


def migrate(raw):
    for key in SHARED:
        name, _ = FIELDS[key]
        raw[name] = {**section(raw, name), 'use': active(key, raw)}



def initialize_consumers():
    raw=config._read_local_config()
    if all('use' in section(raw,BY_KEY[k].section) for k in SHARED):
        return
    migrate(raw)
    config._write_local_config(raw)


def remembered(key, raw=None):
    raw = config._read_local_config() if raw is None else raw
    entry = section(section(section(raw, 'autofind'), 'found'), key)
    return deepcopy(entry) if valid_box(entry.get('box')) else None


def _remember(raw, key, box, target=None):
    state = dict(section(raw, 'autofind'))
    found = dict(section(state, 'found'))
    found[key] = dict(box=deepcopy(box), target=list(target) if target else None,
                      found_at=datetime.now(timezone.utc).isoformat())
    state['found'] = found
    raw['autofind'] = state


def remember(key, box, target=None):
    if not valid_box(box):
        raise ValueError('invalid found box')
    raw = config._read_local_config()
    _remember(raw, key, box, target)
    config._write_local_config(raw)


def select(key, on, *, game_target=None):
    """Atomic selection/registration, preserving every unrelated preference."""
    raw = config._read_local_config()
    migrate(raw)  # snapshot legacy sharing before any registration changes
    name, field = FIELDS[key]
    target = dict(section(raw, name))
    box = box_for(key, raw)
    if box:
        _remember(raw, key, box)
    if on and box is None:
        entry = remembered(key, raw)
        if entry and (not game_target or not entry.get("target") or tuple(entry["target"][4:])==tuple(game_target[4:])):
            target[field] = ({k:entry['box'][k] for k in ('x','y')} if key == 'skillbar' else entry['box'])
    if key in SHARED:
        target['use'] = bool(on)
    elif key in ('dorcha','tuarim'):
        target['enabled'] = bool(on)
    elif key == 'stat_bars':
        bars = deepcopy(section(target, 'bars'))
        if not on:
            target['autofindShown'] = [sid for sid in ('hp','mp','sta') if section(bars,sid).get('show',True)]
        shown = target.get('autofindShown') or ['hp','mp','sta']
        for sid in ('hp','mp','sta'):
            bars[sid] = {**section(bars,sid), 'show': bool(on and sid in shown)}
        target['bars'] = bars
    elif not on:
        target[field] = None
    if key in ('debuff','halo_timer') and not on:
        target[field] = None
    raw[name] = target
    choices = dict(section(section(raw,'autofind'),'selected'))
    choices[key] = bool(on)
    raw['autofind'] = {**section(raw,'autofind'), 'selected':choices}
    # A consumer may select its timer/strip before the shared bar appears.
    if on and key in SHARED and box_for('boss',raw) is None:
        entry = remembered('boss',raw)
        if entry:
            raw['bossPattern'] = {**section(raw,'bossPattern'),'box':entry['box']}
    config._write_local_config(raw)


def wanted(key, raw=None):
    raw = config._read_local_config() if raw is None else raw
    return active(key,raw) or (box_for(key,raw) is None and section(section(raw,'autofind'),'selected').get(key) is True)


def shared_needed(raw=None, *, external=False):
    raw = config._read_local_config() if raw is None else raw
    bars = section(section(raw,'statBars'),'bars')
    alerts = box_for('stat_bars',raw) is not None and any(
        section(section(bars,sid),'alert').get('on') for sid in ('hp','mp','sta'))
    return external or alerts or any(active(k,raw) for k in SHARED)


def release_unused_boss(*, external=False):
    raw = config._read_local_config()
    box = box_for('boss',raw)
    if box and not shared_needed(raw,external=external):
        migrate(raw)
        _remember(raw,'boss',box)
        raw['bossPattern']['box'] = None
        config._write_local_config(raw)
        return True
    if not box and shared_needed(raw,external=external):
        entry = remembered('boss',raw)
        if entry:
            migrate(raw)
            raw['bossPattern']['box'] = entry['box']
            config._write_local_config(raw)
            return True
    return False


class Confirmation:
    """C policy: fresh successful frames, same candidate/epoch/target, active time only."""
    def __init__(self, box, stamp, target):
        self.box, self.stamp, self.target = box, stamp, target
        self.last_frame = None
        self.last_time = None
        self.elapsed = 0.0
        self.saved = False

    def observe(self, *, frame_id, now, readable, stamp, target, running=True):
        if stamp != self.stamp or target != self.target or self.saved:
            return False
        if not running:
            self.last_time = None
            return False
        if frame_id == self.last_frame:
            return False
        self.last_frame = frame_id
        if not readable:
            self.elapsed = 0.0
            self.last_time = None
            return False
        if self.last_time is not None:
            self.elapsed += max(0, now-self.last_time)
        self.last_time = now
        return self.elapsed >= 3.0

    def commit(self, key):
        if self.saved or self.elapsed < 3 or epoch(key) != self.stamp:
            return False
        raw = config._read_local_config()
        old = box_for(key,raw)
        if old != self.box:
            name, field = FIELDS[key]
            raw[name] = {**section(raw,name),field:deepcopy(self.box)}
            config._write_local_config(raw)
            logging.getLogger(__name__).info('자동 찾기 위치 저장 %s: %s -> %s',key,old,self.box)
        self.saved = True
        return True


def apply_discovered(key, *, replace=False):
    """Publish a remembered result only for a consumer the user has already selected."""
    raw=config._read_local_config()
    entry=remembered(key,raw)
    if not entry or not wanted(key,raw): return False
    if box_for(key,raw) is not None and not replace: return False
    migrate(raw)
    name,field=FIELDS[key]
    box=entry['box']
    raw[name]={**section(raw,name),field:({k:box[k] for k in ('x','y')} if key=='skillbar' else box)}
    config._write_local_config(raw)
    return True
