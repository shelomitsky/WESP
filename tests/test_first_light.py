import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


class FirstLightTest(unittest.TestCase):
    def prefs(self):
        return dict(controller={'mac':'aabbccddeeff','count':9},sections=[
            dict(id='a',name='Left',start=1,count=3,reverse=False,placement='left'),
            dict(id='b',name='Right',start=5,count=3,reverse=True,placement='right')])

    def test_chase_stays_inside_selected_section_and_respects_direction(self):
        from first_light import Lease
        prefs=self.prefs();before=copy.deepcopy(prefs)
        lease=Lease(prefs,'b','chase',now=0)
        frame=lease.frame(now=0)
        self.assertNotEqual(frame[7],[0,0,0])
        self.assertEqual(frame[5],[0,0,0])
        for i in (0,1,2,3,4,8):self.assertEqual(frame[i],[0,0,0])
        self.assertEqual(prefs,before)
        self.assertIsNone(lease.frame(now=5))

    def test_status_never_renews_deadline_and_changed_layout_or_target_cancels(self):
        from first_light import Lease,active
        prefs=self.prefs();lease=Lease(prefs,'a','rgb',now=10)
        record=lease.record()
        for now in (10,11,12):self.assertTrue(active(prefs,{'firstLight':record},now))
        self.assertFalse(active(prefs,{'firstLight':record},15))
        changed=copy.deepcopy(prefs);changed['sections'][0]['reverse']=True
        self.assertFalse(active(changed,{'firstLight':record},11))
        changed=copy.deepcopy(prefs);changed['controller']['mac']='112233445566'
        self.assertFalse(active(changed,{'firstLight':record},11))
        self.assertFalse(active(prefs,{'firstLight':record,'suspended':True},11))

    def test_rgb_marker_is_dim_bounded_and_uses_known_colors(self):
        from first_light import Lease
        lease=Lease(self.prefs(),'a','rgb',now=0)
        frames=[lease.frame(now=t) for t in (0,1.3,2.6)]
        self.assertEqual([next(p for p in f if any(p)) for f in frames],
                         [[24,0,0],[0,24,0],[0,0,24]])
        self.assertTrue(all(sum(any(p) for p in f)<=3 for f in frames))
        with self.assertRaises(ValueError):Lease(self.prefs(),'missing','chase',now=0)
        with self.assertRaises(ValueError):Lease(self.prefs(),'a','unknown',now=0)


class FirstLightControlTest(unittest.TestCase):
    def setUp(self):
        import control
        self.control=control
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);(root/'config').mkdir();(root/'runtime').mkdir()
        for name,value in [('CONFIG',root/'config'),('RUNTIME',root/'runtime')]:
            item=patch.object(control,name,value);item.start();self.addCleanup(item.stop)
        self.prefs=control.DEFAULTS | FirstLightTest().prefs() | dict(equalizer=True,kde=False)
        self.state=dict(on=True,bri=100,seg=[dict(id=0,start=0,stop=9,col=[[10,20,30]],fx=0)])
        self.frames=[];self.posts=[];self.lease=None
        control.write_json(control.CONFIG/'settings.json',self.prefs)
        def client(payload=None,pixels=None,calibration=None,**kw):
            if calibration:
                if calibration['action']=='start':
                    from first_light import Lease
                    self.lease=Lease(control.settings(),calibration['section'],calibration['style'])
                elif calibration['action']=='stop':self.lease=None
                return self.lease.record() if self.lease else {'active':False}
            if pixels is not None:self.frames.append(pixels);return True
            if payload:
                self.posts.append(payload)
                if 'on' in payload:self.state['on']=payload['on']
            return self.state
        item=patch('usb_transport.client',side_effect=client);item.start();self.addCleanup(item.stop)

    def test_music_volume_and_normal_base_yield_and_off_clears_test(self):
        c=self.control
        with patch.object(c.time,'monotonic',return_value=10):
            c.execute(['first-light','a','chase'])
            prefs,mem=c.settings(),c.runtime()
            self.assertFalse(c.equalizer_frame(prefs,mem,[1,2,3],pixels=[[5,6,7]]*9))
            c.volume(prefs,mem,50);c.apply(prefs,mem)
            self.assertEqual(self.frames,[])
            c.execute(['power','false'])
            self.assertFalse(c.runtime().get('firstLight'))
            self.assertFalse(self.state['on'])
            self.assertFalse(any(post.get('on') is True for post in self.posts))

    def test_expiry_returns_to_current_scene_and_preserves_settings(self):
        c=self.control
        with patch.object(c.time,'monotonic',return_value=10):c.execute(['first-light','a','rgb'])
        with patch.object(c.time,'monotonic',return_value=11):c.execute(['scene','calm'])
        before=(c.CONFIG/'settings.json').read_bytes()
        with patch.object(c.time,'monotonic',return_value=15),patch.object(c,'kde_color',return_value=[4,5,6]):
            c.execute(['ambient-tick'])
        self.assertFalse(c.runtime().get('firstLight'))
        self.assertEqual(self.frames[-1][1:4],[[4,5,6]]*3)
        self.assertEqual((c.CONFIG/'settings.json').read_bytes(),before)
        self.assertFalse(any(post.get('on') is True for post in self.posts))

    def test_off_or_sleep_rejects_start_instead_of_waking_lighting(self):
        c=self.control;self.state['on']=False
        with self.assertRaisesRegex(ValueError,'Turn on'):c.execute(['first-light','a','chase'])
        self.state['on']=True
        c.write_json(c.RUNTIME/'state.json',dict(controller_mac='aabbccddeeff',suspended=True))
        with self.assertRaisesRegex(ValueError,'paused'):c.execute(['first-light','a','chase'])
        self.assertIsNone(self.lease)

    def test_brightness_during_manual_test_restores_current_color_without_power_on(self):
        c=self.control
        self.prefs.update(equalizer=False,kde=False)
        c.write_json(c.CONFIG/'settings.json',self.prefs)
        c.execute(['first-light','a','chase'])
        self.posts.clear()
        c.execute(['brightness','80'])
        self.assertTrue(any(post.get('seg') and post['seg'][0].get('col')==[[10,20,30]] for post in self.posts))
        self.assertIsNone(self.lease)
        self.assertFalse(c.runtime().get('firstLight'))
        self.assertTrue(self.state['on'])
        self.assertFalse(any(post.get('on') is True for post in self.posts))


if __name__=='__main__':unittest.main()
