import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import control


class ScenesTest(unittest.TestCase):
    def test_presets_preserve_manual_tuning_palette_and_hardware(self):
        import scenes
        prefs=control.DEFAULTS | dict(equalizer_sensitivity=140,equalizer_decay_ms=310,
            controller={'mac':'aabbccddeeff','count':20},equalizer_palette='violet')
        saved=copy.deepcopy(prefs)
        soft=scenes.preset(prefs,'soft')
        vivid=scenes.preset(soft,'vivid')
        restored=scenes.preset(vivid,'custom')
        self.assertEqual(restored['equalizer_sensitivity'],140)
        self.assertEqual(restored['equalizer_decay_ms'],310)
        self.assertEqual(vivid['controller'],prefs['controller'])
        self.assertEqual(vivid['equalizer_palette'],'violet')
        self.assertEqual(prefs,saved)
        with self.assertRaises(ValueError): scenes.preset(prefs,'unknown')

    def test_legacy_mode_is_inferred_without_changing_the_saved_choice(self):
        import scenes
        self.assertEqual(scenes.mode(dict(equalizer=True,kde=True)),'music')
        self.assertEqual(scenes.mode(dict(equalizer=False,kde=True)),'calm')
        self.assertEqual(scenes.mode(dict(equalizer=False,kde=False)),'manual')

    def test_saved_custom_tuning_cannot_import_hardware_fields(self):
        import scenes
        prefs=control.DEFAULTS | dict(music_custom={'controller':{'mac':'112233445566'}})
        with self.assertRaises(ValueError):scenes.preset(prefs,'custom')

    def test_failed_preset_save_keeps_all_previous_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config').mkdir();(root/'runtime').mkdir()
            with patch.object(control,'CONFIG',root/'config'),patch.object(control,'RUNTIME',root/'runtime'):
                control.write_json(control.CONFIG/'settings.json',dict(equalizer_decay_ms=310,equalizer_sensitivity=140))
                original=(control.CONFIG/'settings.json').read_bytes()
                with patch.object(control,'write_json',side_effect=OSError('disk full')):
                    with self.assertRaises(OSError):control.execute(['music-preset','vivid'])
                self.assertEqual((control.CONFIG/'settings.json').read_bytes(),original)

    def test_volume_expiry_returns_to_the_new_calm_scene_without_old_effect_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config').mkdir();(root/'runtime').mkdir()
            with patch.object(control,'CONFIG',root/'config'),patch.object(control,'RUNTIME',root/'runtime'):
                prefs=control.DEFAULTS | dict(equalizer=True,controller={'mac':'aabbccddeeff','count':2},
                    sections=[dict(id='a',name='A',start=0,count=2,reverse=False,placement='left')])
                control.write_json(control.CONFIG/'settings.json',prefs)
                control.write_json(control.RUNTIME/'state.json',dict(controller_mac='aabbccddeeff',
                    volumeUntil=200,equalizerBase={'0':{'fx':5}},overlayBase={'0':{'fx':5}}))
                state=dict(on=True,bri=100,seg=[dict(id=0,col=[[1,2,3]],fx=5,start=0,stop=2)])
                frames=[];posts=[]
                def send(payload=None,pixels=None,**kw):
                    if pixels is not None:frames.append(pixels)
                    elif payload is not None:posts.append(payload)
                    return state
                with patch.object(control,'device_state',return_value=state), \
                     patch.object(control,'kde_color',return_value=[10,20,30]), \
                     patch('usb_transport.client',side_effect=send):
                    with patch.object(control.time,'time',return_value=100):control.execute(['scene','calm'])
                    self.assertEqual(frames,[])
                    with patch.object(control.time,'time',return_value=201):control.execute(['volume-end'])
                    control.release_equalizer(control.settings(),control.runtime())
                self.assertEqual(frames,[[[10,20,30],[10,20,30]]])
                self.assertEqual(posts,[])

    def test_activity_explains_the_temporary_source_and_current_return_target(self):
        import scenes
        prefs=control.DEFAULTS | dict(equalizer=True)
        mem=dict(volumeUntil=12)
        result=scenes.activity(prefs,mem,dict(on=True),10)
        self.assertEqual((result['effective'],result['base']),('volume','music'))
        self.assertEqual(scenes.activity(prefs,mem,dict(on=False),10)['effective'],'off')

    def test_scene_change_during_volume_does_not_restore_an_old_music_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config').mkdir();(root/'runtime').mkdir()
            with patch.object(control,'CONFIG',root/'config'),patch.object(control,'RUNTIME',root/'runtime'):
                prefs=control.DEFAULTS | dict(equalizer=True,controller={'mac':'aabbccddeeff','count':2},
                    sections=[dict(id='a',name='A',start=0,count=2,reverse=False,placement='left')])
                control.write_json(control.CONFIG/'settings.json',prefs)
                control.write_json(control.RUNTIME/'state.json',dict(controller_mac='aabbccddeeff',
                    volumeUntil=200,equalizerBase={'0':{'fx':5}},overlayBase={'0':{'fx':5}}))
                state=dict(on=False,bri=100,seg=[dict(id=0,col=[[1,2,3]],fx=5,start=0,stop=2)])
                with patch.object(control,'device_state',return_value=state), \
                     patch('usb_transport.client',side_effect=AssertionError('Off was overridden')):
                    control.execute(['scene','calm'])
                self.assertFalse(control.settings()['equalizer'])
                self.assertFalse(control.runtime().get('equalizerBase'))
                self.assertEqual(control.runtime()['volumeUntil'],200)


if __name__=='__main__': unittest.main()
