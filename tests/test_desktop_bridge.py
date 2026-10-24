import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DesktopModelTest(unittest.TestCase):
    def test_widget_opens_the_same_desktop_entry_without_a_device_rpc(self):
        import control
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(control, 'CONFIG', Path(folder)), \
             patch.object(control, 'RUNTIME', Path(folder) / 'runtime'), \
             patch('firmware.read_job', return_value={'stage': 'idle'}), \
             patch('subprocess.Popen') as launch, \
             patch('usb_transport.client', side_effect=AssertionError('device RPC')):
            result = control.dispatch(['desktop-open'])
            self.assertTrue(result['ok'])
            self.assertEqual(Path(launch.call_args.args[0][1]).name, 'desktop.py')
            self.assertFalse(launch.call_args.kwargs.get('shell', False))

    def test_demo_never_dispatches_changes_to_a_running_real_device(self):
        import desktop_bridge
        prefs = dict(controller={'mac': 'aabbccddeeff', 'count': 20}, sections=[],
                     equalizer_palette='ocean', equalizer_decay_ms=320)
        before = copy.deepcopy(prefs)
        with patch('control.settings', return_value=prefs), \
             patch('desktop_bridge.DeviceBackend.command', side_effect=AssertionError('physical command')):
            model = desktop_bridge.DesktopModel()
            model.set_demo(True, capture=False)
            model.command('brightness', ['190'])
            model.command('setting', ['equalizer_palette', 'fire'])
            model.command('power', ['false'])
            data = model.poll()
            self.assertEqual(data['target'], 'demo')
            self.assertEqual(data['state']['bri'], 190)
            self.assertFalse(data['state']['on'])
            self.assertEqual(data['settings']['equalizer_palette'], 'fire')
            self.assertEqual(prefs, before)
            with self.assertRaises(ValueError):
                model.command('enroll', ['/dev/ttyUSB0'])
            model.close()

    def test_private_setup_password_is_not_forwarded_as_a_cli_argument(self):
        import desktop_bridge
        backend = desktop_bridge.DeviceBackend()
        with patch('desktop_bridge.subprocess.run', side_effect=AssertionError('secret in argv')):
            with self.assertRaises(ValueError):
                backend.command(['receiver-configure', 'wifi-secret'])

    def test_normal_control_error_is_reported_without_retrying_a_mutation(self):
        import desktop_bridge
        from types import SimpleNamespace
        with patch('desktop_bridge.subprocess.run', return_value=SimpleNamespace(
                returncode=1, stdout='', stderr='Control error: disconnected')) as run:
            with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                desktop_bridge.DeviceBackend().command(['power', 'true'])
            self.assertEqual(run.call_count, 1)
            self.assertFalse(run.call_args.kwargs.get('shell', False))


if __name__ == '__main__':
    unittest.main()
