import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import control,layout,realtime_protocol as rt
MAC='680947485628'

class LocalPreviewTest(unittest.TestCase):
    def test_real_music_preview_reuses_features_without_device_calls_or_capture(self):
        import desktop_bridge
        from feature_preview import Writer
        with tempfile.TemporaryDirectory() as folder,patch.object(control,'RUNTIME',Path(folder)):
            writer=Writer(folder);self.addCleanup(writer.close)
            data=dict(target='device',online=True,native_effects=True,
                settings=dict(controller=dict(mac=MAC,count=20,backend='wesp',connection='wifi'),sections=layout.legacy(20),equalizer=True),
                state=dict(on=True,bri=32),activity=dict(effective='music'))
            model=desktop_bridge.DesktopModel();self.addCleanup(model.close)
            self.assertTrue(hasattr(model,'local_frame'),'real device needs the shared local renderer')
            writer.publish(rt.pack_local(MAC,20,rt.now_ns(),12000,8000))
            with patch.object(model.backend,'command',side_effect=AssertionError('no command for a local frame')),patch.object(model.backend,'setup',side_effect=AssertionError('no ESP frame request')),patch('subprocess.Popen',side_effect=AssertionError('no extra capture')):
                frame=model.local_frame(data)
            self.assertEqual(frame['mac'],MAC);self.assertEqual(frame['source'],'music-local')
            self.assertEqual(frame['brightness'],32);self.assertEqual(len(frame['pixels']),20)
            self.assertTrue(any(any(rgb) for rgb in frame['pixels']))
            for change in ('off','scene','identity','overlay','offline'):
                changed=copy.deepcopy(data)
                if change=='off':changed['state']['on']=False
                elif change=='scene':changed['settings']['equalizer']=False
                elif change=='identity':changed['settings']['controller']['mac']='a0b7652d2050'
                elif change=='overlay':changed['activity']['effective']='volume'
                else:changed['online']=False
                self.assertIsNone(model.local_frame(changed),change)
            writer.publish(rt.pack_local(MAC,20,rt.now_ns()-200_000_000,12000,8000))
            self.assertIsNone(model.local_frame(data),'stale input cannot animate a fresh frame')

    def test_demo_frame_is_the_existing_capture_record(self):
        import desktop_bridge
        from types import SimpleNamespace
        model=desktop_bridge.DesktopModel();self.addCleanup(model.close)
        with patch.object(control,'settings',return_value={}):model.set_demo(True,capture=False)
        record=dict(target='demo',pixels=[[1,2,3]],sequence=1)
        model.audio=SimpleNamespace(record=record,close=lambda:None)
        self.assertTrue(hasattr(model,'local_frame'))
        self.assertIs(model.local_frame(dict(target='demo')),record)
        self.assertIsNone(model.local_frame(dict(target='device')))

if __name__=='__main__':unittest.main()
