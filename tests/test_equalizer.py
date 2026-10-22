import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

class SpectrumTest(unittest.TestCase):
    def analyzer(self):
        import equalizer
        return equalizer.Spectrum()

    def test_silence_is_black(self):
        self.assertEqual(self.analyzer().process(np.zeros(2048)), [0, 0, 0])

    def test_noise_gate_and_dc_offset(self):
        self.assertEqual(self.analyzer().process(np.full(2048, .2)), [0,0,0])
        signal = .0001 * np.sin(2*np.pi*100*np.arange(2048)/48000)
        self.assertEqual(self.analyzer().process(signal), [0,0,0])

    def test_invalid_samples_fail_explicitly(self):
        for values in (np.zeros(10), np.full(2048, np.nan), np.full(2048, np.inf)):
            with self.assertRaises(ValueError):
                self.analyzer().process(values)

    def test_tones_select_frequency_band(self):
        for band, hz in enumerate((100, 1000, 6000)):
            signal = .4 * np.sin(2 * np.pi * hz * np.arange(2048) / 48000)
            rgb = self.analyzer().process(signal)
            self.assertEqual(rgb.index(max(rgb)), band)
            self.assertGreater(max(rgb), 100)

    def test_release_fades_and_reaches_black(self):
        analyzer = self.analyzer()
        tone = .4*np.sin(2*np.pi*100*np.arange(2048)/48000)
        peak = analyzer.process(tone)[0]
        release = analyzer.process(np.zeros(2048))[0]
        self.assertGreater(release, 0)
        self.assertLess(release, peak)
        for _ in range(80):
            rgb = analyzer.process(np.zeros(2048))
        self.assertEqual(rgb, [0, 0, 0])


class SpatialTest(unittest.TestCase):
    def test_attack_smoothing_is_independent_from_decay(self):
        fast=self.analyzer()
        slow=self.analyzer()
        fast.set_attack(0)
        slow.set_attack(200)
        tone=.4*np.sin(2*np.pi*100*np.arange(2048)/48000)
        fast.process(tone)
        slow.process(tone)
        self.assertGreater(fast.level,.9)
        self.assertLess(slow.level,.25)
        self.assertEqual(fast.release,slow.release)
        previous=(slow.reference,slow.level)
        slow.set_attack(80)
        self.assertEqual((slow.reference,slow.level),previous)

    def test_sensitivity_changes_level_even_after_auto_gain_settles(self):
        low=self.analyzer()
        high=self.analyzer()
        low.set_response(50,6)
        high.set_response(150,6)
        tone=.1*np.sin(2*np.pi*100*np.arange(2048)/48000)
        for _ in range(300):
            low.process(tone)
            high.process(tone)
        self.assertGreater(high.level,low.level*2)

    def test_noise_gate_is_adjustable_without_resetting_auto_gain(self):
        low=self.analyzer()
        high=self.analyzer()
        low.set_response(100,0)
        high.set_response(100,30)
        tone=.01*np.sin(2*np.pi*100*np.arange(2048)/48000)
        self.assertTrue(any(any(p) for p in low.process(tone)))
        self.assertEqual(high.process(tone),[[0,0,0]]*20)
        previous=(low.reference,low.level)
        low.set_response(120,6)
        self.assertEqual((low.reference,low.level),previous)

    def test_smooth_profile_preserves_the_previous_envelope(self):
        import equalizer
        analyzer = equalizer.SpatialSpectrum(profile='smooth')
        tone = .4*np.sin(2*np.pi*100*np.arange(2048)/48000)
        analyzer.process(tone)
        self.assertAlmostEqual(analyzer.level, .65)
        analyzer.process(np.zeros(2048))
        self.assertAlmostEqual(analyzer.level, .559)

    def test_invalid_profile_is_reported_instead_of_silently_switching(self):
        import equalizer
        with self.assertRaises(ValueError):
            equalizer.SpatialSpectrum(profile='typo')

    def test_default_profile_rises_fast_but_falls_smoothly(self):
        analyzer = self.analyzer()
        tone = .4*np.sin(2*np.pi*100*np.arange(2048)/48000)
        analyzer.process(tone)
        peak = analyzer.level
        self.assertGreaterEqual(peak, .9, 'a strong beat must rise in one frame')
        for _ in range(6):  # 100 ms at the existing 60 Hz output rate
            analyzer.process(np.zeros(2048))
        self.assertGreater(analyzer.level, peak*.3, 'avoid abrupt flickering decay')
        self.assertLess(analyzer.level, peak*.5, 'do not hold the previous peak')

    def test_decay_setting_changes_fall_without_slowing_attack(self):
        import equalizer
        tone = .4*np.sin(2*np.pi*100*np.arange(2048)/48000)
        short = equalizer.SpatialSpectrum(decay_ms=100)
        long = equalizer.SpatialSpectrum(decay_ms=400)
        short.process(tone)
        long.process(tone)
        self.assertAlmostEqual(short.level, long.level)
        for _ in range(6):
            short.process(np.zeros(2048))
            long.process(np.zeros(2048))
        self.assertLess(short.level, .12)
        self.assertGreater(long.level, .5)

    def test_live_decay_change_preserves_auto_gain_and_current_level(self):
        analyzer = self.analyzer()
        tone = .1*np.sin(2*np.pi*100*np.arange(2048)/48000)
        analyzer.process(tone)
        previous = (analyzer.reference, analyzer.level)
        analyzer.set_decay(400)
        self.assertEqual((analyzer.reference, analyzer.level), previous)
        with self.assertRaises(ValueError):
            analyzer.set_decay(0)


    def test_loud_continuous_signal_leaves_headroom_after_adaptation(self):
        analyzer = self.analyzer()
        tone = .8*np.sin(2*np.pi*100*np.arange(2048)/48000)
        for _ in range(180):
            pixels = analyzer.process(tone)
        self.assertGreater(analyzer.level, .3)
        self.assertLess(analyzer.level, .85)
        self.assertLess(sum(any(p) for p in pixels[:10]), 10)

    def test_same_music_at_different_pc_levels_keeps_similar_dynamics(self):
        tone = np.sin(2*np.pi*100*np.arange(2048)/48000)
        tracks = []
        for gain in (.08, .8):
            analyzer = self.analyzer()
            for _ in range(600):
                analyzer.process(gain*tone)
            levels = []
            for envelope in (.25, .5, 1.0, .35):
                for _ in range(8):
                    analyzer.process(gain*envelope*tone)
                levels.append(analyzer.level)
            self.assertGreater(max(levels)-min(levels), .2)
            tracks.append(levels)
        self.assertLess(max(abs(a-b) for a,b in zip(*tracks)), .12)

    def test_silence_does_not_amplify_noise_after_loud_track(self):
        analyzer = self.analyzer()
        tone = np.sin(2*np.pi*100*np.arange(2048)/48000)
        for _ in range(180):
            analyzer.process(.8*tone)
        for _ in range(1200):
            pixels = analyzer.process(.0001*tone)
        self.assertEqual(pixels, [[0,0,0]]*20)

    def test_each_strip_can_be_reversed_independently(self):
        import equalizer
        pixels = [[i,0,0] for i in range(20)]
        first = equalizer.orient_pixels(pixels, True, False)
        second = equalizer.orient_pixels(pixels, False, True)
        self.assertEqual(first, pixels[:10][::-1]+pixels[10:])
        self.assertEqual(second, pixels[:10]+pixels[10:][::-1])
        self.assertEqual(pixels, [[i,0,0] for i in range(20)])

    def analyzer(self):
        import equalizer
        return equalizer.SpatialSpectrum()

    def test_bass_makes_contiguous_bar_on_both_strips(self):
        tone = .4*np.sin(2*np.pi*100*np.arange(2048)/48000)
        pixels = self.analyzer().process(tone)
        self.assertEqual(len(pixels), 20)
        lit = [any(p) for p in pixels[:10]]
        self.assertGreater(sum(lit), 6)
        self.assertEqual(lit, sorted(lit, reverse=True))
        self.assertEqual(pixels[:10], pixels[10:])

    def test_high_tone_does_not_spawn_disconnected_red_pixels(self):
        tone = .4*np.sin(2*np.pi*9000*np.arange(2048)/48000)
        pixels = self.analyzer().process(tone)
        lit = [any(p) for p in pixels[:10]]
        self.assertGreater(sum(lit), 0)
        self.assertEqual(lit, sorted(lit, reverse=True))
        self.assertEqual(pixels[:10], pixels[10:])

    def test_no_white_dot_after_a_weak_beat(self):
        analyzer = self.analyzer()
        tone = .03*np.sin(2*np.pi*100*np.arange(2048)/48000)
        analyzer.process(tone)
        for _ in range(36):
            pixels = analyzer.process(np.zeros(2048))
        self.assertEqual(pixels, [[0,0,0]]*20)

    def test_stronger_beats_fill_more_pixels_and_tone_is_stable(self):
        tone = np.sin(2*np.pi*100*np.arange(2048)/48000)
        quiet = self.analyzer().process(.025*tone)
        loud = self.analyzer().process(.25*tone)
        self.assertLess(sum(any(p) for p in quiet), sum(any(p) for p in loud))
        analyzer = self.analyzer()
        for _ in range(120):
            previous = analyzer.process(.1*tone)
        self.assertEqual(analyzer.process(.1*tone), previous)

    def test_repeated_beats_have_repeated_peaks_and_dark_gaps(self):
        analyzer = self.analyzer()
        tone = .2*np.sin(2*np.pi*100*np.arange(2048)/48000)
        heights = []
        for frame in range(120):
            pixels = analyzer.process(tone if frame % 30 < 3 else np.zeros(2048))
            heights.append(sum(sum(p) for p in pixels[:10]))
        self.assertGreater(heights[2], heights[15]*3)
        self.assertEqual(heights[29], 0)
        self.assertLess(abs(heights[2]-heights[32]), heights[2]*.02)

    def test_silence_and_release(self):
        analyzer = self.analyzer()
        self.assertEqual(analyzer.process(np.zeros(2048)), [[0,0,0]]*20)
        tone = .4*np.sin(2*np.pi*100*np.arange(2048)/48000)
        analyzer.process(tone)
        self.assertTrue(any(any(p) for p in analyzer.process(np.zeros(2048))))
        for _ in range(180):
            pixels = analyzer.process(np.zeros(2048))
        self.assertEqual(pixels, [[0,0,0]]*20)

    def test_levels_are_not_one_color_for_whole_strip(self):
        tone = .06*np.sin(2*np.pi*100*np.arange(2048)/48000)
        pixels = self.analyzer().process(tone)
        self.assertGreater(len(set(map(tuple,pixels))), 1)
