import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

class RealtimeCaptureTest(unittest.TestCase):
    def test_one_immutable_window_expires_and_discards_scheduling_backlog(self):
        import realtime_capture as capture
        window=capture.PCMWindow();base=1_000_000_000
        self.assertTrue(window.update(np.ones(4000,dtype='<f4').tobytes(),base))
        values,stamp=window.snapshot(base+10_000_000)
        self.assertEqual(len(values),2048);self.assertEqual(values.nbytes,8192);self.assertFalse(values.flags.writeable)
        self.assertIsNone(window.snapshot(base+121_000_000))
        self.assertFalse(window.update(np.ones(2048,dtype='<f4').tobytes(),base+300_000_000))
        self.assertIsNone(window.snapshot(base+300_000_000))
        self.assertTrue(window.update(np.full(480,.2,dtype='<f4').tobytes(),base+310_000_000))
        values,_=window.snapshot(base+310_000_000)
        self.assertTrue(np.all(values[:-480]==0));self.assertTrue(np.allclose(values[-480:],.2))

    def test_capture_drains_real_pipe_while_consumer_is_not_reading(self):
        import realtime_capture as capture
        read,write=os.pipe();stream=os.fdopen(read,'rb',buffering=0)
        class Process:
            stdout=stream
            def terminate(self):pass
            def wait(self,timeout=None):return 0
        monitor=SimpleNamespace(source='test.monitor',close=lambda:None)
        with patch.object(capture,'OutputMonitor',return_value=monitor),patch.object(capture.subprocess,'Popen',return_value=Process()):
            recorder=capture.LatestCapture();self.addCleanup(recorder.close)
            def emit():
                for n in range(1,41):os.write(write,np.full(480,n/100,dtype='<f4').tobytes());time.sleep(.005)
            writer=threading.Thread(target=emit,daemon=True);writer.start();writer.join(2)
            self.assertFalse(writer.is_alive(),'capture must keep draining without a consumer or network')
            time.sleep(.02)
            values,stamp=recorder.window.snapshot()
            self.assertAlmostEqual(float(values[-1]),.4,places=5)
            self.assertLess(capture.rt.now_ns()-stamp,capture.rt.MAX_AGE_NS)
            os.close(write)

    def test_split_float_after_capture_gap_keeps_alignment_and_fresh_clock(self):
        import realtime_capture as capture
        read,write=os.pipe();stream=os.fdopen(read,'rb',buffering=0)
        class Process:
            stdout=stream
            def terminate(self):pass
            def wait(self,timeout=None):return 0
        monitor=SimpleNamespace(source='test.monitor',close=lambda:None)
        with patch.object(capture,'OutputMonitor',return_value=monitor),patch.object(capture.subprocess,'Popen',return_value=Process()):
            recorder=capture.LatestCapture()
            try:
                os.write(write,np.ones(480,dtype='<f4').tobytes());time.sleep(.025)
                before=recorder.window.snapshot()[1]
                half=np.array([.37],dtype='<f4').tobytes()
                os.write(write,half[:2]);time.sleep(.02)
                self.assertEqual(recorder.window.snapshot()[1],before,'partial float must not freshen old audio')
                os.write(write,half[2:]);time.sleep(.01)
                time.sleep(.15)
                os.write(write,np.ones(480,dtype='<f4').tobytes()+half[:2]);time.sleep(.02)
                os.write(write,half[2:]+np.full(480,.37,dtype='<f4').tobytes());time.sleep(.02)
                values,_=recorder.window.snapshot()
                self.assertTrue(np.allclose(values[-480:],.37))
            finally:recorder.close();os.close(write)

    def test_shared_capture_can_label_an_isolated_demo_stream(self):
        import realtime_capture as capture
        read,write=os.pipe();stream=os.fdopen(read,'rb',buffering=0);started=threading.Event()
        class Process:
            stdout=stream
            def terminate(self):pass
            def wait(self,timeout=None):return 0
        def spawn(*args,**kwargs):started.set();return Process()
        with patch.object(capture,'OutputMonitor',return_value=SimpleNamespace(source='test.monitor',close=lambda:None)),patch.object(capture.subprocess,'Popen',side_effect=spawn) as opened:
            recorder=None
            try:
                recorder=capture.LatestCapture(client='WESP Preview')
                self.assertTrue(started.wait(1))
                self.assertIn('--client-name=WESP Preview',opened.call_args.args[0])
                self.assertIn('--property=node.virtual=true',opened.call_args.args[0])
                self.assertIn('--property=stream.monitor=true',opened.call_args.args[0])
            finally:
                if recorder:recorder.close()
                else:stream.close()
                os.close(write)

    def test_fast_rms_observes_ten_millisecond_attack(self):
        import equalizer
        source=equalizer.AudioFeatures();samples=np.zeros(2048)
        samples[-480:]=.2*np.sin(2*np.pi*100*np.arange(480)/48000)
        fast=source.process(samples,fast=True);normal=source.process(samples)
        self.assertGreater(fast['rms'],normal['rms']*1.8)
        self.assertAlmostEqual(fast['rms'],.1414,delta=.003)

    def test_local_publisher_drops_when_inbox_is_full_without_waiting(self):
        import realtime_producer as producer,realtime_protocol as rt
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);listener=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);self.addCleanup(listener.close);listener.bind(str(runtime/'audio.sock'))
            p=producer.Publisher(runtime,{'mac':'680947485628','count':2});self.addCleanup(p.close)
            p.socket.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,1024)
            started=time.monotonic();outcomes=[p.publish({'rms':.1,'bass':.1},rt.now_ns()) for _ in range(100)]
            self.assertLess(time.monotonic()-started,.1)
            self.assertIn(False,outcomes);self.assertIn(True,outcomes)

    def test_capability_hint_is_cached_and_pinned_to_route_and_identity(self):
        import realtime_producer as producer
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);path=runtime/'audio-stream.json'
            path.write_text(json.dumps(dict(supported=True,active=True,mac='680947485628',count=2)))
            hint=producer.CapabilityHint(runtime);prefs={'controller':dict(mac='680947485628',count=2,connection='wifi',backend='wesp')}
            self.assertTrue(hint.supported(prefs))
            prefs['controller']['connection']='usb';self.assertFalse(hint.supported(prefs))
            prefs['controller'].update(connection='wifi',mac='a0b7652d2050');self.assertFalse(hint.supported(prefs))

if __name__=='__main__':unittest.main()
