"""UI-independent application state. Device commands and demo never share state."""
import copy
import json
from pathlib import Path
import selectors
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import control
from i18n import tr
import preview


class DeviceBackend:
    COMMANDS = {'status', 'config', 'ports', 'power', 'brightness', 'setting', 'layout',
                'enroll', 'clear', 'notify-preview', 'firmware-status',
                'firmware-prepare', 'firmware-prepare-native', 'firmware-install',
                'firmware-cancel', 'firmware-connect', 'firmware-native-ready'}

    def command(self, args):
        if not args or args[0] not in self.COMMANDS:
            raise ValueError(tr('Unsupported application command'))
        result = subprocess.run(['/usr/bin/python3', str(Path(__file__).with_name('control.py')),
                                 *[str(arg) for arg in args]],
                                capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or tr('The command could not be completed'))
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or not value.get('ok'):
            raise RuntimeError(tr('The command could not be completed'))
        return value

    def setup(self, action, fields):
        if action not in ('probe', 'status', 'configure', 'wifi'):
            raise ValueError(tr('Unsupported application command'))
        try:
            endpoint = control.read_json(control.RUNTIME / 'receiver-setup.json', {})
            url = urllib.parse.urlsplit(endpoint['url'])
            if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.path != '/setup' or not url.port:
                raise ValueError('Invalid local endpoint')
            payload = dict(fields, action=action)
            request = urllib.request.Request(endpoint['url'], json.dumps(payload).encode(),
                headers={'Authorization': 'Bearer ' + endpoint['bearer'],
                         'Content-Type': 'application/json;charset=UTF-8'})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=8) as response:
                result = json.load(response)
            if not isinstance(result, dict) or result.get('ok') is not True:
                raise ValueError('Setup failed')
            return result
        except Exception:
            raise RuntimeError(tr('Could not configure the receiver. Check the USB connection, GPIOs and network settings.')) from None


class DemoAudio:
    """A window-scoped capture worker; uses the same DSP as the device producer."""
    def __init__(self, session):
        self.session = session
        self.record = None
        self.message = tr('Waiting for desktop audio')
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        import numpy as np
        while not self.stop.is_set():
            process = None
            try:
                process = subprocess.Popen(['parec', '--device=@DEFAULT_MONITOR@', '--raw',
                    '--format=float32le', '--rate=48000', '--channels=1', '--latency-msec=10',
                    '--client-name=WESP Preview'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                import os
                os.set_blocking(process.stdout.fileno(), False)
                history, pending = np.zeros(2048, dtype='<f4'), bytearray()
                opened = last_audio = time.monotonic()
                next_frame = opened
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while not self.stop.is_set() and time.monotonic() - opened < 15:
                        if selector.select(.015):
                            chunk = os.read(process.stdout.fileno(), 65536)
                            if not chunk:
                                raise RuntimeError('Capture ended')
                            pending.extend(chunk)
                            complete = len(pending) // 4 * 4
                            if complete:
                                take = min(complete // 4, 2048)
                                values = np.frombuffer(bytes(pending[complete-take*4:complete]), dtype='<f4')
                                del pending[:complete]
                                history = np.concatenate((history[take:], values))
                                last_audio = time.monotonic()
                        now = time.monotonic()
                        if now - last_audio > 2:
                            raise RuntimeError('Capture stalled')
                        if now >= next_frame:
                            samples = history if now-last_audio < .1 else np.zeros(2048)
                            self.record = self.session.process(samples)
                            self.message = tr('Reacting to music') if np.max(np.abs(samples)) > .006 else tr('Silence — play audio on your computer')
                            next_frame = now + 1/60
            except Exception:
                self.message = tr('Desktop audio unavailable — retrying')
                self.record = self.session.process(np.zeros(2048))
                self.stop.wait(1)
            finally:
                if process is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    process.stdout.close()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=4)


class DesktopModel:
    def __init__(self, backend=None):
        self.backend = backend or DeviceBackend()
        self.demo = None
        self.audio = None
        self.receiver = {}
        self.ports = []

    def set_demo(self, enabled, capture=True):
        if self.audio:
            self.audio.close()
            self.audio = None
        if enabled:
            self.demo = preview.DemoSession(control.settings())
            if capture:
                self.audio = DemoAudio(self.demo)
        else:
            self.demo = None

    def close(self):
        if self.audio:
            self.audio.close()
            self.audio = None
        self.demo = None

    def command(self, action, args):
        if self.demo is not None:
            if action == 'brightness':
                self.demo.configure('brightness', int(args[0]))
            elif action == 'power':
                self.demo.configure('on', str(args[0]).lower() == 'true')
            elif action == 'setting' and len(args) == 2:
                self.demo.configure(args[0], args[1])
            else:
                raise ValueError(tr('Leave demo mode to configure your device'))
            return {'ok': True}
        if action == 'setup':
            result = self.backend.setup(args[0], args[1])
            self.receiver = result['receiver']
        else:
            result = self.backend.command([action, *args])
            if action == 'ports':
                self.ports = result['ports']
            if action in ('enroll', 'firmware-connect'):
                self.receiver = {}
        return result

    def poll(self):
        if self.demo is not None:
            import numpy as np
            record = self.audio.record if self.audio and self.audio.record else self.demo.process(np.zeros(2048))
            with self.demo.lock:
                return dict(target='demo', configured=False, online=False,
                    settings=copy.deepcopy(self.demo.prefs), sections=copy.deepcopy(self.demo.sections),
                    state=dict(on=self.demo.on, bri=self.demo.brightness), frame=record,
                    message=self.audio.message if self.audio else tr('Waiting for desktop audio'),
                    receiver={}, ports=[], firmware={})
        prefs = control.settings()
        selected = prefs.get('controller') or {}
        data = dict(target='device', configured=bool(selected), online=False, settings=prefs,
                    sections=prefs.get('sections', []), state={'on': False, 'bri': 128},
                    frame=preview.read(control.RUNTIME / 'frame-preview.json', selected.get('mac')),
                    receiver=self.receiver, ports=self.ports, error='', message='', firmware={})
        if selected:
            try:
                result = self.backend.command(['status'])
                data.update(state=result['state'], online=True,
                            message=(result.get('equalizer') or {}).get('message', ''))
            except Exception as error:
                data['error'] = str(error)
        try:
            data['firmware'] = self.backend.command(['firmware-status'])['firmware']
        except Exception:
            pass
        return data
