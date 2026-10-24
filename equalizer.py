#!/usr/bin/python3
"""Desktop output -> synchronized USB level meters. Audio stays in memory."""
from i18n import tr
import logging
import math
import os
import selectors
import signal
import subprocess
import time

import numpy as np
import control
from audio_source import OutputMonitor,capture_command

LOG = logging.getLogger('wled-equalizer')
RATE, SIZE, FPS = 48000, 2048, 15
USB_FPS = 60
PROFILES = {
    'fast': dict(capture_ms=10, attack=.95, release=.70),
    'smooth': dict(capture_ms=40, attack=.65, release=.86),
}


def orient_pixels(pixels, reverse_first=False, reverse_second=False):
    """Logical meter order -> physical wiring order, independently per strip."""
    first, second = pixels[:10], pixels[10:]
    return (first[::-1] if reverse_first else first) + (second[::-1] if reverse_second else second)


def status(message):
    control.RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    control.write_json(control.RUNTIME / 'equalizer-status.json',
                       dict(message=message, updated=time.time()))


class Spectrum:
    def __init__(self):
        self.window = np.hanning(SIZE)
        self.hz = np.fft.rfftfreq(SIZE, 1 / RATE)
        self.level = np.zeros(3)

    def process(self, samples):
        samples = np.asarray(samples, dtype=float)
        if samples.shape != (SIZE,) or not np.isfinite(samples).all():
            raise ValueError('Expected 2048 finite mono samples')
        spectrum = np.abs(np.fft.rfft((samples - samples.mean()) * self.window))
        spectrum /= self.window.sum() / 2
        bands = np.array([np.sqrt(np.sum(spectrum[(self.hz >= low) &
                                                   (self.hz < high)] ** 2))
                          for low, high in ((40, 250), (250, 2500), (2500, 16000))])
        target = np.clip((bands - .006) * 3.5, 0, 1) ** .65
        self.level = np.maximum(target, self.level * .76)
        self.level[self.level < .004] = 0
        return np.rint(self.level * 255).astype(int).tolist()


class AudioFeatures:
    """Raw source features only; native ESP owns gain, gate and envelopes."""
    def __init__(self):
        self.window=np.hanning(SIZE)
        hz=np.fft.rfftfreq(SIZE,1/RATE);self.low=(hz>=40)&(hz<180)
        self.scale=self.window.sum()/2

    def process(self,samples,fast=False):
        samples=np.asarray(samples,dtype=float)
        if samples.shape!=(SIZE,) or not np.isfinite(samples).all():raise ValueError('Expected finite mono audio')
        centered=samples-samples.mean()
        spectrum=np.abs(np.fft.rfft(centered*self.window))/self.scale
        rms_window=samples[-480:] if fast else samples
        rms_window=rms_window-rms_window.mean()
        return dict(rms=min(1.,float(np.sqrt(np.mean(rms_window**2)))),bass=min(1.,float(np.sqrt(np.sum(spectrum[self.low]**2)))))


class SpatialSpectrum:
    """One continuous bass/level meter repeated on both ten-pixel strips."""
    COLORS = np.array([[0,180,130], [0,205,95], [0,225,55], [45,240,10],
                       [110,240,0], [180,220,0], [240,170,0], [255,110,0],
                       [255,55,0], [255,15,15]])

    def __init__(self, profile='fast', decay_ms=None):
        if profile not in PROFILES:
            raise ValueError('WLED_EQ_PROFILE must be fast or smooth')
        self.profile = profile
        self.attack = PROFILES[profile]['attack']
        self.release = PROFILES[profile]['release']
        if decay_ms is not None or profile == 'fast':
            self.set_decay(250 if decay_ms is None else decay_ms)
        self.window = np.hanning(SIZE)
        self.hz = np.fft.rfftfreq(SIZE, 1/RATE)
        self.level = 0.0
        self.reference = .1
        self.bass = 0.0
        self.set_response(100,6)

    def set_response(self,sensitivity,gate):
        self.sensitivity=control.validate_tuning('equalizer_sensitivity',sensitivity)/100
        self.gate=control.validate_tuning('equalizer_gate',gate)/1000

    def set_attack(self,milliseconds):
        milliseconds=control.validate_tuning('equalizer_attack_ms',milliseconds)
        baseline=PROFILES[self.profile]['attack']
        self.attack=min(baseline,1-.1**(1000/(USB_FPS*milliseconds))) if milliseconds else baseline

    def set_decay(self, milliseconds):
        # Time to 10% of a peak at the existing USB render cadence.
        milliseconds = control.validate_decay_ms(milliseconds)
        self.release = .1 ** (1000 / (USB_FPS * milliseconds))

    def process(self, samples):
        samples = np.asarray(samples, dtype=float)
        if samples.shape != (SIZE,) or not np.isfinite(samples).all():
            raise ValueError('Expected 2048 finite mono samples')
        centered = samples-samples.mean()
        fft = np.abs(np.fft.rfft(centered*self.window)) / (self.window.sum()/2)
        bass = np.sqrt(np.sum(fft[(self.hz >= 40) & (self.hz < 180)]**2))
        rms = float(np.sqrt(np.mean(centered**2)))
        return self.features(rms,float(bass))

    def features(self,rms,bass,elapsed=1/60):
        if (not all(math.isfinite(v) for v in (rms,bass,elapsed)) or not 0<=rms<=1
                or not 0<=bass<=1 or not 0<=elapsed<=2):raise ValueError('Invalid audio features')
        self.bass,self.rms=bass,rms
        cadence=elapsed*USB_FPS
        # Track the recent programme level, independently of the PC's volume.
        # Headroom prevents loud/compressed tracks from pinning the whole bar.
        # Do not learn from silence: the noise gate must not be amplified.
        drive = max(float(bass), float(rms)*.8)
        if drive <= self.gate:
            target = 0.0
        else:
            rate = .08 if drive > self.reference else .006
            self.reference += (drive-self.reference)*(1-(1-rate)**cadence)
            self.reference = max(.02, self.reference)
            if abs(drive-self.reference) < self.reference*.01:
                self.reference = max(.02, drive)
            target = float(np.clip(drive/(self.reference*1.4)*self.sensitivity, 0, 1)**1.1)
        if target > self.level:
            self.level += (target-self.level)*(1-(1-self.attack)**cadence)
        else:
            self.level = max(target, self.level*self.release**cadence)
        if self.level < .02:
            self.level = 0.0
        height = self.level*10
        pixels = [np.rint(color*np.clip(height-index,0,1)).astype(int).tolist()
                  for index,color in enumerate(self.COLORS)]
        return pixels + [list(p) for p in pixels]


def restore():
    with control.locked():
        prefs, mem = control.settings(), control.runtime()
        control.release_equalizer(prefs, mem)
        control.write_json(control.RUNTIME / 'state.json', mem)


def run():
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # Keep auto-gain history while reopening the capture on output switches.
    # Otherwise sensitivity would jump back to its initial value every 15s.
    import music
    renderer=music.Renderer(os.environ.get('WLED_EQ_PROFILE','fast'))
    spatial=renderer.analyzer
    feature_source=AudioFeatures()
    native=False;capability_checked=0;network_retry_at=0
    monitor=None
    import realtime_producer
    hint=realtime_producer.CapabilityHint(control.RUNTIME)
    capture_ms = PROFILES[spatial.profile]['capture_ms']
    LOG.info('Equalizer profile=%s, requested capture=%sms, USB FPS=%s',
             spatial.profile, capture_ms, USB_FPS)
    try:
        while not stopping:
            proc = None
            try:
                prefs, mem = control.settings(), control.runtime()
                if not prefs['equalizer'] or mem['suspended']:
                    if monitor is not None:monitor.close();monitor=None
                    restore()
                    status(tr("Paused") if mem['suspended'] else tr("Disabled"))
                    time.sleep(.3)
                    continue
                if hint.supported(prefs):
                    if monitor is not None:monitor.close();monitor=None
                    realtime_producer.run(hint,lambda:stopping,status,lambda samples:feature_source.process(samples,fast=True))
                    continue
                # Keep one stream until the default OUTPUT actually changes.
                if monitor is None:monitor=OutputMonitor()
                source=monitor.source
                proc = subprocess.Popen(capture_command(source,capture_ms,'WESP Audio'),stdout=subprocess.PIPE)
                os.set_blocking(proc.stdout.fileno(), False)
                analyzer = Spectrum()
                usb = os.environ.get('WLED_TRANSPORT', prefs.get('transport', 'usb')) == 'usb'
                fps = USB_FPS if usb else FPS
                history = np.zeros(SIZE, dtype='<f4')
                pending = bytearray()
                next_frame = time.monotonic()
                have_audio = False
                last_audio = time.monotonic()
                last_status = 0
                with selectors.DefaultSelector() as selector:
                    selector.register(proc.stdout, selectors.EVENT_READ)
                    while not stopping:
                        prefs, mem = control.settings(), control.runtime()
                        if not prefs['equalizer'] or mem['suspended']:
                            break
                        if monitor.source != source or hint.supported(prefs):
                            break
                        wait = min(.2, max(0, next_frame-time.monotonic())) if have_audio else .2
                        if selector.select(wait):
                            chunk = os.read(proc.stdout.fileno(), 65536)
                            if not chunk:
                                raise RuntimeError('Audio capture ended')
                            pending.extend(chunk)
                            last_audio = time.monotonic()
                            complete = len(pending) // 4 * 4
                            if complete:
                                take = min(complete//4, SIZE)
                                samples = np.frombuffer(bytes(pending[complete-take*4:complete]),
                                                        dtype='<f4')
                                del pending[:complete]
                                history = np.concatenate((history[take:], samples))
                                have_audio = True
                        elif time.monotonic() - last_audio > 2:
                            raise RuntimeError('Audio capture stalled')
                        if not have_audio or time.monotonic() < next_frame:
                            continue
                        # Render on a timer, independent of audio batch sizes.
                        # If the source stops sending, fade instead of holding a peak.
                        samples = history if time.monotonic()-last_audio < .1 else np.zeros(SIZE)
                        if time.monotonic()<network_retry_at:
                            next_frame=time.monotonic()+.05
                            continue
                        try:
                            if usb and (prefs.get('controller') or {}).get('backend')=='wesp' and time.monotonic()-capability_checked>=1:
                                import usb_transport
                                native=usb_transport.client(native={'action':'capabilities'}) is True
                                capability_checked=time.monotonic()
                            elif (prefs.get('controller') or {}).get('backend')!='wesp':native=False
                            fps=20 if native else USB_FPS if usb else FPS
                            features=feature_source.process(samples) if native else None
                            rgb = None if native else analyzer.process(samples)
                            if usb and not native:
                                renderer.analyze(samples,prefs)
                            pixels = [] if usb and not native else None
                            colors=None
                            if native and prefs.get('equalizer_palette')=='wallpaper':
                                import wallpaper
                                colors=wallpaper.cached(control.RUNTIME)['colors']
                            with control.locked():
                                prefs, mem = control.settings(), control.runtime()
                                if pixels is not None:
                                    if prefs.get('controller') and prefs.get('sections'):
                                        import layout
                                        colors=None
                                        if prefs.get('equalizer_palette')=='wallpaper':
                                            import wallpaper
                                            colors=wallpaper.cached(control.RUNTIME)['colors']
                                        pixels=renderer.pixels(prefs,prefs['sections'],prefs['controller']['count'],colors=colors)
                                    else:
                                        import layout
                                        sections=layout.legacy(20,prefs.get('reverse_first',False),prefs.get('reverse_second',False))
                                        pixels=renderer.pixels(prefs,sections,20)
                                was_native=mem.get('nativeEffects',False)
                                active = (control.equalizer_frame(prefs,mem,rgb,features=features,colors=colors) if native
                                          else control.equalizer_frame(prefs,mem,rgb,pixels=pixels))
                                if native and not was_native and mem.get('nativeEffects'):
                                    control.write_json(control.RUNTIME/'state.json',mem)
                        except Exception:
                            LOG.exception('Receiver unavailable; keeping desktop audio capture')
                            status(tr('Receiver unavailable — audio capture remains active'))
                            network_retry_at=time.monotonic()+.5
                            next_frame=time.monotonic()+.05
                            continue
                        # Advance against the previous deadline; from-now pacing
                        # would skip every second audio block under minor jitter.
                        now = time.monotonic()
                        next_frame += 1/fps
                        if next_frame < now:
                            next_frame = now + 1/fps  # skip missed deadlines, no burst
                        if time.monotonic() - last_status > 1:
                            mode = tr("fast response") if spatial.profile == 'fast' else tr("smooth response")
                            status((tr('Music and signals are rendered on the ESP.') if native else
                                    tr('USB · %1 · up to 60 FPS',mode) if usb else tr("Reacting to music")) if active else tr("Waiting for lighting to turn on or the volume indicator to finish"))
                            last_status = time.monotonic()
                        if not active:
                            time.sleep(.1)
            except Exception:
                LOG.exception('Music lighting unavailable; retrying')
                status(tr("No audio or WLED connection — reconnecting"))
                try:
                    restore()
                except Exception:
                    LOG.exception('Unable to restore lighting; snapshot retained')
                for _ in range(20):
                    if stopping:
                        break
                    time.sleep(.1)
            finally:
                if proc is not None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    proc.stdout.close()
    finally:
        if monitor is not None:monitor.close()
        restore()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    run()
