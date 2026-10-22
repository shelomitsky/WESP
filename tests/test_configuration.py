import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import control
import usb_transport


class ConfigurationTest(unittest.TestCase):
    def test_palette_saves_offline_and_rejects_unknown_choice(self):
        self.assertEqual(control.settings()['equalizer_palette'],'classic')
        with patch.object(usb_transport,'client',side_effect=AssertionError('unexpected USB')):
            for palette in ('classic','fire','ocean','violet','rainbow','wallpaper'):
                control.execute(['setting','equalizer_palette',palette])
                self.assertEqual(control.settings()['equalizer_palette'],palette)
        before=(self.config/'settings.json').read_text()
        with self.assertRaises(ValueError):
            control.execute(['setting','equalizer_palette','missing'])
        self.assertEqual((self.config/'settings.json').read_text(),before)

    def test_tuning_saves_offline_and_invalid_values_leave_it_untouched(self):
        with patch.object(usb_transport,'client',side_effect=AssertionError('unexpected USB')):
            for key,value in [('equalizer_sensitivity','125'),('equalizer_gate','9'),('equalizer_attack_ms','120'),
                              ('notify_style','pulse'),('notify_color','#AABBCC'),('notify_strength','45')]:
                result=control.execute(['setting',key,value])
                self.assertTrue(result['ok'])
        self.assertEqual(control.settings()['notify_color'],'#aabbcc')
        before=(self.config/'settings.json').read_text()
        for key,value in [('equalizer_sensitivity','0'),('equalizer_gate','31'),('equalizer_attack_ms','301'),
                          ('notify_style','oops'),('notify_color','purple'),('notify_strength','101')]:
            with self.assertRaises(ValueError):
                control.execute(['setting',key,value])
            self.assertEqual((self.config/'settings.json').read_text(),before)

    def test_default_namespace_does_not_inherit_the_legacy_configuration(self):
        legacy=self.root/'xdg/wled-control'
        legacy.mkdir(parents=True)
        (legacy/'settings.json').write_text('{"equalizer":true}')
        env=dict(os.environ,HOME=str(self.root),XDG_CONFIG_HOME=str(self.root/'xdg'))
        env.pop('WLED_CONFIG_DIR',None)
        env.pop('WLED_RUNTIME_DIR',None)
        result=subprocess.run([sys.executable,'-c',
            'import control,json; print(json.dumps(control.settings()))'],
            cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,check=True)
        self.assertFalse(json.loads(result.stdout)['equalizer'])
        self.assertIsNone(json.loads(result.stdout)['controller'])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'config'
        self.config.mkdir()
        self.runtime=self.root/'runtime'
        self.runtime.mkdir()
        self.patches=[patch.object(control,'CONFIG',self.config),
                      patch.object(control,'RUNTIME',self.runtime)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_new_install_is_unconfigured_and_does_not_touch_serial(self):
        with patch.object(usb_transport,'client',side_effect=AssertionError('unexpected USB')):
            result=control.execute(['status'])
        self.assertFalse(result['configured'])
        self.assertIsNone(result['settings']['controller'])

    def test_identity_and_count_are_enrolled_not_embedded(self):
        info=dict(info=dict(mac='021122334455',leds=dict(count=37)),state=dict(on=True,bri=128))
        device=usb_transport.Device('/dev/ttyUSB8',expected_mac='021122334455',led_count=37)
        device.verify_identity(info)
        with self.assertRaises(ValueError):
            device.verify_identity(dict(info=dict(mac='021122334456',leds=dict(count=37))))
        with self.assertRaises(ValueError):
            device.verify_identity(dict(info=dict(mac='021122334455',leds=dict(count=38))))

    def test_inflight_command_cannot_cross_enrollment_identity_boundary(self):
        device=usb_transport.Device('/dev/ttyUSB8',expected_mac='021122334455',led_count=37)
        usb_transport.require_target(dict(controller_mac='021122334455',controller_count=37),device)
        for message in (dict(controller_mac='021122334456',controller_count=37),
                        dict(controller_mac='021122334455',controller_count=20),{}):
            with self.assertRaises(ValueError):
                usb_transport.require_target(message,device)

    def test_layout_validation_is_atomic_and_offline(self):
        selected=dict(port='/dev/ttyUSB8',mac='021122334455',count=37)
        control.write_json(self.config/'settings.json',dict(controller=selected))
        before=(self.config/'settings.json').read_text()
        with self.assertRaises(ValueError):
            control.execute(['layout',json.dumps([dict(id='a',name='A',start=0,count=38,reverse=False,placement='left')])])
        self.assertEqual((self.config/'settings.json').read_text(),before)
        valid=[dict(id='a',name='A',start=0,count=37,reverse=True,placement='left')]
        with patch.object(usb_transport,'client',side_effect=AssertionError('unexpected USB')):
            control.execute(['layout',json.dumps(valid)])
        self.assertEqual(control.settings()['sections'],valid)

    def test_another_device_cannot_inherit_effect_snapshot(self):
        control.write_json(self.config/'settings.json',dict(controller=dict(mac='021122334455')))
        control.write_json(self.runtime/'state.json',dict(controller_mac='021122334456',
                            equalizerBase={'4':dict(fx=9)},base={'4':dict(fx=9)},ids=[42]))
        mem=control.runtime()
        self.assertFalse(mem.get('equalizerBase'))
        self.assertEqual(mem['ids'],[])

    def test_snapshot_captures_noncontiguous_segment_ids(self):
        snapshot=control.base_segments(dict(seg=[dict(id=0),dict(id=4),dict(id=9)]))
        self.assertEqual(set(snapshot),{'0','4','9'})

    def test_enrollment_persists_new_identity_and_disables_music(self):
        selected=dict(port='/dev/ttyUSB8',mac='021122334455',count=37)
        with patch.object(usb_transport,'client',return_value=selected):
            result=control.execute(['enroll','/dev/ttyUSB8'])
        self.assertEqual(result['settings']['controller'],selected)
        self.assertFalse(result['settings']['equalizer'])
        self.assertEqual(result['settings']['sections'][0]['count'],37)
        self.assertEqual(control.runtime()['controller_mac'],selected['mac'])

    def test_enrollment_forwards_a_pinned_identity_before_any_speed_change(self):
        expected=dict(mac='021122334455',count=20)
        def enroll(**kwargs):
            self.assertEqual(kwargs['expected'],expected)
            return dict(port='/dev/ttyUSB8',**expected)
        with patch.object(usb_transport,'client',side_effect=enroll):
            control.execute(['enroll','/dev/ttyUSB8',json.dumps(expected)])

    def test_off_and_sleep_do_not_send_music_frames(self):
        prefs=control.DEFAULTS | dict(equalizer=True,controller=dict(mac='021122334455',count=1))
        mem=dict(suspended=True,volumeUntil=0)
        with patch.object(usb_transport,'client',side_effect=AssertionError('unexpected pixels')):
            self.assertFalse(control.equalizer_frame(prefs,mem,[0,0,0],pixels=[[1,2,3]]))
        mem['suspended']=False
        with patch.object(control,'device_state',return_value=dict(on=False,bri=128)), \
             patch.object(usb_transport,'client',side_effect=AssertionError('unexpected pixels')):
            self.assertFalse(control.equalizer_frame(prefs,mem,[0,0,0],pixels=[[1,2,3]]))
