"""UI-independent application state. Device commands and demo never share state."""
import copy
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import control
from realtime_capture import LatestCapture
from i18n import tr
import preview


class DeviceBackend:
    COMMANDS = {'status', 'config', 'ports', 'power', 'brightness', 'setting', 'layout',
                'enroll', 'clear', 'notify-preview', 'firmware-status','scene','music-preset',
                'first-light','first-light-stop',
                'preset-save','preset-load','preset-delete','ota-start','ota-status',
                'firmware-prepare-native', 'firmware-install',
                'firmware-cancel', 'firmware-native-ready'}

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
        if action not in ('probe', 'status', 'configure', 'wifi','preview'):
            raise ValueError(tr('Unsupported application command'))
        public_error=tr('Could not configure the receiver. Check the connection and output settings, then read the settings again.')
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
                if isinstance(result,dict):
                    public_error={
                        'network_requires_usb':tr('Connect USB to change the Wi-Fi network. LED outputs can be saved over Wi-Fi.'),
                        'firmware_update_required':tr('Update the ESP firmware over USB once to enable configuration over Wi-Fi.'),
                        'configuration_unconfirmed':tr('The save could not be confirmed. Read the ESP settings again before retrying.')
                    }.get(result.get('error_code'),public_error)
                raise ValueError('Setup failed')
            return result
        except Exception:
            raise RuntimeError(public_error) from None


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
        capture=LatestCapture(client='WESP Preview')
        silence=np.zeros(2048,dtype='<f4')
        try:
            while not self.stop.is_set():
                snapshot=capture.window.snapshot()
                samples=snapshot[0] if snapshot is not None else silence
                try:
                    self.record=self.session.process(samples)
                    self.message=(tr('Waiting for desktop audio') if snapshot is None else
                        tr('Reacting to music') if np.max(np.abs(samples))>.006 else
                        tr('Silence — play audio on your computer'))
                except Exception:
                    preview.LOG.exception('Demo rendering unavailable')
                    self.message=tr('Desktop audio unavailable — retrying')
                self.stop.wait(1/60)
        finally:capture.close()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=4)


class DesktopModel:
    def __init__(self, backend=None):
        self.backend = backend or DeviceBackend()
        self.demo = None
        self.audio = None
        self.receiver = {}
        self.native_frame=None
        self.native_frame_at=0
        self.feature_preview=preview.FeatureSession(control.RUNTIME)
        self.preview_memory={};self.preview_memory_at=0
        self.ports = []
        self.setup_error=''
        self.setup_note=''
        self.wifi_verified=False
        self.pending_probe=None
        self.action_warning=''

    def read_pending_receiver(self):
        if not self.pending_probe:
            raise ValueError(tr('Select the USB receiver before reading settings'))
        try:
            result=self.backend.setup('probe',self.pending_probe)
            self.receiver=result['receiver']
            self.setup_error=''
            self.setup_note=tr('Receiver settings read. Configure its LED outputs.')
            return result
        except Exception:
            self.setup_error=tr('Firmware installed. Reading settings failed — retry the read.')
            self.receiver={}
            return {'ok':True}

    def identity(self):
        if self.demo is not None:
            return 'demo'
        return 'device:' + str((control.settings().get('controller') or {}).get('mac', ''))

    def local_frame(self,data):
        if self.demo is not None:
            return self.audio.record if data.get('target')=='demo' and self.audio else None
        prefs=data.get('settings',{});selected=prefs.get('controller') or {};state=data.get('state',{})
        if (data.get('target')!='device' or not data.get('online') or not data.get('native_effects')
                or not state.get('on') or not prefs.get('equalizer') or selected.get('backend')!='wesp'
                or selected.get('connection')!='wifi'):
            self.feature_preview.clear();return None
        now=time.monotonic()
        if now>=self.preview_memory_at:
            self.preview_memory=control.read_json(control.RUNTIME/'state.json',{})
            self.preview_memory_at=now+.1
        effective=data.get('activity',{}).get('effective','music')
        if self.preview_memory.get('controller_mac')==selected.get('mac'):
            import scenes
            effective=scenes.activity(prefs,self.preview_memory,state,time.time())['effective']
        if effective!='music':
            self.feature_preview.clear();return None
        return self.feature_preview.frame(prefs,state)

    def preview_frame(self):
        selected=control.settings().get('controller') or {}
        if selected.get('backend')!='wesp':return None
        try:
            frame=self.backend.setup('preview',{'mac':selected['mac']})['receiver']['frame']
            if not isinstance(frame,dict) or frame.get('mac')!=selected.get('mac'):raise ValueError('Preview target changed')
            self.native_frame=frame;self.native_frame_at=time.monotonic()
            return frame
        except Exception:
            self.native_frame=None
            return None

    def set_demo(self, enabled, capture=True):
        self.feature_preview.clear()
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
        self.feature_preview.close()
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
            elif action == 'scene' and len(args)==1:
                self.demo.select_scene(args[0])
            elif action == 'music-preset' and len(args)==1:
                self.demo.preset(args[0])
            elif action=='first-light' and len(args)==2:
                self.demo.start_test(args[0],args[1])
            elif action=='first-light-stop':
                self.demo.stop_test()
            else:
                raise ValueError(tr('Leave demo mode to configure your device'))
            return {'ok': True}
        if action == 'setup':
            if args[0]=='retry':
                return self.read_pending_receiver()
            if args[0]=='wifi' and not self.wifi_verified:
                raise ValueError(tr('Check Wi-Fi before switching the connection'))
            result = self.backend.setup(args[0], args[1])
            self.receiver = result['receiver']
            self.setup_error=''
            if args[0] in ('probe','configure'):
                self.wifi_verified=False
            if args[0]=='probe':
                self.setup_note=tr('Receiver settings read. Configure its LED outputs.')
            elif args[0]=='configure':
                self.setup_note=tr('Outputs saved on the ESP. Test the strips, then verify Wi-Fi.')
            elif args[0]=='status':
                self.wifi_verified=bool((self.receiver.get('wifi') or {}).get('connected'))
                self.setup_note=tr('Wi-Fi verified for this receiver.') if self.wifi_verified else tr('Wi-Fi is not connected yet')
            elif args[0]=='wifi':
                self.setup_note=tr('Using Wi-Fi. You can move the ESP to a separate power supply.')
        else:
            result = self.backend.command([action, *args])
            self.action_warning=result.get('warning','')
            if action == 'ports':
                self.ports = result['ports']
            if action == 'enroll':
                self.receiver = {}
                self.setup_error='';self.setup_note='';self.wifi_verified=False
            if action == 'firmware-prepare-native':
                self.pending_probe=None;self.setup_error='';self.setup_note=''
            if action=='firmware-native-ready':
                job=result['firmware']
                self.pending_probe=dict(port=job['port'],expected_mac=job['board']['mac'])
                self.read_pending_receiver()
        return result

    def poll(self):
        import scenes
        if self.demo is not None:
            import numpy as np
            record = self.audio.record if self.audio and self.audio.record else self.demo.process(np.zeros(2048))
            with self.demo.lock:
                calibration=self.demo.test_status()
                activity=scenes.activity(self.demo.prefs,{},dict(on=self.demo.on),time.time())
                if calibration['active']:
                    activity=dict(base=scenes.mode(self.demo.prefs),effective='calibration',label=tr('Checking strip: %1',calibration['name']))
                return dict(target='demo', configured=False, online=False,
                    settings=copy.deepcopy(self.demo.prefs), sections=copy.deepcopy(self.demo.sections),
                    state=dict(on=self.demo.on, bri=self.demo.brightness), frame=record,
                    message=self.audio.message if self.audio else tr('Waiting for desktop audio'),
                    activity=activity,calibration=calibration,
                    receiver={}, ports=[], firmware={},setup_error='',setup_note='',wifi_verified=False)
        prefs = control.settings()
        selected = prefs.get('controller') or {}
        import ota_update
        ota=ota_update.status()
        if ota.get('mac')!=selected.get('mac'):ota={'stage':'idle'}
        labels={'queued':tr('Preparing Wi-Fi update'),'uploading':tr('Uploading firmware over Wi-Fi'),
                'restarting':tr('Checking the updated ESP'),'complete':tr('ESP update confirmed'),
                'failed':tr('ESP update could not be confirmed')}
        ota['label']=labels.get(ota.get('stage'),'')
        ota_busy=ota.get('stage') in ota_update.ACTIVE
        data = dict(target='device', configured=bool(selected), online=False, settings=prefs,
                    sections=prefs.get('sections', []), state={'on': False, 'bri': 128},
                    frame=preview.read(control.RUNTIME / 'frame-preview.json', selected.get('mac')),
                    receiver=self.receiver, ports=self.ports, error=self.action_warning, message='', firmware={},ota=ota,
                    calibration={'active':False},setup_error=self.setup_error,setup_note=self.setup_note,native_effects=False,
                    wifi_verified=self.wifi_verified)
        if ota_busy:
            data['frame']=None
        if selected and not ota_busy:
            try:
                result = self.backend.command(['status'])
                data.update(state=result['state'], online=True,
                            native_effects=result.get('native_effects',False),
                            native_capabilities=result.get('native_capabilities',{}),
                            activity=result.get('activity',{}),
                            calibration=result.get('calibration',{'active':False}),
                            message=(result.get('equalizer') or {}).get('message', ''))
            except Exception as error:
                data['error'] = str(error)
        if data['native_effects']:
            if not data['state'].get('on'):self.native_frame=None
            frame=self.native_frame
            data['frame']=(frame if frame and frame.get('mac')==selected.get('mac')
                and time.monotonic()-self.native_frame_at<.75 else None)
        else:self.native_frame=None
        try:
            data['firmware'] = self.backend.command(['firmware-status'])['firmware']
            labels={'starting':tr('Preparing installation'),'tools':tr('Preparing installation tools'),
                    'download':tr('Downloading firmware'),'detecting':tr('Identifying the selected ESP'),
                    'backup':tr('Saving the original firmware'),'prepared':tr('Backup ready. Confirm firmware replacement.'),
                    'writing':tr('Writing and verifying firmware'),'flashed':tr('Firmware written. Finish setup.'),
                    'installed':tr('Firmware installed'),'connected':tr('Controller connected'),
                    'failed':tr('Installation failed; the backup is retained'),'cancelled':tr('Installation cancelled')}
            data['firmware']['label']=labels.get(data['firmware'].get('stage'),'')
        except Exception:
            pass
        return data
