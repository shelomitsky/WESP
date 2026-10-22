import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import control
import usb_transport


class NotificationControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        (root/'config').mkdir()
        (root/'runtime').mkdir()
        for target,value in [('CONFIG',root/'config'),('RUNTIME',root/'runtime')]:
            p=patch.object(control,target,value)
            p.start()
            self.addCleanup(p.stop)
        self.prefs=control.DEFAULTS | dict(kde=False,controller=dict(mac='021122334455',count=5),
            sections=[dict(id='a',name='A',start=1,count=3,reverse=False,placement='custom')])
        self.mem=dict(controller_mac='021122334455',ids=[42],notifyStarted=100,notifyRendered=True,
                      suspended=False,volumeUntil=0,base={})
        self.state=dict(on=True,bri=128,seg=[dict(id=4,start=0,stop=5,col=[[10,20,30]],bri=128,fx=5)])
        self.posts=[]
        self.frames=[]
        def client(payload=None,pixels=None,**kwargs):
            if pixels is not None:
                self.frames.append(pixels)
                return True
            if payload is not None:
                self.posts.append(payload)
            return self.state
        p=patch.object(usb_transport,'client',side_effect=client)
        p.start()
        self.addCleanup(p.stop)
        self.save()

    def save(self):
        control.write_json(control.CONFIG/'settings.json',self.prefs)
        control.write_json(control.RUNTIME/'state.json',self.mem)

    def test_idle_flash_animates_whole_sections_then_restores_manual_effect(self):
        with patch.object(control.time,'time',return_value=100.4):
            control.execute(['ambient-tick'])
        self.assertEqual(self.frames[-1][0],[0,0,0])
        self.assertNotEqual(self.frames[-1][1],[10,20,30])
        self.assertEqual(self.frames[-1][1],self.frames[-1][2])
        with patch.object(control.time,'time',return_value=102):
            control.execute(['ambient-tick'])
        self.assertEqual(self.posts[-1]['seg'][0]['id'],4)
        self.assertEqual(self.posts[-1]['seg'][0]['fx'],5)
        self.assertNotIn('on',self.posts[-1])

    def test_idle_writer_yields_to_music_and_volume_and_sleep(self):
        original_mem=dict(self.mem)
        original_prefs=dict(self.prefs)
        for changes,prefs in [({'equalizerBase':{'4':{'fx':5}}},{'equalizer':True}),
                              ({'volumeUntil':200},{}),({'suspended':True},{})]:
            self.mem=original_mem | changes
            self.prefs=original_prefs | prefs
            self.save()
            with patch.object(control.time,'time',return_value=100.4):
                control.execute(['ambient-tick'])
        self.assertEqual(self.frames,[])
        self.assertEqual(self.posts,[])

    def test_music_overlay_uses_the_same_whole_strip_effect(self):
        prefs=self.prefs | dict(equalizer=True,notify_style='tint')
        mem=self.mem | dict(equalizerBase={'4':{'fx':5}})
        base=[[10,20,30] for _ in range(5)]
        with patch.object(control.time,'time',return_value=100.4):
            self.assertTrue(control.equalizer_frame(prefs,mem,[1,2,3],pixels=base))
        self.assertEqual(self.frames[-1][0],base[0])
        self.assertEqual(self.frames[-1][4],base[4])
        self.assertNotEqual(self.frames[-1][1],base[1])
        self.assertEqual(self.frames[-1][1],self.frames[-1][2])
        self.assertEqual(base,[[10,20,30]]*5)

    def test_preview_does_not_create_counter_or_wake_off_lighting(self):
        self.mem['ids']=[]
        self.save()
        with patch.object(control.time,'time',return_value=100):
            result=control.execute(['notify-preview'])
        self.assertEqual(result['notifications'],0)
        self.assertEqual(control.runtime()['ids'],[])
        self.state['on']=False
        before=len(self.frames)
        with self.assertRaises(ValueError):
            control.execute(['notify-preview'])
        self.assertEqual(len(self.frames),before)
        self.assertEqual(self.posts,[])

    def test_notification_during_volume_starts_after_volume_finishes(self):
        self.mem['volumeUntil']=102
        self.save()
        with patch.object(control.time,'time',return_value=100):
            control.execute(['notify-add','43'])
        self.assertEqual(control.runtime()['notifyStarted'],102)

    def test_burst_keeps_running_flash_instead_of_resetting_it_to_zero(self):
        with patch.object(control.time,'time',return_value=100.3):
            control.execute(['notify-add','43'])
        self.assertEqual(control.runtime()['notifyStarted'],100)
        self.assertEqual(control.runtime()['ids'],[42,43])
