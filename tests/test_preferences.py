"""Desktop tuning contracts shared by scenes, saved presets and preview."""
import importlib
import importlib.util
from pathlib import Path
import unittest

import control
import effects_config
import layout
import manage
import preset_store
import preview
import scenes


class PreferencesTest(unittest.TestCase):
    def preferences(self):
        self.assertIsNotNone(importlib.util.find_spec('preferences'),
                             'Shared preference rules must be importable without the command layer')
        return importlib.import_module('preferences')

    def test_shared_validation_keeps_desktop_input_rules_and_control_entry_points(self):
        rules = self.preferences()
        self.assertIs(control.DEFAULTS, rules.DEFAULTS)
        self.assertIs(control.validate_tuning, rules.validate_tuning)
        self.assertIs(control.validate_decay_ms, rules.validate_decay_ms)
        for key, raw, expected in (
                ('equalizer_decay_ms', '080', 80), ('equalizer_sensitivity', '125', 125),
                ('notify_color', '#AB12EF', '#ab12ef'), ('music_repeat_ms', '0', 0),
                ('music_style', 'pulse', 'pulse'), ('equalizer_palette', 'violet', 'violet')):
            with self.subTest(key=key):
                self.assertEqual(rules.validate_value(key, raw), expected)
        for key, bad in (('equalizer_decay_ms', True), ('equalizer_decay_ms', 79),
                         ('equalizer_sensitivity', 125.0), ('equalizer_gate', '-1'),
                         ('music_repeat_ms', 179), ('notify_color', '#12345g')):
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                rules.validate_value(key, bad)
        with self.assertRaises(KeyError):
            rules.validate_value('controller', {'mac': '001122334455'})

    def test_shared_rules_keep_scene_and_preset_fields_separate(self):
        rules = self.preferences()
        self.assertEqual(scenes.TUNING, rules.RESPONSE_FIELDS)
        self.assertEqual(preset_store.FIELDS, rules.MUSIC_FIELDS)
        saved = preset_store.edit(dict(equalizer_sensitivity='125', equalizer_decay_ms='310'), 'save', 'Evening')
        item = saved['native_presets'][0]
        self.assertEqual(item['settings']['equalizer_sensitivity'], '125')
        self.assertEqual(item['settings']['equalizer_decay_ms'], '310')
        loaded = preset_store.edit(saved, 'load', item['id'])
        self.assertEqual(loaded['equalizer_sensitivity'], 125)
        self.assertEqual(loaded['equalizer_decay_ms'], 310)
        demo = preview.DemoSession()
        demo.configure('equalizer_decay_ms', '310')
        self.assertEqual(demo.prefs['equalizer_decay_ms'], 310)
        self.assertEqual(demo.prefs['music_custom']['equalizer_decay_ms'], 310)

    def test_native_wire_config_still_rejects_desktop_numeric_strings(self):
        self.preferences()
        document = effects_config.from_preferences(dict(controller={'count': 2}, sections=layout.legacy(2)))
        document['presets'][0]['sensitivity'] = '125'
        document['revision'] = effects_config.revision(document)
        with self.assertRaisesRegex(ValueError, 'Invalid native effect integer'):
            effects_config.validate(document, 2)

    def test_shared_rules_are_in_the_installed_payload(self):
        self.preferences()
        payload = manage.payloads()
        self.assertIn('preferences.py', {path.name for path in payload})
        content = next(data for path, (data, mode) in payload.items() if path.name == 'preferences.py')
        self.assertEqual(content, (Path(control.__file__).parent/'preferences.py').read_bytes())


if __name__ == '__main__':
    unittest.main()
