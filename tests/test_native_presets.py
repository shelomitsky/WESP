from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class NativePresetTest(unittest.TestCase):
    def test_named_preset_excludes_identity_and_restores_tuning_without_power_commands(self):
        import control
        with tempfile.TemporaryDirectory() as folder,patch.object(control,'CONFIG',Path(folder)),patch.object(control,'RUNTIME',Path(folder)):
            control.write_json(control.CONFIG/'settings.json',dict(music_style='pulse',equalizer_sensitivity=125,
                host='private-host',wifi_password='private-fixture',equalizer=False))
            with patch('usb_transport.client',side_effect=AssertionError('No selected device, no commands')):
                saved=control.execute(['preset-save','Вечер'])['settings']['native_presets'][0]
                self.assertNotIn('private',str(saved))
                self.assertEqual(saved['name'],'Вечер')
                control.execute(['setting','equalizer_sensitivity','90'])
                result=control.execute(['preset-load',saved['id']])['settings']
                self.assertEqual(result['equalizer_sensitivity'],125)
                self.assertEqual(result['music_style'],'pulse')
                self.assertFalse(result['equalizer'])
                self.assertEqual(control.execute(['preset-delete',saved['id']])['settings']['native_presets'],[])

    def test_wallpaper_and_repeat_settings_reject_bad_ranges(self):
        import control
        for key,value in [('music_repeat_ms',100),('wallpaper_timeout_ms',0),('wallpaper_fade_ms',10001)]:
            with self.subTest(key=key),self.assertRaises(ValueError):control.validate_tuning(key,value)
        self.assertEqual(control.validate_tuning('music_repeat_ms','0'),0)
        self.assertEqual(control.validate_tuning('wallpaper_timeout_ms','8000'),8000)


if __name__=='__main__':unittest.main()
