"""Coherent music rendering shared by the device producer and isolated demo."""
import math
import time

import layout


class BeatPulse:
    def __init__(self):
        self.history = self.previous = self.envelope = 0.0
        self.last = None
        self.last_beat = float('-inf')

    def process(self, bass, gate, now=None,repeat_ms=0,drive=None):
        if not math.isfinite(bass) or bass < 0 or not math.isfinite(gate) or gate < 0:
            raise ValueError('Expected finite nonnegative bass and gate')
        now = time.monotonic() if now is None else now
        if not math.isfinite(now):
            raise ValueError('Invalid music timestamp')
        elapsed = 1/60 if self.last is None else max(0, now-self.last)
        if elapsed > 2 or (self.last is not None and now < self.last):
            self.envelope = self.history = self.previous = 0.0
            self.last_beat = float('-inf')
        self.envelope *= math.exp(-elapsed/.18)
        onset = (bass > max(gate, .003) and bass > self.history*1.7
                 and bass > self.previous*1.25 and now-self.last_beat >= .18)
        if repeat_ms and max(bass,drive or 0)>max(gate,.003) and now-self.last_beat>=repeat_ms/1000:onset=True
        if onset:
            self.envelope, self.last_beat = 1.0, now
        self.history += (bass-self.history)*(1-math.exp(-min(elapsed,.2)/.35))
        self.previous, self.last = bass, now
        if self.envelope < .005:
            self.envelope = 0.0
        return self.envelope


class Renderer:
    def __init__(self, profile='fast'):
        from equalizer import SpatialSpectrum
        self.analyzer = SpatialSpectrum(profile)
        self.pulse = BeatPulse()

    def frame(self, samples, prefs, sections, count, colors=None, now=None):
        self.analyze(samples,prefs,now)
        return self.pixels(prefs,sections,count,colors)

    def analyze(self,samples,prefs,now=None):
        self.analyzer.set_decay(prefs.get('equalizer_decay_ms',250))
        self.analyzer.set_response(prefs.get('equalizer_sensitivity',100),prefs.get('equalizer_gate',6))
        self.analyzer.set_attack(prefs.get('equalizer_attack_ms',0))
        self.analyzer.process(samples)
        self.pulse.process(self.analyzer.bass,self.analyzer.gate,now,prefs.get('music_repeat_ms',1000),getattr(self.analyzer,'rms',0)*.8)

    def features(self,rms,bass,prefs,now=None):
        now=time.monotonic() if now is None else now
        last=getattr(self,'feature_time',None)
        elapsed=1/60 if last is None else now-last
        if not math.isfinite(now):raise ValueError('Invalid music timestamp')
        if not 0<=elapsed<=2:
            self.analyzer.level=0;self.analyzer.reference=.1;self.pulse=BeatPulse();elapsed=1/60
        self.analyzer.set_decay(prefs.get('equalizer_decay_ms',250))
        self.analyzer.set_response(prefs.get('equalizer_sensitivity',100),prefs.get('equalizer_gate',6))
        self.analyzer.set_attack(prefs.get('equalizer_attack_ms',0))
        self.analyzer.features(rms,bass,elapsed)
        self.pulse.process(bass,self.analyzer.gate,now,prefs.get('music_repeat_ms',1000),rms*.8)
        self.feature_time=now

    def pixels(self,prefs,sections,count,colors=None):
        style = prefs.get('music_style','meter')
        if style not in ('meter','pulse'):
            raise ValueError('Invalid music style')
        level = self.analyzer.level
        if style == 'pulse':
            level = min(1,level*.6+self.pulse.envelope*.4)
        return layout.meter(level,sections,count,palette=prefs.get('equalizer_palette','classic'),colors=colors)
