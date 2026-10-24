import copy
import unittest


class NativeBenchTest(unittest.TestCase):
    def preferences(self):
        return dict(controller={'mac':'680947485628','count':9},sections=[
            dict(id='a',name='a',start=1,count=3,reverse=False,placement='left'),
            dict(id='b',name='b',start=5,count=3,reverse=True,placement='right')])

    def test_same_cpp_engine_plays_signal_over_live_audio_and_off_cancels(self):
        from effects_config import from_preferences
        from native_sim import Simulator
        config=from_preferences(self.preferences())
        with Simulator(9) as sim:
            self.assertTrue(sim.configure(config))
            sim.power(True)
            self.assertTrue(sim.audio(.2,.2,100))
            self.assertTrue(any(any(pixel) for pixel in sim.frame(100)))
            self.assertTrue(sim.event('notification','0123456789abcdef',0,110))
            sim.audio(0,0,200)
            sim.audio(0,0,500)
            sim.audio(0,0,1000)
            sim.audio(0,0,1800)
            self.assertEqual(sim.frame(1800),[[0,0,0]]*9)
            sim.power(False)
            self.assertFalse(sim.audio(.5,.5,1900))
            self.assertEqual(sim.frame(1900),[[0,0,0]]*9)

    def test_config_rejects_overlap_duplicate_presets_and_revision_tampering(self):
        from effects_config import from_preferences,validate,revision
        config=from_preferences(self.preferences())
        self.assertEqual(validate(config,9),config)
        for change in ('overlap','duplicate','revision','schema'):
            bad=copy.deepcopy(config)
            if change=='overlap':bad['sections'][1][0]=2
            elif change=='duplicate':bad['presets'].append(copy.deepcopy(bad['presets'][0]))
            elif change=='revision':bad['presets'][0]['sensitivity']=150
            else:bad['schema']=True;bad['revision']=revision(bad)
            with self.subTest(change=change),self.assertRaises(ValueError):validate(bad,9)


if __name__=='__main__':unittest.main()
