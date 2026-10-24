from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class NativeHostTest(unittest.TestCase):
    def test_unsmoothed_features_do_not_depend_on_previous_audio_or_ui_tuning(self):
        import equalizer,numpy as np
        source=equalizer.AudioFeatures()
        samples=.1*np.sin(2*np.pi*80*np.arange(2048)/48000)
        first=source.process(samples)
        source.process(np.zeros(2048))
        second=source.process(samples)
        self.assertEqual(first,second)
        self.assertAlmostEqual(first['rms'],.0708,delta=.002)
        self.assertGreater(first['bass'],.08)
        self.assertEqual(source.process(np.zeros(2048)),{'rms':0,'bass':0})

    def test_volume_and_notification_leave_native_audio_flowing_without_rgb(self):
        import control,layout,time
        with tempfile.TemporaryDirectory() as folder,patch.object(control,'CONFIG',Path(folder)),patch.object(control,'RUNTIME',Path(folder)):
            prefs=control.DEFAULTS | dict(controller={'mac':'680947485628','backend':'wesp','count':2},
                sections=layout.legacy(2),equalizer=True)
            control.write_json(control.CONFIG/'settings.json',prefs)
            mem=dict(ids=[1],volumeUntil=time.time()+2,suspended=False,base={},equalizerBase={'0':{'col':[[1,2,3]],'bri':100,'fx':0}},notifyStarted=time.time())
            commands=[]
            def client(payload=None,pixels=None,native=None,**kw):
                if native is not None:commands.append(native);return True
                if pixels is not None:raise AssertionError('native path rendered RGB on PC')
                return dict(on=True,bri=100,seg=[dict(id=0,start=0,stop=2,col=[[1,2,3]],bri=255,fx=0)])
            with patch('usb_transport.client',side_effect=client),patch.object(control,'kde_color',return_value=[1,2,3]):
                self.assertTrue(control.equalizer_frame(prefs,mem,None,features={'rms':.2,'bass':.1}))
                control.apply(prefs,mem)
            self.assertEqual(commands[0]['action'],'audio')
            self.assertEqual(commands[0]['rms'],.2)
            self.assertEqual(commands[1]['action'],'apply')
            self.assertTrue(commands[1]['notification'])


if __name__=='__main__':unittest.main()
