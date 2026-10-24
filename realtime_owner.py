"""Owner-only local inbox. The data thread never takes a control/TCP lock."""
import json
from pathlib import Path
import selectors
import socket
import threading
import time

import effects_config
import manage
import realtime_protocol as rt


class RealtimeOwner:
    def __init__(self,runtime,get_device):
        self.runtime=Path(runtime)
        self.path=self.runtime/'audio.sock'
        self.get_device=get_device
        self.socket=None
        self.thread=None
        self.stop=threading.Event()
        self.allowed=False
        self.last_capture=0
        self.status_at=0
        self.status_signature=None
        self.stats=dict(received=0,invalid=0,stale=0,wrong_target=0,coalesced=0)

    def bind(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path.unlink(missing_ok=True)
        self.socket=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.socket.bind(str(self.path));self.path.chmod(0o600)

    def start(self):
        self.bind()
        self.thread=threading.Thread(target=self.run,name='wesp-audio-inbox',daemon=True)
        self.thread.start()

    def block(self):
        self.allowed=False
        self.last_capture=max(self.last_capture,rt.now_ns())
        device=self.get_device()
        if device is not None and hasattr(device,'revoke_realtime'):device.revoke_realtime()

    def prepare(self,prefs,memory,calibration):
        device=self.get_device();selected=prefs.get('controller') or {}
        supported=bool(device is not None and hasattr(device,'supports_realtime') and device.supports_realtime()
            and selected.get('mac')==device.expected_mac and selected.get('count')==device.led_count
            and selected.get('connection')=='wifi' and selected.get('backend')=='wesp')
        eligible=bool(supported and prefs.get('equalizer') and not memory.get('suspended')
            and not memory.get('firstLight') and not calibration and device.document.get('on'))
        try:
            if eligible:
                colors=None
                if prefs.get('equalizer_palette')=='wallpaper':
                    import wallpaper
                    colors=wallpaper.cached(self.runtime)['colors']
                config=effects_config.cached(prefs)
                self.allowed=bool(device.prepare_realtime(config,colors) if colors is not None else device.prepare_realtime(config))
            else:self.block()
        except Exception:
            self.block()
            raise
        finally:
            self.publish_status(device,selected,supported)

    def publish_status(self,device,selected,supported):
        signature=(selected.get('mac'),selected.get('count'),supported,self.allowed)
        now=time.monotonic()
        if signature==self.status_signature and now-self.status_at<1:return
        document=dict(mac=selected.get('mac'),count=selected.get('count'),supported=supported,
            active=self.allowed,updated=time.time(),local=self.stats.copy(),
            wire=getattr(device,'fast_stats',{}).copy() if device is not None else {})
        manage.atomic_write(self.runtime/'audio-stream.json',json.dumps(document).encode(),0o600)
        self.status_signature=signature;self.status_at=now

    def pump(self):
        newest=None;device=self.get_device()
        for _ in range(64):
            try:packet=self.socket.recv(rt.LOCAL.size+1)
            except BlockingIOError:break
            self.stats['received']+=1
            try:sample=rt.unpack_local(packet)
            except ValueError:self.stats['invalid']+=1;continue
            mac,count,captured,_,_=sample
            if device is None or mac!=device.expected_mac or count!=device.led_count:
                self.stats['wrong_target']+=1;continue
            now=rt.now_ns()
            if captured<=self.last_capture or not 0<=now-captured<=rt.MAX_AGE_NS:
                self.stats['stale']+=1;continue
            if newest is None or captured>newest[2]:
                if newest is not None:self.stats['coalesced']+=1
                newest=sample
            else:self.stats['coalesced']+=1
        if newest is not None:
            self.last_capture=newest[2]
            if self.allowed and device is self.get_device() and hasattr(device,'send_realtime'):
                return device.send_realtime(*newest)
        return False

    def run(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.socket,selectors.EVENT_READ)
            while not self.stop.is_set():
                if selector.select(.05):self.pump()

    def close(self):
        self.block();self.stop.set()
        if self.thread is not None:self.thread.join(timeout=2)
        if self.socket is not None:self.socket.close();self.socket=None
        self.path.unlink(missing_ok=True)
