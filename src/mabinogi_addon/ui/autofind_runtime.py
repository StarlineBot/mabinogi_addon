"""Persistent worker capture and discovery; Qt owns guarded capture and commits."""
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
import logging

from PySide6.QtCore import QObject, QTimer

from .. import config, autofind_state as state
from ..autofind_replay import detector_assets, run_detector
from ..setup_state import section
from ..system.window_capture import registered_game_target
from .dpi import to_logical, to_physical

_log = logging.getLogger(__name__)
MOVING = ('buff','dorcha','tuarim')


def buff_templates():
    import cv2
    from ..catalog import available_catalog
    from ..image_io import imread
    result = []
    for buff in available_catalog():
        template = imread(buff.match_icon)
        if template is not None:
            result.append(cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) if template.ndim == 3 else template)
    return tuple(result)


def readable(key, frame, *, templates=None):
    if frame is None or not frame.size:
        return False
    if key == 'dorcha':
        from ..detect.dorcha_reader import read_dorcha
        return read_dorcha(frame) is not None
    if key == 'tuarim':
        from ..detect.tuarim_reader import read_observation
        return read_observation(frame) is not None
    if key == 'halo_timer':
        from ..detect.halo_timer import read_seconds
        return read_seconds(frame,max_seconds=3600) is not None
    if key in ('boss','debuff'):
        from ..detect.boss_bar import make_validator
        return make_validator()(frame)
    if key == 'buff':
        import cv2
        gray = cv2.cvtColor(frame[:,:64],cv2.COLOR_BGR2GRAY)
        for template in buff_templates() if templates is None else templates:
            if gray.shape[0]>=template.shape[0] and gray.shape[1]>=template.shape[1]:
                if cv2.minMaxLoc(cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED))[1]>=.85:
                    return True
        return False
    # Fixed-region validation uses the existing geometric detector.
    return run_detector(key,frame,detector_assets(key),{}) is not None


def expected_crop(key, target):
    _,_,x,y,w,h=target
    if key=='boss':
        top=h-(263 if h<=1080 else 193)-45
        return x+w//2-340,y+max(0,top),680,min(150,h-max(0,top))
    top=(146 if h<=1080 else 173 if h>=2000 else 136)-35
    return x+w//2-140,y+top,280,110


def find_expected(key, frame):
    if key=='boss':
        # Pad above the small strip so the existing lower-half search covers it.
        import numpy as np
        from ..detect.boss_bar import locate_boss_bar, make_validator
        h=frame.shape[0]
        padded=np.concatenate((np.zeros((3*h,frame.shape[1],3),dtype=frame.dtype),frame))
        box=locate_boss_bar(padded,make_validator())
        return None if box is None else (box[0],box[1]-3*h,box[2],box[3])
    from ..detect.halo_timer import cells,read_seconds
    found=[]
    for _,(x,y,w,h) in cells(frame):
        x0,y0=max(0,x-4),max(0,y-4)
        roi=frame[y0:y+h+4,x0:x+w+4]
        if read_seconds(roi,max_seconds=3600) is not None:
            found.append((x0,y0,roi.shape[1],roi.shape[0]))
    return found[0] if len(found)==1 else None


class NativeCapture:
    """Owned exclusively by one executor thread, including creation and close."""
    def __init__(self):
        self.sct = None
        self.failed = False

    def grab(self, x, y, w, h):
        import numpy as np
        try:
            if self.sct is None:
                import mss
                self.sct = mss.mss()
            shot = self.sct.grab(dict(left=x, top=y, width=w, height=h))
            frame = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[:, :, :3].copy()
            self.failed = False
            return frame
        except Exception:
            if not self.failed:
                _log.warning('자동 찾기 캡처 실패', exc_info=True)
            self.failed = True
            return None

    def close(self):
        sct, self.sct = self.sct, None
        if sct is not None:
            try: sct.close()
            except Exception: _log.warning('자동 찾기 캡처 정리 실패', exc_info=True)


class AutofindRuntime(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window=window
        self.executor = None
        self.native = NativeCapture()
        self._raw_revision = -1
        self._raw = None
        self._templates_revision = -1
        self._templates = ()
        self.future=None
        self.job=None
        self.closed=False
        self.capturing=False
        self.target=None
        self.target_generation=0
        self.candidates={}
        self.lost={}
        self.failures={}
        self.next_search={}
        self.next_wait=0.0
        self.next_full=monotonic()+60
        self.last_tick=None
        self.sequence=0
        self.notified=set()
        self._notice_epochs={}
        self._automatic=None
        self.timer=QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._safe_tick)
        self.timer.start()

    def shutdown(self):
        if self.closed: return
        self.closed=True
        self.timer.stop()
        self.candidates.clear()
        if self.executor is not None:
            # Queued after the only in-flight job: release on the owning thread.
            self.executor.submit(self.native.close)
            self.executor.shutdown(wait=False)
        self.future = self.job = None

    def _notice(self, key, visible):
        tab = getattr(self.window, 'buff_tab' if key == 'buff' else 'resource_tab', None)
        region = getattr(tab, 'region_section', None)
        if visible:
            self.notified.add(key)
            self._notice_epochs[key] = state.epoch(key)
            name = {'buff': '버프', 'dorcha': '도르카', 'tuarim': '투아림'}[key]
            particle = '을' if key == 'tuarim' else '를'
            message = f'{name}{particle} 10초 넘게 읽지 못했어요. 아래 영역 다시 지정을 펼쳐 자동 찾기를 눌러주세요.'
        else:
            self.notified.discard(key)
            self._notice_epochs.pop(key, None)
            message = ''
        if region is not None:
            region.set_notice(key, message)

    def _settings(self):
        revision = state.revision()
        if revision != self._raw_revision:
            self._raw = config._read_local_config()
            self._raw_revision = revision
        return self._raw

    def _read(self, key, frame, revision):
        if key == 'buff':
            if self._templates_revision != revision:
                self._templates = buff_templates()
                self._templates_revision = revision
            return readable(key, frame, templates=self._templates)
        return readable(key, frame)

    def _submit(self, job, work):
        if self.closed or self.future is not None:
            return
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='autofind-runtime')
        job["generation"] = self.target_generation
        self.job = job
        self.future = self.executor.submit(work)

    def _capture(self, physical):
        """Prepare on Qt; native capture runs on the persistent worker unless occluded by our UI."""
        target = self.target
        _, _, left, top, width, height = target
        x, y, w, h = physical
        if w <= 0 or h <= 0 or x < left or y < top or x+w > left+width or y+h > top+height:
            return lambda: None
        if self.window.dorcha_tab._own_window_over(physical):
            self.capturing = True
            try:
                frame = self.window.boss_tab._grab_rect(x, y, w, h)
                frame = frame.copy() if frame is not None else None
            finally:
                self.capturing = False
            return lambda: frame if registered_game_target(target) == target else None
        def capture():
            if self.closed or registered_game_target(target) != target:
                return None
            frame = self.native.grab(x, y, w, h)
            return frame if not self.closed and registered_game_target(target) == target else None
        return capture

    def _safe_tick(self):
        try: self.tick()
        except Exception: _log.exception("자동 찾기 상태 갱신 실패")

    def tick(self):
        if self.closed or self.capturing: return
        now=monotonic()
        window=self.window
        target=registered_game_target(self.target)
        if target!=self.target:
            for key in tuple(self.notified): self._notice(key, False)
            self.target=target
            self.target_generation+=1
            self.candidates.clear()
            self.lost.clear()
            self.next_search.clear()
            self.failures.clear()
            self.last_tick=None
        raw=self._settings()
        auto=state.automatic(raw)
        if auto != self._automatic:
            self._automatic = auto
            self.lost.clear()
            for key in tuple(self.notified): self._notice(key, False)
            if self.job: self.job['suspended'] = True
        for key in tuple(self.notified):
            if not state.active(key, raw) or self._notice_epochs[key] != state.epoch(key):
                self._notice(key, False)
                self.lost.pop(key, None)
        running=bool(target and not getattr(window,'_paused',False) and not window._setup_busy()
                     and not getattr(window,'_config_pending_restart',False) and window._watcher.is_game_active())
        if not running:
            self.last_tick=None
            if self.job: self.job["suspended"]=True
            for candidate in self.candidates.values(): candidate.last_time=None
            # A pending result is discarded while capture/verification is suspended.
            if self.future is not None and self.future.done(): self.future=self.job=None
            return
        delta=0 if self.last_tick is None else min(1,now-self.last_tick)
        self.last_tick=now
        self.candidates={k:c for k,c in self.candidates.items() if auto and c.stamp==state.epoch(k) and c.target==target}
        if self.future is not None:
            if not self.future.done(): return
            job=self.job
            future=self.future
            self.future=self.job=None
            try: result=future.result()
            except Exception:
                _log.exception('자동 찾기 백그라운드 판독 실패')
                return
            if job.get('suspended') or job.get('generation')!=self.target_generation or job['target']!=target or any(state.epoch(k)!=v for k,v in job['stamps'].items()): return
            self._accept(job,result,now,auto,delta)
            return
        # Confirm and monitor only active registrations, never remembered locations.
        checks={}
        stamps={key:state.epoch(key) for key in MOVING}
        for key in MOVING:
            if not state.active(key,raw): continue
            box=self.candidates[key].box if key in self.candidates else state.box_for(key,raw)
            if box:
                physical=to_physical(box)
                checks[key]=self._capture(physical)
        due=[k for k in MOVING if state.active(k,raw) and (self.lost.get(k,0)>10 or (state.box_for(k,raw) is None and section(section(raw,"autofind"),"selected").get(k) is True))
             and now>=self.next_search.get(k,0) and k not in self.candidates]
        if auto and due:
            detector='buff' if 'buff' in due else 'resources'
            keys=('buff',) if detector=='buff' else tuple(k for k in ('dorcha','tuarim') if state.active(k,raw))
            self._search(detector,keys,now)
            return
        if auto and section(raw,'autofind').get('armed') and now>=self.next_wait:
            waiting=[k for k in ('boss','halo_timer') if not state.remembered(k,raw) and state.box_for(k,raw) is None]
            self.next_wait=now+10
            if waiting:
                key=min(waiting,key=lambda k:self.next_search.get(k,0))
                full=now>=self.next_full
                if full: self.next_full=now+60
                self._search(key,('boss','debuff') if key=='boss' else ('halo_timer',),now,waiting=True,small=not full)
                return
        if checks:
            self.sequence+=1
            job=dict(kind='read',target=target,stamps={k:stamps[k] for k in checks},frame_id=self.sequence,delta=delta)
            revision = self._raw_revision
            def work():
                result = {}
                for key, capture in checks.items():
                    frame = capture()
                    result[key] = None if frame is None else self._read(key, frame, revision)
                return result
            self._submit(job, work)

    def _search(self, detector, keys, now, *, waiting=False, small=False):
        physical=expected_crop(detector,self.target) if small else tuple(self.target[2:])
        stamps={k:state.epoch(k) for k in keys}
        capture=self._capture(physical)
        if any(state.epoch(k)!=v for k,v in stamps.items()): return
        job=dict(kind='search',target=self.target,stamps=stamps,
                 keys=keys,detector=detector,physical=physical,waiting=waiting)
        def work():
            frame = capture()
            if frame is None: return None, {"capture_failed": True}
            trace={}
            box=find_expected(detector,frame) if small else run_detector(detector,frame,detector_assets(detector),trace)
            if box and detector=='buff':
                from ..detect.favorites import widen_to_favorites
                box=widen_to_favorites(frame,box)
            return box,trace
        self._submit(job,work)
        for key in keys: self.next_search[key]=now+(60 if self.failures.get(key,0)>=3 else 10)

    def _accept(self, job, result, now, auto, delta):
        if job['kind']=='read':
            for key,ok in result.items():
                candidate=self.candidates.get(key)
                if ok is None:
                    if candidate: candidate.last_time = None
                    continue
                if candidate:
                    if candidate.observe(frame_id=job['frame_id'],now=now,readable=ok,stamp=state.epoch(key),target=self.target):
                        try: saved=candidate.commit(key)
                        except OSError:
                            _log.exception('자동 찾기 위치 저장 실패')
                            saved=False
                        self.candidates.pop(key,None)
                        if saved:
                            if candidate.changed:
                                self.window._reload_autofind_feature(key)
                            self.lost[key]=self.failures[key]=0
                    elif now-getattr(candidate,"created",now)>10:
                        # A failed frame resets the 3-second interval. Bound unreadable trials to 10 seconds.
                        self.candidates.pop(key,None)
                        self.failures[key]=self.failures.get(key,0)+1
                        self.next_search[key]=now+(60 if self.failures[key]>=3 else 10)
                elif ok:
                    self.lost[key]=self.failures[key]=0
                    self._notice(key, False)
                else:
                    self.lost[key]=self.lost.get(key,0)+job['delta']+delta
                    if not auto and self.lost[key]>10 and key not in self.notified:
                        self._notice(key, True)
                        message='못 읽은 지 10초가 지났어요. 해당 탭에서 자동 찾기를 눌러주세요.'
                        self.window.setup_guide.record_result(key,'못 찾음 · '+message)
            return
        if not auto: return
        box,trace=result
        if trace.get("capture_failed"): return
        ox,oy,_,_=job['physical']
        for key in job['keys']:
            region=trace.get('regions',{}).get(key) if job['detector']=='resources' else box
            if region is None:
                self.failures[key]=self.failures.get(key,0)+1
                self.next_search[key]=now+(60 if self.failures[key]>=3 else 10)
                continue
            if key=='debuff':
                x,y,w,h=region
                top=max(0,y-int(h*1.4))
                region=x,top,w,y+h-top
            x,y,w,h=region
            logical=dict(zip(('x','y','w','h'),to_logical(x+ox,y+oy,w,h)))
            if job['waiting']:
                try:
                    state.remember(key,logical,self.target)
                    if state.wanted(key):
                        state.select(key,True,game_target=self.target)
                        self.window._reload_autofind_feature(key)
                    if key=='boss':
                        external=bool(getattr(getattr(self.window,'blackbox_tools',None),'wants_boss_presence',lambda:False)())
                        state.release_unused_boss(external=external)
                        self.window.boss_tab.reload_region()
                    self.window.setup_guide.record_result(key,'찾음')
                except OSError: _log.exception('등장 위치 저장 실패')
            else:
                self.candidates[key]=state.Confirmation(logical,state.epoch(key),self.target)
                self.candidates[key].created=now


def try_remembered(owner, key, apply):
    """Explicit tab action: validate a remembered location before any whole-window search."""
    from .screen_grab import capture_for_autofind
    from .region_registration import region_generation, editing_allowed
    entry=state.remembered(key)
    target=registered_game_target()
    if not entry or target is None or not editing_allowed(owner): return False
    if entry.get('target') and tuple(entry['target'][4:])!=tuple(target[4:]): return False
    stamp=region_generation(key)
    frame,ox,oy=capture_for_autofind(require_game=True,strict_game=True)
    if frame is None or registered_game_target(target)!=target or region_generation(key)!=stamp: return False
    x,y,w,h=to_physical(entry['box'])
    x,y=x-ox,y-oy
    if x<0 or y<0 or x+w>frame.shape[1] or y+h>frame.shape[0]: return False
    crop=frame[y:y+h,x:x+w]
    if key=='debuff': crop=crop[-37:]
    if not readable(key,crop): return False
    if not editing_allowed(owner) or region_generation(key)!=stamp: return False
    apply(*(entry['box'][k] for k in ('x','y','w','h')))
    return True
