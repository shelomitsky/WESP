import os
from pathlib import Path
import socket
import struct
import tempfile
import unittest
from unittest.mock import patch

import realtime_protocol as rt

MAC='680947485628'

class MailboxTest(unittest.TestCase):
    def test_latest_features_are_pinned_fresh_and_private(self):
        from feature_preview import Writer,Reader
        with tempfile.TemporaryDirectory() as directory:
            writer=Writer(directory);self.addCleanup(writer.close)
            reader=Reader(directory);self.addCleanup(reader.close)
            stamp=rt.now_ns()
            for value in (100,200,300):writer.publish(rt.pack_local(MAC,20,stamp,value,value))
            self.assertEqual(reader.read(MAC,20,stamp),(MAC,20,stamp,300,300))
            self.assertEqual((Path(directory)/'audio-preview.bin').stat().st_mode&0o777,0o600)
            self.assertIsNone(reader.read('a0b7652d2050',20,stamp))
            self.assertIsNone(reader.read(MAC,10,stamp))
            self.assertIsNone(reader.read(MAC,20,stamp+121_000_000))
            self.assertIsNone(reader.read(MAC,20,stamp-1))
            writer.close();self.assertIsNone(reader.read(MAC,20,stamp))

    def test_torn_record_replacement_and_older_writer_close(self):
        from feature_preview import Writer,Reader
        with tempfile.TemporaryDirectory() as directory:
            first=Writer(directory);self.addCleanup(first.close)
            reader=Reader(directory);self.addCleanup(reader.close);stamp=rt.now_ns()
            first.publish(rt.pack_local(MAC,20,stamp,100,100))
            self.assertIsNotNone(reader.read(MAC,20,stamp))
            first.mapping[:8]=struct.pack('<Q',3)
            self.assertIsNone(reader.read(MAC,20,stamp),'in-progress update must not become a frame')
            second=Writer(directory);self.addCleanup(second.close)
            second.publish(rt.pack_local(MAC,20,stamp,200,200));first.close()
            self.assertEqual(reader.read(MAC,20,stamp)[3:],(200,200))
            os.chmod(Path(directory)/'audio-preview.bin',0o644)
            self.assertIsNone(reader.read(MAC,20,stamp),'ignore a mailbox with nonprivate permissions')

    def test_preview_failure_never_blocks_or_fails_audio_delivery(self):
        import realtime_producer as producer
        with tempfile.TemporaryDirectory() as directory:
            listener=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);self.addCleanup(listener.close)
            listener.bind(str(Path(directory)/'audio.sock'))
            p=producer.Publisher(directory,dict(mac=MAC,count=20));self.addCleanup(p.close)
            self.assertTrue(hasattr(p,'preview'),'audio publisher needs the optional feature mirror')
            with patch.object(p.preview,'publish',side_effect=OSError('preview unavailable')):
                self.assertTrue(p.publish(dict(rms=.2,bass=.3),rt.now_ns()))
            self.assertEqual(len(listener.recv(100)),24)

class FeaturesTest(unittest.TestCase):
    def test_normal_loud_pcm_keeps_legacy_bass_energy_above_one(self):
        import equalizer,numpy as np
        samples=.9*np.sin(2*np.pi*100*np.arange(2048)/48000)
        analyzer=equalizer.SpatialSpectrum()
        pixels=analyzer.process(samples)
        self.assertGreater(analyzer.bass,1)
        self.assertTrue(any(any(rgb) for rgb in pixels))

    def test_existing_renderer_uses_features_without_another_fft(self):
        import music
        sections=[dict(id='a',name='A',start=0,count=3,reverse=False,placement='left'),dict(id='b',name='B',start=4,count=3,reverse=True,placement='right')]
        prefs=dict(music_style='pulse',equalizer_palette='ocean')
        renderer=music.Renderer()
        self.assertTrue(hasattr(renderer,'features'),'shared demo renderer must accept precomputed levels')
        with patch('numpy.fft.rfft',side_effect=AssertionError('no duplicate audio analysis')):
            renderer.features(.3,.2,prefs,now=1)
            a=renderer.pixels(prefs,sections,7)
            renderer.features(0,0,prefs,now=1.5)
            b=renderer.pixels(prefs,sections,7)
        self.assertTrue(any(any(rgb) for rgb in a));self.assertLess(sum(map(sum,b)),sum(map(sum,a)))
        self.assertEqual(a[:3],list(reversed(a[4:])));self.assertEqual(a[3],[0,0,0])
        for level in (float('nan'),-1,2):
            with self.assertRaises(ValueError):renderer.features(level,.1,prefs,now=2)

if __name__=='__main__':unittest.main()
