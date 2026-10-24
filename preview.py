"""Bounded host-frame preview and an isolated, transport-free music demo."""
import copy
import json
import logging
import math
from pathlib import Path
import re
import tempfile
import threading
import time

import control
import layout

LOG = logging.getLogger('wesp.preview')


def pixels_checked(pixels):
    if (not isinstance(pixels, list) or not 1 <= len(pixels) <= 1024
            or any(not isinstance(p, (list, tuple)) or len(p) != 3
                   or any(type(c) is not int or not 0 <= c <= 255 for c in p) for p in pixels)):
        raise ValueError('Invalid RGB preview frame')
    return [list(p) for p in pixels]


class Publisher:
    def __init__(self, path):
        self.path = Path(path)
        self.last = float('-inf')
        self.sequence = 0

    def publish(self, pixels, mac, brightness=255, source='music', now=None, force=False):
        now = time.monotonic() if now is None else now
        if not force and now - self.last < .1:
            return False
        frame = pixels_checked(pixels)
        if not re.fullmatch('[0-9a-f]{12}', mac or '') or type(brightness) is not int or not 0 <= brightness <= 255:
            raise ValueError('Invalid preview target or brightness')
        record = dict(target='device', mac=mac, pixels=frame, brightness=brightness,
                      source=source, updated=now, sequence=self.sequence + 1)
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent,
                                             prefix='.frame-', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(record, stream)
            temporary.replace(self.path)
        except OSError:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            LOG.debug('Preview unavailable', exc_info=True)
            return False
        self.last, self.sequence = now, record['sequence']
        return True


def read(path, mac, now=None):
    try:
        path = Path(path)
        if path.stat().st_size > 32768:
            return None
        record = json.loads(path.read_text())
        if record.get('target') != 'device' or record.get('mac') != mac:
            return None
        record['pixels'] = pixels_checked(record['pixels'])
        if (type(record['brightness']) is not int or not 0 <= record['brightness'] <= 255
                or type(record['updated']) not in (int, float) or not math.isfinite(record['updated'])
                or not isinstance(record.get('source'), str)):
            return None
        age = (time.monotonic() if now is None else now) - record['updated']
        record.update(age=max(0, age), stale=age < 0 or age > 2)
        return record
    except (OSError, ValueError, KeyError, TypeError):
        return None


class DemoSession:
    """Only temporary tuning and pure DSP: never dispatch a device command."""
    def __init__(self, prefs=None):
        import music
        allowed = ('equalizer_decay_ms', 'equalizer_sensitivity', 'equalizer_gate',
                   'equalizer_attack_ms', 'equalizer_palette','music_style','music_preset','music_custom','music_repeat_ms')
        self.prefs = {key: copy.deepcopy((prefs or {}).get(key, control.DEFAULTS[key])) for key in allowed}
        self.prefs.update(equalizer=True,kde=False)
        self.sections = layout.legacy(20, reverse_second=True)
        self.sections[0]['placement'], self.sections[1]['placement'] = 'left', 'right'
        self.renderer=music.Renderer()
        self.analyzer=self.renderer.analyzer
        self.calm_color=None
        self.calibration=None
        self.brightness, self.on, self.sequence = 128, True, 0
        self.lock = threading.RLock()

    def configure(self, key, value):
        with self.lock:
            if key == 'brightness':
                if type(value) is not int or not 1 <= value <= 255:
                    raise ValueError('Invalid brightness')
                self.brightness = value
            elif key == 'on':
                if type(value) is not bool:
                    raise ValueError('Invalid power state')
                self.on = value
                if not value:
                    self.calibration=None
            elif key in self.prefs:
                if key in ('music_custom','music_preset','equalizer','kde'):
                    raise ValueError('Unsupported demo setting')
                self.prefs[key] = (control.validate_decay_ms(value) if key == 'equalizer_decay_ms'
                                   else control.validate_tuning(key, value))
                import scenes
                if key in scenes.TUNING:
                    self.prefs['music_preset']='custom'
                    self.prefs['music_custom']={item:self.prefs[item] for item in scenes.TUNING}
            else:
                raise ValueError('Unsupported demo setting')

    def preset(self,name):
        import scenes
        with self.lock:
            self.prefs=scenes.preset(self.prefs,name)

    def select_scene(self,name):
        import scenes
        with self.lock:
            self.prefs=scenes.select(self.prefs,name)
            if name=='calm':
                self.calm_color=control.kde_color()

    def start_test(self,section,style):
        import first_light
        with self.lock:
            if not self.on:
                raise ValueError(control.tr('Turn on the lighting before testing a strip'))
            self.calibration=first_light.Lease(dict(controller={'mac':'000000000000','count':20},
                                                  sections=self.sections),section,style)

    def stop_test(self):
        with self.lock:
            self.calibration=None

    def test_status(self):
        with self.lock:
            if self.calibration and self.calibration.frame() is None:
                self.calibration=None
            return self.calibration.record() if self.calibration else dict(active=False)

    def process(self, samples):
        with self.lock:
            self.renderer.analyze(samples,self.prefs)
            colors = None
            if self.prefs['equalizer_palette'] == 'wallpaper':
                import wallpaper
                colors = wallpaper.cached(control.RUNTIME)['colors']
            pixels=(self.renderer.pixels(self.prefs,self.sections,20,colors) if self.prefs['equalizer']
                    else layout.solid(self.calm_color or [0,112,254],self.sections,20))
            if not self.on:
                pixels=[[0,0,0] for _ in range(20)]
            calibration=self.test_status()
            if calibration['active']:
                test_pixels=self.calibration.frame()
                if test_pixels is None:
                    self.calibration=None;calibration={'active':False}
                else:
                    pixels=test_pixels
            self.sequence += 1
            return dict(target='demo', pixels=pixels, brightness=self.brightness,
                        source='calibration' if calibration['active'] else 'music' if self.prefs['equalizer'] else 'calm', sequence=self.sequence, updated=time.monotonic(),
                        stale=False, sections=copy.deepcopy(self.sections), on=self.on,
                        settings=copy.deepcopy(self.prefs))


class FeatureSession:
    """Window-only calculated music, driven by the producer's existing levels."""
    def __init__(self,runtime):
        from feature_preview import Reader
        self.reader=Reader(runtime);self.renderer=None;self.identity=None;self.sequence=0

    def clear(self):self.renderer=None;self.identity=None

    def frame(self,prefs,state):
        selected=prefs.get('controller') or {};identity=(selected.get('mac'),selected.get('count'))
        sample=self.reader.read(*identity)
        if sample is None:self.clear();return None
        if self.renderer is None or self.identity!=identity:
            import music
            self.renderer=music.Renderer();self.identity=identity
        self.renderer.features(sample[3]/65535,sample[4]/65535,prefs)
        colors=None
        if prefs.get('equalizer_palette')=='wallpaper':
            import wallpaper
            colors=wallpaper.cached(control.RUNTIME)['colors']
        pixels=self.renderer.pixels(prefs,prefs.get('sections',[]),identity[1],colors)
        self.sequence+=1
        return dict(target='device',mac=identity[0],pixels=pixels,brightness=state.get('bri',255),
            source='music-local',updated=time.monotonic(),sequence=self.sequence,stale=False)

    def close(self):self.reader.close();self.clear()
