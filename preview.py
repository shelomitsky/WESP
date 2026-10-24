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
        import equalizer
        allowed = ('equalizer_decay_ms', 'equalizer_sensitivity', 'equalizer_gate',
                   'equalizer_attack_ms', 'equalizer_palette')
        self.prefs = {key: copy.deepcopy((prefs or {}).get(key, control.DEFAULTS[key])) for key in allowed}
        self.sections = layout.legacy(20, reverse_second=True)
        self.sections[0]['placement'], self.sections[1]['placement'] = 'left', 'right'
        self.analyzer = equalizer.SpatialSpectrum()
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
            elif key in self.prefs:
                self.prefs[key] = (control.validate_decay_ms(value) if key == 'equalizer_decay_ms'
                                   else control.validate_tuning(key, value))
            else:
                raise ValueError('Unsupported demo setting')

    def process(self, samples):
        with self.lock:
            self.analyzer.set_response(self.prefs['equalizer_sensitivity'], self.prefs['equalizer_gate'])
            self.analyzer.set_decay(self.prefs['equalizer_decay_ms'])
            self.analyzer.set_attack(self.prefs['equalizer_attack_ms'])
            self.analyzer.process(samples)
            colors = None
            if self.prefs['equalizer_palette'] == 'wallpaper':
                import wallpaper
                colors = wallpaper.cached(control.RUNTIME)['colors']
            pixels = layout.meter(self.analyzer.level if self.on else 0, self.sections, 20,
                                  palette=self.prefs['equalizer_palette'], colors=colors)
            self.sequence += 1
            return dict(target='demo', pixels=pixels, brightness=self.brightness,
                        source='music', sequence=self.sequence, updated=time.monotonic(),
                        stale=False, sections=copy.deepcopy(self.sections), on=self.on,
                        settings=copy.deepcopy(self.prefs))
