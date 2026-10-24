import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


class PulseTest(unittest.TestCase):
    def test_continuous_bass_does_not_become_a_train_of_beats(self):
        from music import BeatPulse
        pulse=BeatPulse()
        values=[pulse.process(.2,.006,now=i/60) for i in range(120)]
        self.assertGreater(values[0],.8)
        self.assertLess(max(values[60:]),.05)
        for i in range(120,150): pulse.process(0,.006,now=i/60)
        self.assertGreater(pulse.process(.2,.006,now=2.5),.8)

    def test_noise_silence_and_clock_pause_do_not_preserve_an_old_accent(self):
        from music import BeatPulse
        pulse=BeatPulse()
        self.assertEqual(pulse.process(.001,.006,now=0),0)
        pulse.process(.2,.006,now=.2)
        self.assertLess(pulse.process(0,.006,now=3),.001)
        for value in (float('nan'),float('inf'),-.1):
            with self.assertRaises(ValueError): pulse.process(value,.006,now=4)

    def test_renderer_keeps_reverse_gaps_and_live_analyzer_history(self):
        from music import Renderer
        sections=[dict(id='a',name='A',start=1,count=4,reverse=False,placement='left'),
                  dict(id='b',name='B',start=6,count=4,reverse=True,placement='right')]
        tone=.2*np.sin(2*np.pi*100*np.arange(2048)/48000)
        prefs=dict(music_style='pulse',equalizer_palette='ocean')
        renderer=Renderer()
        frame=renderer.frame(tone,prefs,sections,11,now=0)
        self.assertEqual(frame[1:5],list(reversed(frame[6:10])))
        for i in (0,5,10):self.assertEqual(frame[i],[0,0,0])
        analyzer=renderer.analyzer
        prefs['equalizer_decay_ms']=500
        renderer.frame(tone,prefs,sections,11,now=.1)
        self.assertIs(renderer.analyzer,analyzer)
        self.assertNotEqual(analyzer.reference,.1)


if __name__=='__main__': unittest.main()
