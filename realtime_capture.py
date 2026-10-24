"""Continuously drain desktop audio into one immutable, expiring PCM window."""
import logging
import os
import selectors
import subprocess
import threading

import numpy as np
from audio_source import OutputMonitor,capture_command
import realtime_protocol as rt

LOG=logging.getLogger('wesp-audio')
SIZE=2048


class PCMWindow:
    def __init__(self):
        self.lock=threading.Lock()
        self.samples=np.zeros(SIZE,dtype='<f4');self.samples.flags.writeable=False
        self.captured_ns=0
        self.last_batch_ns=0

    def reset(self):
        with self.lock:
            self.captured_ns=self.last_batch_ns=0

    def update(self,data,captured_ns):
        if not data or len(data)%4:raise ValueError('Incomplete PCM sample')
        values=np.frombuffer(data,dtype='<f4')[-SIZE:]
        if not np.isfinite(values).all():raise ValueError('Nonfinite PCM')
        with self.lock:
            if self.last_batch_ns and not 0<=captured_ns-self.last_batch_ns<=rt.MAX_AGE_NS:
                self.captured_ns=0;self.last_batch_ns=captured_ns
                return False
            samples=np.zeros(SIZE,dtype='<f4');samples[-len(values):]=values
            samples.flags.writeable=False
            self.samples=samples;self.captured_ns=self.last_batch_ns=captured_ns
            return True

    def snapshot(self,now=None):
        if now is None:now=rt.now_ns()
        with self.lock:
            if not self.captured_ns or not 0<=now-self.captured_ns<=rt.MAX_AGE_NS:return None
            return self.samples,self.captured_ns


class LatestCapture:
    def __init__(self):
        self.window=PCMWindow()
        self.stop=threading.Event()
        self.monitor=OutputMonitor()
        self.thread=threading.Thread(target=self.run,name='wesp-pcm-drain',daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            process=None
            try:
                source=self.monitor.source
                process=subprocess.Popen(capture_command(source,10,'WESP Audio'),
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
                os.set_blocking(process.stdout.fileno(),False)
                self.window.reset();pending=bytearray()
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout,selectors.EVENT_READ)
                    while not self.stop.is_set() and self.monitor.source==source:
                        if not selector.select(.1):continue
                        received=0;tail=len(pending)%4
                        for _ in range(16):
                            try:data=os.read(process.stdout.fileno(),65536)
                            except BlockingIOError:break
                            if not data:raise RuntimeError('Desktop audio stream ended')
                            pending.extend(data);received+=len(data)
                            excess=(len(pending)-SIZE*4)//4*4
                            if excess>0:del pending[:excess]
                        complete=len(pending)//4*4
                        if (tail+received)//4 and complete:
                            accepted=self.window.update(bytes(pending[:complete]),rt.now_ns())
                            if not accepted:del pending[:complete] # Keep split-float alignment, discard old samples.
                self.window.reset()
            except Exception:
                if not self.stop.is_set():LOG.exception('Desktop output capture unavailable; retrying')
                self.window.reset();self.stop.wait(1)
            finally:
                if process is not None:
                    process.terminate()
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                    process.stdout.close()

    def close(self):
        self.stop.set();self.thread.join(timeout=4);self.monitor.close();self.window.reset()
