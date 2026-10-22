"""Exercise capture loop with a real PCM pipe; no audio server or HTTP needed."""
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control
import equalizer
import layout


class Clock:
    def __init__(self):
        self.now = 0
    def monotonic(self):
        return self.now


class BatchedAudioTest(unittest.TestCase):
    def test_wallpaper_updates_live_without_image_decoding_in_audio_worker(self):
        handlers,frames={},[]
        clock=Clock()
        prefs=dict(equalizer=True,equalizer_palette='wallpaper',
                   controller=dict(count=20),sections=layout.legacy(20,True,False))
        tone=(.4*np.sin(2*np.pi*100*np.arange(2048)/48000)).astype('<f4').tobytes()

        class Stream:
            def fileno(self): return 99
            def close(self): pass
        class Capture:
            stdout=Stream()
            def terminate(self): pass
            def wait(self,timeout=None): return 0
        class Selector:
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def register(self,*_): pass
            def select(self,timeout):
                clock.now+=max(timeout,.000001)
                return [(None,None)]

        import wallpaper
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'wallpaper-palette.json'
            def save(color):
                control.write_json(cache,dict(available=True,status='Test wallpaper',colors=[color]*10))
            save([255,0,0])
            def frame(*args,pixels=None,**kwargs):
                frames.append(pixels)
                if len(frames)==1:
                    save([0,0,255])
                else:
                    handlers[signal.SIGTERM](None,None)
                return True
            with patch.object(signal,'signal',side_effect=lambda s,f:handlers.update({s:f})), \
                 patch.object(equalizer.time,'monotonic',side_effect=clock.monotonic), \
                 patch.object(equalizer.selectors,'DefaultSelector',Selector), \
                 patch.object(equalizer.os,'read',return_value=tone), \
                 patch.object(equalizer.os,'set_blocking'), \
                 patch.object(control,'RUNTIME',Path(tmp)), \
                 patch.object(control,'settings',return_value=prefs), \
                 patch.object(control,'runtime',return_value=dict(suspended=False)), \
                 patch.object(control,'equalizer_frame',side_effect=frame), \
                 patch.object(wallpaper,'sample_pixels',side_effect=AssertionError('audio decoded wallpaper')), \
                 patch.object(equalizer,'restore'), \
                 patch.object(equalizer.subprocess,'Popen',return_value=Capture()) as capture:
                equalizer.run()
            self.assertEqual(capture.call_count,1)
        self.assertGreater(frames[0][9][0],0)
        self.assertEqual(frames[0][9][1:],[0,0])
        self.assertEqual(frames[1][9][:2],[0,0])
        self.assertGreater(frames[1][9][2],0)

    def test_decay_changes_while_capture_is_running(self):
        handlers, levels, analyzers = {}, [], []
        clock = Clock()
        prefs = dict(equalizer=True, equalizer_decay_ms=250)
        tone = (.4*np.sin(2*np.pi*100*np.arange(2048)/48000)).astype('<f4').tobytes()
        silence = np.zeros(2048, dtype='<f4').tobytes()
        real_analyzer = equalizer.SpatialSpectrum

        def make_analyzer(*args, **kwargs):
            analyzer = real_analyzer(*args, **kwargs)
            analyzers.append(analyzer)
            return analyzer

        class Stream:
            def fileno(self): return 99
            def close(self): pass
        class Capture:
            stdout = Stream()
            def terminate(self): pass
            def wait(self, timeout=None): return 0
        class Selector:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def register(self, *_): pass
            def select(self, timeout):
                clock.now += max(timeout, .000001)
                return [(None,None)]

        def frame(*args, **kwargs):
            levels.append(analyzers[0].level)
            prefs['equalizer_decay_ms'] = 600
            if len(levels) == 7:
                handlers[signal.SIGTERM](None,None)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(signal, 'signal', side_effect=lambda s,f:handlers.update({s:f})), \
                 patch.object(equalizer.time, 'monotonic', side_effect=clock.monotonic), \
                 patch.object(equalizer.selectors, 'DefaultSelector', Selector), \
                 patch.object(equalizer.os, 'read', side_effect=[tone]+[silence]*10), \
                 patch.object(equalizer.os, 'set_blocking'), \
                 patch.object(control, 'RUNTIME', Path(tmp)), \
                 patch.object(control, 'settings', return_value=prefs), \
                 patch.object(control, 'runtime', return_value=dict(suspended=False)), \
                 patch.object(control, 'equalizer_frame', side_effect=frame), \
                 patch.object(equalizer, 'SpatialSpectrum', side_effect=make_analyzer), \
                 patch.object(equalizer, 'restore'), \
                 patch.object(equalizer.subprocess, 'Popen', return_value=Capture()):
                equalizer.run()
        self.assertEqual(len(analyzers), 1, 'settings must not restart capture or auto gain')
        self.assertGreater(levels[-1], .6, 'the new decay must affect the running worker')

    def test_audio_batches_do_not_reduce_sixty_hz_output(self):
        # Emulate a backend delivering 40 ms of PCM at once. The output must
        # still tick every 16.7 ms using the latest rolling analysis window.
        handlers, frames = {}, []
        clock = Clock()
        tone = (.4*np.sin(2*np.pi*100*np.arange(1920)/48000)).astype('<f4').tobytes()

        class Stream:
            def fileno(self): return 99
            def close(self): pass
        class Capture:
            stdout = Stream()
            def terminate(self): pass
            def wait(self, timeout=None): return 0
        class Selector:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def register(self, *_): pass
            def select(self, timeout):
                before = clock.now
                next_batch = (int(round(before/.04, 8))+1)*.04
                if before == 0:
                    clock.now = .000001
                    return [(None,None)]
                clock.now += timeout
                if clock.now >= next_batch-1e-8:
                    clock.now = max(clock.now, next_batch)
                    return [(None,None)]
                return []

        def frame(*args, **kwargs):
            frames.append(clock.now)
            if len(frames) == 12:
                handlers[signal.SIGTERM](None,None)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(signal, 'signal', side_effect=lambda s,f:handlers.update({s:f})), \
                 patch.object(equalizer.time, 'monotonic', side_effect=clock.monotonic), \
                 patch.object(equalizer.selectors, 'DefaultSelector', Selector), \
                 patch.object(equalizer.os, 'read', return_value=tone), \
                 patch.object(equalizer.os, 'set_blocking'), \
                 patch.object(control, 'RUNTIME', Path(tmp)), \
                 patch.object(control, 'settings', return_value=dict(equalizer=True)), \
                 patch.object(control, 'runtime', return_value=dict(suspended=False)), \
                 patch.object(control, 'equalizer_frame', side_effect=frame), \
                 patch.object(equalizer, 'restore'), \
                 patch.object(equalizer.subprocess, 'Popen', return_value=Capture()):
                equalizer.run()
        self.assertLess(frames[-1]-frames[0], .21)
        self.assertTrue(all(.015 <= b-a <= .018 for a,b in zip(frames,frames[1:])), frames)


class WorkerTest(unittest.TestCase):
    def test_pcm_frame_and_sigterm_cleanup(self):
        handlers, frames, restored = {}, [], []
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, 'rb', buffering=0)
        tone = (.4*np.sin(2*np.pi*100*np.arange(2048)/48000)).astype('<f4')
        # Write a complete small block; fit in a pipe without a reader thread.
        os.write(write_fd, tone.tobytes())
        os.close(write_fd)

        class Capture:
            stdout = stream
            terminated = False
            def terminate(self):
                self.terminated = True
            def wait(self, timeout=None):
                return 0

        capture = Capture()
        def frame(prefs, mem, rgb, pixels=None):
            frames.append(rgb)
            self.assertEqual(len(pixels), 20)
            self.assertGreater(len(set(map(tuple,pixels))), 1)
            handlers[signal.SIGTERM](None, None)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(signal, 'signal', side_effect=lambda sig, fn: handlers.update({sig:fn})), \
                 patch.object(control, 'RUNTIME', Path(tmp)), \
                 patch.object(control, 'settings', return_value=dict(equalizer=True)), \
                 patch.object(control, 'runtime', return_value=dict(suspended=False)), \
                 patch.object(control, 'equalizer_frame', side_effect=frame), \
                 patch.object(equalizer, 'restore', side_effect=lambda: restored.append(True)), \
                 patch.object(equalizer.subprocess, 'Popen', return_value=capture) as spawn:
                equalizer.run()
        self.assertEqual(len(frames), 1)
        self.assertGreater(frames[0][0], 100)
        self.assertEqual(frames[0].index(max(frames[0])), 0)
        self.assertTrue(capture.terminated)
        self.assertTrue(stream.closed)
        self.assertEqual(restored, [True])
        self.assertIn('--device=@DEFAULT_MONITOR@', spawn.call_args.args[0])
        latency = next(arg for arg in spawn.call_args.args[0]
                       if arg.startswith('--latency-msec='))
        self.assertLessEqual(int(latency.split('=')[1]), 10)

    def test_disabled_worker_never_opens_audio(self):
        handlers = {}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(signal, 'signal', side_effect=lambda sig, fn: handlers.update({sig:fn})), \
                 patch.object(control, 'RUNTIME', Path(tmp)), \
                 patch.object(control, 'settings', return_value=dict(equalizer=False)), \
                 patch.object(control, 'runtime', return_value=dict(suspended=False)), \
                 patch.object(equalizer, 'restore'), \
                 patch.object(equalizer.time, 'sleep', side_effect=lambda _: handlers[signal.SIGTERM](None,None)), \
                 patch.object(equalizer.subprocess, 'Popen') as spawn:
                equalizer.run()
                spawn.assert_not_called()
