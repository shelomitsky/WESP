"""Finite dim section-identification frames, driven by the existing device owner."""
import hashlib
import json
import math
import time

from i18n import tr
import layout

# Leave room for the native receiver's fail-dark watchdog within a five-second test.
DURATION=3.5


def signature(prefs):
    selected=prefs.get('controller') or {}
    sections=layout.validate(prefs.get('sections'),selected.get('count'))
    return hashlib.sha256(json.dumps(sections,sort_keys=True).encode()).hexdigest()


def active(prefs,mem,now=None):
    record=mem.get('firstLight')
    now=time.monotonic() if now is None else now
    if not isinstance(record,dict) or mem.get('suspended'):
        return False
    selected=prefs.get('controller') or {}
    try:
        until=record['until']
        return (type(until) in (int,float) and math.isfinite(until) and 0<until-now<=DURATION
                and selected.get('mac')==record['mac'] and selected.get('count')==record['count']
                and signature(prefs)==record['signature'])
    except (KeyError,TypeError,ValueError):
        return False


class Lease:
    def __init__(self,prefs,section,style,now=None):
        if style not in ('chase','rgb'):
            raise ValueError(tr('Choose a direction or RGB test'))
        self.signature=signature(prefs)
        self.mac=prefs['controller']['mac']
        self.count=prefs['controller']['count']
        sections=layout.validate(prefs['sections'],self.count)
        self.section=next((item for item in sections if item['id']==section),None)
        if self.section is None:
            raise ValueError(tr('Choose a saved strip to test'))
        self.style=style
        self.start=time.monotonic() if now is None else now
        self.until=self.start+DURATION

    def record(self):
        return dict(active=True,mac=self.mac,count=self.count,signature=self.signature,
                    section=self.section['id'],name=self.section['name'],style=self.style,until=self.until)

    def frame(self,now=None):
        now=time.monotonic() if now is None else now
        elapsed=now-self.start
        if not 0<=elapsed<DURATION:
            return None
        result=[[0,0,0] for _ in range(self.count)]
        indices=layout.indices(self.section)
        if self.style=='rgb':
            color=[[24,0,0],[0,24,0],[0,0,24]][min(2,int(elapsed*3/DURATION))]
            for index in indices[:3]:result[index]=list(color)
        else:
            head=min(len(indices)-1,int(elapsed*(len(indices)-1)/max(.1,DURATION-.3)))
            result[indices[head]]=[0,32,20]
            if head:result[indices[head-1]]=[0,8,5]
        return result
