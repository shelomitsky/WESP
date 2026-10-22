import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import notification_fx as fx


class NotificationEffectsTest(unittest.TestCase):
    def setUp(self):
        self.prefs=dict(notify=True,notify_style='flash',notify_color='#8000ff',notify_strength=60)
        self.mem=dict(ids=[42],notifyStarted=100)
        self.sections=[dict(start=1,count=3,reverse=True)]
        self.frame=[[10,20,30] for _ in range(5)]

    def test_two_flashes_have_two_peaks_and_then_restore_exact_base(self):
        for elapsed in (.4,1.2):
            output=fx.overlay(self.frame,self.sections,self.prefs,self.mem,100+elapsed)
            self.assertNotEqual(output[1],self.frame[1])
            self.assertEqual(output[1],output[2])
        for elapsed in (0,.8,1.6,2.5):
            self.assertEqual(fx.overlay(self.frame,self.sections,self.prefs,self.mem,100+elapsed),self.frame)
        self.assertFalse(fx.active(self.prefs,self.mem,102))
        self.assertEqual(self.frame,[[10,20,30]]*5)

    def test_only_configured_pixels_are_changed(self):
        output=fx.overlay(self.frame,self.sections,self.prefs,self.mem,100.4)
        self.assertEqual(output[0],self.frame[0])
        self.assertEqual(output[4],self.frame[4])

    def test_pulse_tint_and_pixel_are_distinct_and_close_stops_them(self):
        for style in ('pulse','tint','pixel'):
            prefs=dict(self.prefs,notify_style=style)
            output=fx.overlay(self.frame,self.sections,prefs,self.mem,100.6)
            count=sum(a!=b for a,b in zip(output,self.frame))
            self.assertEqual(count,1 if style=='pixel' else 3)
            self.assertFalse(fx.active(prefs,dict(self.mem,ids=[]),100.6))
            self.assertFalse(fx.active(dict(prefs,notify=False),self.mem,100.6))

    def test_preview_is_temporary_and_does_not_need_a_fake_notification_id(self):
        mem=dict(ids=[],notifyPreviewStart=100,notifyPreviewUntil=103)
        prefs=dict(self.prefs,notify_style='tint')
        self.assertTrue(fx.active(prefs,mem,101))
        self.assertFalse(fx.active(prefs,mem,104))
        self.assertEqual(mem['ids'],[])
