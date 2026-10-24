"""Fast audio producer: cached capability hint and nonblocking local datagrams."""
import json
from pathlib import Path
import socket
import time

import control
from i18n import tr
from realtime_capture import LatestCapture
import realtime_protocol as rt


class CapabilityHint:
    def __init__(self,runtime):
        self.runtime=Path(runtime);self.document={};self.next_read=0

    def supported(self,prefs):
        if time.monotonic()>=self.next_read:
            try:
                value=json.loads((self.runtime/'audio-stream.json').read_text())
                self.document=value if isinstance(value,dict) else {}
            except (OSError,ValueError):self.document={}
            self.next_read=time.monotonic()+.25
        selected=prefs.get('controller') or {}
        return (selected.get('backend')=='wesp' and selected.get('connection')=='wifi'
            and self.document.get('supported') is True and self.document.get('mac')==selected.get('mac')
            and self.document.get('count')==selected.get('count'))


class Publisher:
    def __init__(self,runtime,selected):
        self.path=str(Path(runtime)/'audio.sock');self.selected=dict(selected)
        self.socket=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);self.socket.setblocking(False)
        self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,4096)
        from feature_preview import Writer
        self.preview=Writer(runtime)

    def publish(self,features,captured_ns):
        packet=rt.pack_local(self.selected['mac'],self.selected['count'],captured_ns,
            rt.level(features['rms']),rt.level(features['bass']))
        try:sent=self.socket.sendto(packet,self.path)==len(packet)
        except OSError:return False # No retry or queue of yesterday's attacks.
        if sent:
            try:self.preview.publish(packet)
            except (OSError,ValueError):pass # Display must never interrupt audio.
        return sent

    def close(self):self.preview.close();self.socket.close()


def run(hint,stopped,status,analyze):
    prefs=control.settings();selected=prefs['controller']
    identity=tuple(selected.get(k) for k in ('mac','count','backend','connection'))
    capture=LatestCapture();publisher=Publisher(control.RUNTIME,selected)
    next_settings=last_status=0;last_source=0;memory={};marked=False;local_ok=False
    try:
        next_tick=time.monotonic()
        while not stopped():
            now=time.monotonic()
            if now>=next_settings:
                prefs,memory=control.settings(),control.runtime();next_settings=now+.1
                current=prefs.get('controller') or {}
                if (not prefs.get('equalizer') or memory.get('suspended') or not hint.supported(prefs)
                        or tuple(current.get(k) for k in ('mac','count','backend','connection'))!=identity):break
                if not marked:
                    # One-time runtime metadata may wait; the PCM drain never does.
                    with control.locked():
                        memory=control.runtime()
                        if not memory.get('nativeEffects'):
                            memory['nativeEffects']=True;control.write_json(control.RUNTIME/'state.json',memory)
                    marked=True
            snapshot=capture.window.snapshot()
            active=hint.document.get('active') is True
            if snapshot is not None and active and not memory.get('firstLight'):
                samples,captured_ns=snapshot
                if captured_ns!=last_source:
                    local_ok=publisher.publish(analyze(samples),captured_ns);last_source=captured_ns
            if now-last_status>=1:
                status(tr('Waiting for desktop audio') if snapshot is None else
                    tr('Receiver unavailable — audio capture remains active') if active and not local_ok else
                    tr('Music and signals are rendered on the ESP.') if active else
                    tr('Waiting for lighting to turn on or the volume indicator to finish'))
                last_status=now
            next_tick+=.01
            now=time.monotonic()
            if next_tick<now:next_tick=now
            time.sleep(max(0,next_tick-now))
    finally:
        publisher.close();capture.close()
