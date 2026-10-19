"""Monotonic halo schedule with explicit battle arming and conservative resynchronization."""

from dataclasses import dataclass
import math

EVENTS=tuple(893-63*k for k in range(15))


@dataclass(frozen=True)
class HaloState:
    phase: str
    remaining: float | None = None
    until_halo: float | None = None
    warning: int | None = None


class HaloTracker:
    def __init__(self):
        self.stop()

    def stop(self):
        self.armed=False
        self.anchor=None
        self.target=None
        self.last_now=None
        self.last_remaining=None
        self.confirm=[]
        self.fired=set()
        self.checked_at=None
        self.restart_confirm=[]

    def arm(self):
        self.stop()
        self.armed=True

    def observe(self, raw, now, *, eligible=True, target=None):
        if not isinstance(now,(float,int)) or not math.isfinite(now):
            self.stop()
            return HaloState('stopped')
        if self.last_now is not None and now<self.last_now:
            self.stop()
        gap=0 if self.last_now is None else now-self.last_now
        self.last_now=now
        if not self.armed:
            return HaloState('stopped')
        if target is not None:
            if self.target is not None and target!=self.target:
                self.stop()
                return HaloState('stopped')
            self.target=target
        remaining=None if self.anchor is None else self.anchor[0]-(now-self.anchor[1])
        valid=eligible and type(raw) is int and 0<=raw<=900
        if remaining is not None and valid and raw>remaining+5:
            # One bad glyph must not rewind the battle or erase fired rounds.
            if (self.restart_confirm and
                    abs((self.restart_confirm[-1][0]-raw)-(now-self.restart_confirm[-1][1]))>1.25):
                self.restart_confirm=[]
            self.restart_confirm.append((raw,now))
            self.restart_confirm=self.restart_confirm[-3:]
            self.last_remaining=None
            if (len(self.restart_confirm)==3 and now-self.restart_confirm[0][1]>=.75
                    and self.restart_confirm[0][0]>raw):
                self.stop()
                return HaloState('stopped')
            return HaloState('uncertain')
        self.restart_confirm=[]
        if not valid or gap>5:
            self.confirm=[]
            self.last_remaining=None
            if remaining is not None:
                self.fired.update(k for k,event in enumerate(EVENTS,1) if remaining<=event+5)
            return HaloState('uncertain')
        if remaining is None or self.last_remaining is None or abs(raw-remaining)>2:
            if self.confirm and abs((self.confirm[-1][0]-raw)-(now-self.confirm[-1][1]))>1.25:
                self.confirm=[]
            self.confirm.append((raw,now))
            self.confirm=self.confirm[-3:]
            if (len(self.confirm)<3 or now-self.confirm[0][1]<.75
                    or self.confirm[0][0]<=raw):
                return HaloState('confirming')
            self.anchor=(raw,now)
            self.checked_at=now
            self.last_remaining=raw
            self.confirm=[]
            self.fired.update(k for k,event in enumerate(EVENTS,1) if raw<=event+5)
            return self._state(raw)
        warning=None
        for k,event in enumerate(EVENTS,1):
            threshold=event+5
            if remaining<=threshold and k not in self.fired:
                self.fired.add(k)
                if self.last_remaining>threshold and remaining>=threshold-1:
                    warning=k
        self.last_remaining=remaining
        if now-self.checked_at>=60:
            # Compare complete mm:ss, not just the minute digit. Never replay crossed alarms.
            self.anchor=(raw,now)
            self.checked_at=now
            remaining=raw
            self.last_remaining=raw
            self.fired.update(k for k,event in enumerate(EVENTS,1) if raw<=event+5)
        return self._state(remaining,warning)

    def _state(self,remaining,warning=None):
        if remaining<=0:
            self.armed=False
            return HaloState('ended',0)
        following=next((event for event in EVENTS if remaining>event),None)
        return HaloState('synced',remaining,None if following is None else remaining-following,warning)
