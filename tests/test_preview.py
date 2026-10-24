import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PreviewTest(unittest.TestCase):
    def test_snapshot_is_bounded_private_and_rejects_another_controller(self):
        import preview
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'frame.json'
            publisher = preview.Publisher(path)
            self.assertTrue(publisher.publish([[255, 0, 0], [0, 20, 0]], 'aabbccddeeff',
                                              brightness=128, now=10))
            record = preview.read(path, 'aabbccddeeff', now=10.5)
            self.assertEqual(record['pixels'], [[255, 0, 0], [0, 20, 0]])
            self.assertEqual(record['brightness'], 128)
            self.assertFalse(record['stale'])
            self.assertTrue(preview.read(path, 'aabbccddeeff', now=13)['stale'])
            self.assertIsNone(preview.read(path, '112233445566', now=10.5))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(publisher.publish([[0, 0, 0]], 'aabbccddeeff', now=10.02))
            with self.assertRaises(ValueError):
                publisher.publish([[True, 0, 0]], 'aabbccddeeff', now=11)
            path.write_text('{"pixels": ["invalid"]}')
            self.assertIsNone(preview.read(path, 'aabbccddeeff', now=11))

    def test_demo_tuning_and_shutdown_never_touch_saved_settings_or_hardware(self):
        import preview
        prefs = dict(equalizer_decay_ms=250, equalizer_sensitivity=100,
                     equalizer_gate=6, equalizer_attack_ms=0, equalizer_palette='classic',
                     controller={'mac': 'aabbccddeeff', 'count': 99})
        before = copy.deepcopy(prefs)
        with patch('serial.Serial', side_effect=AssertionError('demo opened serial')), \
             patch('socket.create_connection', side_effect=AssertionError('demo opened TCP')), \
             patch('control.write_json', side_effect=AssertionError('demo wrote settings')), \
             patch('usb_transport.client', side_effect=AssertionError('demo sent RPC')):
            session = preview.DemoSession(prefs)
            session.configure('equalizer_sensitivity', 150)
            session.configure('brightness', 60)
            tone = .2 * np.sin(2 * np.pi * 100 * np.arange(2048) / 48000)
            record = session.process(tone)
            self.assertEqual(record['target'], 'demo')
            self.assertEqual(len(record['pixels']), 20)
            self.assertTrue(any(any(pixel) for pixel in record['pixels']))
            session.configure('on', False)
            self.assertEqual(session.process(tone)['pixels'], [[0, 0, 0]] * 20)
            self.assertEqual(prefs, before)

    def test_publishing_failure_cannot_break_the_transport_sender(self):
        import preview
        with tempfile.TemporaryDirectory() as folder:
            blocked = Path(folder) / 'file'
            blocked.write_text('not a directory')
            publisher = preview.Publisher(blocked / 'frame.json')
            self.assertFalse(publisher.publish([[1, 2, 3]], 'aabbccddeeff', now=10))


if __name__ == '__main__':
    unittest.main()
