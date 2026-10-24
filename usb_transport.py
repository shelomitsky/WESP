"""Single USB owner and local command socket; WLED JSON + Adalight."""
from i18n import tr
import copy
import json
import logging
import os
from pathlib import Path
import signal
import socket
import socketserver
import threading
import time

from usb_probe import DEFAULT_PORT, decode_reply

LOG = logging.getLogger('wled-usb')
BAUD_COMMANDS = {115200: b'\xb0', 921600: b'\xb5'}


def socket_path():
    runtime = Path(os.environ.get('WLED_RUNTIME_DIR',
                   str(Path(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/wled-control-desktop-{os.getuid()}')) / 'wled-control-desktop')))
    return runtime / 'usb.sock'


def adalight(pixels):
    if not 1 <= len(pixels) <= 1024:
        raise ValueError(tr("Invalid LED count"))
    if any(len(rgb) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in rgb)
           for rgb in pixels):
        raise ValueError(tr("Invalid RGB values"))
    high, low = divmod(len(pixels)-1, 256)
    return b'Ada' + bytes([high, low, high ^ low ^ 0x55]) + bytes(v for rgb in pixels for v in rgb)


def client(payload=None, pixels=None, link=False, baud=None, enroll=None, expected=None, calibration=None,native=None):
    message = dict(kind='pixels', pixels=pixels) if pixels is not None else dict(kind='state', payload=payload)
    if link:
        message = dict(kind='link')
    if baud is not None:
        message = dict(kind='baud', baud=baud)
    if calibration is not None:
        message = dict(kind='calibration',calibration=calibration)
    if native is not None:
        message=dict(kind='native',native=native)
    if enroll is not None:
        message = dict(kind='enroll', port=enroll)
        if expected is not None:
            message['expected']=expected
    else:
        import control
        selected=control.settings().get('controller')
        if not selected:
            raise ValueError(tr("Select a controller first"))
        message['controller_mac']=selected['mac']
        message['controller_count']=selected['count']
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(120 if native and native.get('action')=='ota' else 12 if baud is not None or enroll is not None else 4)
        try:
            connection.connect(str(socket_path()))
        except OSError as error:
            raise ValueError(tr("USB service is not running: wled-control-usb.service is required")) from error
        connection.sendall(json.dumps(message).encode() + b'\n')
        with connection.makefile('rb') as stream:
            response = json.loads(stream.readline(131072))
    if not response.get('ok'):
        raise ValueError(response.get('error', tr("USB communication error")))
    return response['result']


def require_target(command,device):
    if (command.get('controller_mac') != device.expected_mac
            or command.get('controller_count') != device.led_count):
        raise ValueError(tr("The selected controller changed; reconnect"))


def native_request(device,fields,prefs):
    """One owner handles both transports; None explicitly means old firmware."""
    import wesp_transport,effects_config
    if not isinstance(device,wesp_transport.Device):return None
    device.connect()
    if fields.get('action')=='metadata':return dict(device.document.get('capabilities',{}))
    if fields.get('action')=='ota':
        import ota_update
        return ota_update.perform(device,fields.get('id'))
    if not device.native_effects():return None
    action=fields.get('action')
    if action=='capabilities':return True
    config=effects_config.cached(prefs)
    if action=='configure':device.effects_configure(config);return True
    if action=='audio':return device.features(fields['rms'],fields['bass'],config,fields.get('colors'))
    if action in ('apply','volume'):
        if not device.document['on']:return False
        device.effects_configure(config)
        if not prefs.get('equalizer'):
            device.effect('solid',fields['color'],config)
        elif not device.last_scene:
            device.features(0,0,config)
        if action=='volume':return device.event('volume',fields['ref'],fields['value'],config)
        if fields.get('notification'):
            device.event('notification',fields['notification'],0,config)
        else:
            device.event('clear',fields['clear_ref'],0,config)
        if not prefs.get('volume'):
            device.event('clear_volume',fields['clear_ref'],0,config)
        return True
    raise ValueError('Unknown native effect action')


class Device:
    def __init__(self, port=None, baud=921600, expected_mac=None, led_count=None, discover=False):
        if baud not in BAUD_COMMANDS:
            raise ValueError(tr("Supported baud rates are 115200 and 921600"))
        self.expected_mac, self.led_count, self.discover = expected_mac, led_count, discover
        self.port, self.baud, self.preferred_baud = port, 115200, baud
        self.serial = None
        self.query_lock = threading.Lock()
        self.write_lock = threading.RLock()
        self.document = None
        self.updated = 0
        self.needs_handshake = False
        self.reply_sequence = 0
        self.frame_sequence = 0
        self.last_exchange = {}

    def verify_identity(self, document):
        import re
        info = document.get('info', {})
        mac = info.get('mac', '').lower().replace(':','')
        count = info.get('leds', {}).get('count')
        if not re.fullmatch(r'[0-9a-f]{12}', mac) or type(count) is not int or not 1 <= count <= 1024:
            raise ValueError(tr("WLED with 1–1024 RGB LEDs is required"))
        if self.discover and self.expected_mac is None:
            self.expected_mac, self.led_count = mac, count
        if not self.expected_mac or mac != self.expected_mac:
            raise ValueError(tr("USB: a different controller is connected"))
        if self.discover and self.led_count is None:
            self.led_count = count
        if count != self.led_count:
            raise ValueError(tr("WLED LED count changed; check the layout and reconnect"))

    def connect(self):
        import serial
        if not self.port or (not self.expected_mac and not self.discover):
            raise ValueError(tr("Select a controller first"))
        if self.serial is not None and self.serial.is_open:
            if self.needs_handshake:
                self.negotiate()
            return
        device = serial.Serial(port=None, baudrate=115200, timeout=.1,
                               write_timeout=.3, exclusive=True)
        device.dtr = device.rts = False
        device.port = self.port
        try:
            device.open()
            time.sleep(1.5)
        except Exception:
            device.close()
            raise
        self.serial = device
        self.needs_handshake = True
        self.negotiate()

    def exchange(self, payload=None, timeout=2):
        """One JSON roundtrip; caller owns query_lock and write_lock."""
        started = time.monotonic()
        packet = json.dumps(dict(payload or {}, v=True)).encode() + b'\n'
        self.serial.flush()
        self.serial.reset_input_buffer()
        self.write(packet)
        buffer = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            buffer.extend(self.serial.read(min(max(self.serial.in_waiting, 1), 8192)))
            doc = decode_reply(buffer)
            if doc is not None:
                self.verify_identity(doc)
                self.document = doc
                self.updated = time.monotonic()
                self.reply_sequence += 1
                self.last_exchange = dict(baud=self.serial.baudrate,tx_bytes=len(packet),
                    rx_bytes=len(buffer),elapsed_ms=round((time.monotonic()-started)*1000,2),
                    ok=True,frames=self.frame_sequence,kind='command' if payload else 'poll')
                LOG.info('USB exchange %s',json.dumps(self.last_exchange))
                return copy.deepcopy(doc['state'])
            if len(buffer) > 131072:
                raise ValueError(tr("WLED response is too large"))
        self.last_exchange = dict(baud=self.serial.baudrate,tx_bytes=len(packet),
            rx_bytes=len(buffer),elapsed_ms=round((time.monotonic()-started)*1000,2),
            ok=False,frames=self.frame_sequence,kind='command' if payload else 'poll')
        LOG.warning('USB exchange timeout %s',json.dumps(self.last_exchange))
        raise TimeoutError(tr("No WLED response over USB"))

    def negotiate(self):
        """Find this controller, then change baud only after identity proof.

        The temporary WLED command does not write flash. Try both known rates
        on reconnect because a reset restores 115200, but a service restart
        can leave WLED running at 921600.
        """
        rates = dict.fromkeys((self.serial.baudrate, self.preferred_baud, 115200, 921600))
        self.needs_handshake = True
        found = False
        for rate in rates:
            self.serial.baudrate = rate
            try:
                self.exchange(timeout=1)
                self.baud = rate
                found = True
                break
            except TimeoutError:
                continue
        if not found:
            raise TimeoutError(tr("WLED did not respond at 115200 or 921600 baud"))
        if self.baud != self.preferred_baud:
            source_baud = self.baud
            try:
                # Check host-driver support before telling WLED to change.
                # No bytes are transmitted during this local-only preflight.
                self.serial.baudrate = self.preferred_baud
                self.serial.baudrate = source_baud
            except (ValueError, OSError):
                self.serial.baudrate = source_baud
                self.needs_handshake = False
                LOG.warning('Host driver rejected %s baud; keeping %s',
                            self.preferred_baud, source_baud)
                return
            self.write(BAUD_COMMANDS[self.preferred_baud])
            self.serial.flush()
            time.sleep(.05)  # let WLED drain its old-baud acknowledgement
            self.serial.baudrate = self.preferred_baud
            try:
                self.exchange(timeout=1.5)
                self.baud = self.preferred_baud
            except TimeoutError:
                # If the command succeeded but the fast reply was lost, undo it
                # at the fast rate; if it was ignored, WLED is already at 115200.
                self.write(BAUD_COMMANDS[115200])
                self.serial.flush()
                time.sleep(.05)
                self.serial.baudrate = 115200
                self.exchange(timeout=1.5)
                self.baud = 115200
                LOG.warning('Fast USB handshake failed; verified fallback to 115200 baud')
        self.needs_handshake = False
        LOG.info('USB identity confirmed: %s, baud=%s, target=%s',
                 self.expected_mac, self.baud, self.preferred_baud)

    def set_baud(self, baud):
        if baud not in BAUD_COMMANDS:
            raise ValueError(tr("Supported baud rates are 115200 and 921600"))
        with self.query_lock, self.write_lock:
            self.state()
            self.verify_identity(self.document)
            self.preferred_baud = baud
            self.negotiate()
            return self.link_status()

    def link_status(self):
        if self.needs_handshake:
            raise ValueError(tr("USB is negotiating speed; try again"))
        self.state()
        self.verify_identity(self.document)
        return dict(baud=self.baud, target_baud=self.preferred_baud,
                    fallback=self.baud != self.preferred_baud, mac=self.expected_mac,
                    reply_sequence=self.reply_sequence,
                    last_reply_age=round(time.monotonic()-self.updated, 3),
                    frame_sequence=self.frame_sequence,last_exchange=self.last_exchange.copy())

    def write(self, packet):
        with self.write_lock:
            if self.serial is None or not self.serial.is_open:
                raise ValueError(tr("USB controller disconnected"))
            if self.serial.write(packet) != len(packet):
                raise OSError(tr("Incomplete USB frame"))

    def query(self, payload=None):
        # WLED serializes JSON synchronously; while it sends the response it
        # cannot consume a fast incoming pixel stream reliably. Finish the
        # entire request/reply before allowing any more Adalight frames.
        with self.query_lock, self.write_lock:
            try:
                self.connect()
                if payload is not None:
                    if self.document is None or time.monotonic() - self.updated > 3:
                        raise ValueError(tr("No confirmed USB state before the change"))
                    self.verify_identity(self.document)
                return self.exchange(payload)
            except Exception as error:
                self.updated = 0
                # A read timeout must not repeatedly reset an otherwise
                # connected ESP via CP2102 port open/close. Retry in place.
                if isinstance(error, TimeoutError):
                    self.needs_handshake = True
                    raise
                with self.write_lock:
                    if self.serial is not None:
                        self.serial.close()
                    self.serial = None
                raise

    def state(self, payload=None):
        if payload is not None:
            return self.query(payload)
        if self.needs_handshake:
            raise ValueError(tr("USB is negotiating speed; try again"))
        if self.document is None or time.monotonic() - self.updated > 3:
            raise ValueError(tr("No recent WLED state over USB"))
        return copy.deepcopy(self.document['state'])

    def pixels(self, pixels):
        packet = adalight(pixels)
        with self.write_lock:
            state = self.state()
            self.verify_identity(self.document)
            if not state.get('on'):
                return False
            if state.get('lor', 0):
                raise ValueError(tr("Realtime override is enabled in WLED"))
            if len(pixels) != self.document['info']['leds']['count']:
                raise ValueError(tr("Frame LED count does not match WLED; reconnect the controller"))
            self.write(packet)
            self.frame_sequence += 1
            return True

    def close(self):
        with self.query_lock, self.write_lock:
            if self.serial is not None:
                self.serial.close()
                self.serial = None


def serve():
    import control
    import preview
    publisher = preview.Publisher(control.RUNTIME / 'frame-preview.json')
    prefs = control.settings()
    configured = prefs.get('controller')
    def selected_device(selected):
        if selected.get('backend')=='wesp':
            import wesp_transport
            return wesp_transport.Device(selected.get('port'),expected_mac=selected['mac'],
                    led_count=selected['count'],host=selected.get('host'),
                    fallback_host=selected.get('fallback_host'),
                    connection=selected.get('connection','usb'))
        return Device(selected['port'],expected_mac=selected['mac'],led_count=selected['count'])
    device = selected_device(configured) if configured else None
    device_lock = threading.RLock()
    stop = threading.Event()
    wake = threading.Event()
    calibration = [None]

    def cancel_calibration(blank=True):
        lease=calibration[0]
        calibration[0]=None
        if lease is None or device is None or device.expected_mac!=lease.mac:
            return
        if hasattr(device,'last_frame'):
            device.last_frame=None
        if blank:
            try:
                pixels=[[0,0,0] for _ in range(device.led_count)]
                device.pixels(pixels)
                publisher.publish(pixels,device.expected_mac,source='calibration',force=True)
            except (OSError,ValueError,TimeoutError):
                LOG.debug('Calibration stopped without output',exc_info=True)

    def calibration_status():
        import first_light
        lease=calibration[0]
        if lease and not first_light.active(control.settings(),{'firstLight':lease.record()}):
            cancel_calibration()
            lease=None
        return lease.record() if lease else dict(active=False)

    def enroll_device(command):
        nonlocal device
        import re
        port=command['port']
        if not re.fullmatch(r'/dev/tty(?:USB|ACM)[0-9]+',port):
            raise ValueError(tr("Select a USB serial port from the list"))
        # This may restore an old EQ snapshot through an ordinary RPC. The
        # threaded server can handle it; device_lock must not be held yet.
        control.prepare_enrollment()
        with device_lock:
            cancel_calibration()
            old=device
            if old is not None:
                try:
                    old.query({'live':False})
                except Exception:
                    LOG.warning('Previous controller unavailable during explicit enrollment',exc_info=True)
                finally:
                    old.close()
            pinned=command.get('expected')
            device_class=Device
            if pinned and pinned.get('backend')=='wesp':
                import wesp_transport
                device_class=wesp_transport.Device
            candidate=device_class(port,expected_mac=pinned['mac'] if pinned else None,
                             led_count=pinned.get('count') if pinned else None,
                             discover=not pinned or 'count' not in pinned)
            try:
                candidate.query()
                selected=dict(port=port,mac=candidate.expected_mac,count=candidate.led_count)
                if device_class is not Device:
                    selected.update(backend='wesp',connection='usb')
                control.persist_enrollment(selected)
            except Exception:
                candidate.close()
                raise
            device=candidate
            return selected

    def receiver_setup(command):
        """Called only by the authenticated local UI bridge, never a shell arg."""
        nonlocal device
        import wesp_transport
        action=command.get('action')
        if action not in ('probe','status','configure','wifi','preview'):
            raise ValueError('Unknown receiver setup action')
        with control.locked():
            with device_lock:
                if action=='probe':
                    import re
                    port=command.get('port','')
                    if not re.fullmatch(r'/dev/tty(?:USB|ACM)[0-9]+',port):
                        raise ValueError('Invalid USB port')
                    expected_mac=command.get('expected_mac')
                    if expected_mac and not re.fullmatch('[0-9a-f]{12}',expected_mac):
                        raise ValueError('Invalid expected receiver MAC')
                    cancel_calibration()
                    old=device
                    if old is not None:
                        old.close()
                    candidate=wesp_transport.Device(port,expected_mac=expected_mac or None,discover=True)
                    try:
                        result=candidate.setup_status()
                        candidate.pair()
                    except Exception:
                        candidate.close()
                        raise
                    device=candidate
                    return result
                if not isinstance(device,wesp_transport.Device) or command.get('mac')!=device.expected_mac:
                    raise ValueError('Select and read the WESP receiver first')
                if action=='status':
                    return device.setup_status(refresh_count=True)
                if action=='preview':
                    return {'frame':device.preview()}
                target=device
                if action=='configure':
                    wesp_transport.validate_outputs(command.get('outputs'),command.get('max_milliamps',500))
                    if device.connection!='usb' and (command.get('ssid') is not None or command.get('password') is not None):
                        raise wesp_transport.ConfigurationError('network_requires_usb','Use USB to change the WESP Wi-Fi network')
            # Native configure itself darkens and clears old output ownership.
            # Replaying overlays here can block recovery after a lost CFG ACK
            # when the receiver's count already differs from saved settings.
            if action!='configure':
                control.prepare_enrollment()
            with device_lock:
                if device is not target or command.get('mac')!=device.expected_mac:
                    raise ValueError('The receiver changed during setup')
                if action=='configure':
                    cancel_calibration()
                    result=device.configure(command.get('outputs'),command.get('max_milliamps',500),
                                            ssid=command.get('ssid'),password=command.get('password'))
                    selected=dict(port=device.port,mac=device.expected_mac,count=device.led_count,
                                  backend='wesp',connection=device.connection)
                    if device.connection=='wifi':
                        selected.update(host=device.host,fallback_host=device.fallback_host)
                    control.persist_enrollment(selected,preserve_scene=True)
                    return result
                info=device.setup_status()
                wifi=info['wifi']
                if not wifi.get('connected') or not wifi.get('ip'):
                    raise ValueError('The receiver has not joined Wi-Fi yet')
                candidate=wesp_transport.Device(device.port,expected_mac=device.expected_mac,
                    led_count=device.led_count,host=wifi.get('host') or wifi['ip'],
                    fallback_host=wifi['ip'],connection='wifi')
                try:
                    result=candidate.setup_status()
                    selected=dict(port=device.port,mac=device.expected_mac,count=device.led_count,
                        backend='wesp',connection='wifi',host=wifi.get('host') or wifi['ip'],
                        fallback_host=wifi['ip'])
                    control.persist_enrollment(selected)
                except Exception:
                    candidate.close()
                    raise
                device.close()
                device=candidate
                return result

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(4)
            try:
                command=json.loads(self.rfile.readline(65536))
                if command['kind']=='enroll':
                    # Lock before device_lock so a command already holding the
                    # shared lock can finish its UART RPC while enrollment waits.
                    with control.locked():
                        result=enroll_device(command)
                else:
                    with device_lock:
                        if device is None:
                            raise ValueError(tr("Select a controller first"))
                        require_target(command,device)
                        if command['kind']=='state':
                            if command.get('payload') and calibration[0]:
                                cancel_calibration(blank=command['payload'].get('on') is not False)
                            result=device.state(command.get('payload'))
                            if result.get('on') is False:
                                publisher.publish([[0,0,0] for _ in range(device.led_count)],
                                                  device.expected_mac, source='off', force=True)
                        elif command['kind']=='pixels':
                            if calibration_status()['active']:
                                response=dict(ok=True,result=False)
                                self.wfile.write(json.dumps(response).encode()+b'\n')
                                return
                            result=device.pixels(command['pixels'])
                            if result is not False and time.monotonic()-publisher.last >= .1:
                                try:
                                    import notification_fx
                                    document=device.document or {}
                                    state=document.get('state',document)
                                    current=control.settings()
                                    memory=control.runtime()
                                    source=('volume' if memory.get('volumeUntil',0)>time.time() else
                                            'notification' if notification_fx.active(current,memory,time.time()) else
                                            'music' if current.get('equalizer') else
                                            'desktop' if current.get('kde') else 'manual')
                                    publisher.publish(command['pixels'],device.expected_mac,
                                                      brightness=state.get('bri',255),source=source)
                                except (OSError,ValueError,KeyError,TypeError):
                                    LOG.debug('Preview metadata unavailable',exc_info=True)
                        elif command['kind']=='link':
                            result=device.link_status()
                        elif command['kind']=='native':
                            action=command['native'].get('action')
                            if action=='ota':cancel_calibration()
                            if calibration_status()['active'] and action not in ('capabilities','metadata'):
                                result=False
                            else:
                                result=native_request(device,command['native'],control.settings())
                        elif command['kind']=='calibration':
                            import first_light
                            fields=command['calibration']
                            if not isinstance(fields,dict):
                                raise ValueError(tr('Invalid strip test request'))
                            action=fields.get('action')
                            if action=='start':
                                device.query()
                                if not device.state()['on']:
                                    raise ValueError(tr('Turn on the lighting before testing a strip'))
                                current=control.settings()
                                require_target(command,device)
                                calibration[0]=first_light.Lease(current,fields.get('section'),fields.get('style'))
                                try:
                                    frame=calibration[0].frame()
                                    device.pixels(frame)
                                    publisher.publish(frame,device.expected_mac,source='calibration',force=True)
                                except Exception:
                                    cancel_calibration(blank=False)
                                    raise
                                result=calibration[0].record()
                                wake.set()
                            elif action=='stop':
                                cancel_calibration()
                                result=dict(active=False)
                                wake.set()
                            elif action=='status':
                                result=calibration_status()
                            else:
                                raise ValueError(tr('Invalid strip test request'))
                        elif command['kind']=='baud':
                            result=device.set_baud(command['baud'])
                        else:
                            raise ValueError(tr("Unknown USB command"))
                response=dict(ok=True,result=result)
            except Exception as error:
                LOG.warning('USB command failed: %s',error)
                response=dict(ok=False,error=str(error))
            try:
                self.wfile.write(json.dumps(response).encode()+b'\n')
            except (BrokenPipeError,ConnectionResetError):
                pass

    def refresh():
        last_query=0
        while not stop.is_set():
            delay=.25
            try:
                with device_lock:
                    if device is not None:
                        if calibration_status()['active']:
                            lease=calibration[0]
                            if not device.state()['on']:
                                cancel_calibration(blank=False)
                            else:
                                frame=lease.frame()
                                if frame is None:
                                    cancel_calibration()
                                else:
                                    device.pixels(frame)
                                    publisher.publish(frame,device.expected_mac,source='calibration')
                        elif hasattr(device,'maintain'):
                            device.maintain()
                        interval=.25 if hasattr(device,'maintain') else 1
                        if calibration[0] is None or time.monotonic()-last_query>=interval:
                            device.query()
                            last_query=time.monotonic()
                        if (calibration[0] is None and hasattr(device,'native_effects') and device.native_effects()
                                and device.last_scene is None and device.last_frame is None and device.state()['on']):
                            current=control.settings();memory=control.runtime()
                            if ((current.get('controller') or {}).get('mac')==device.expected_mac
                                    and not current.get('equalizer') and not memory.get('suspended')
                                    and not memory.get('firstLight')):
                                color=control.kde_color() if current.get('kde') else list(device.color or [0,0,0])
                                native_request(device,{'action':'apply','color':color,'notification':None,'clear_ref':'0000000000000000'},current)
                        delay=(.05 if calibration[0] else device.refresh_interval() if hasattr(device,'refresh_interval')
                               else .25 if hasattr(device,'maintain') else 1)
            except Exception:
                with device_lock:
                    cancel_calibration(blank=False)
                LOG.exception('USB state refresh failed; retrying')
            wake.wait(delay)
            wake.clear()

    def finish(*_):
        stop.set()
        wake.set()

    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)
    path = socket_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Same owner lock as control's command lock, independent name. A second
    # service must not unlink the first service's socket or claim its UART.
    with control.locked('usb-owner'):
        path.unlink(missing_ok=True)
        server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
        path.chmod(0o600)
        server.timeout = .2
        import receiver_setup as setup_module
        bridge=setup_module.Bridge(path.parent,receiver_setup)
        poller = threading.Thread(target=refresh, daemon=True)
        poller.start()
        try:
            while not stop.is_set():
                server.handle_request()
        finally:
            stop.set()
            bridge.close()
            # Join request threads before closing/reconfiguring their Device.
            server.server_close()
            poller.join(timeout=5)
            try:
                if device is not None and hasattr(device,'maintain'):
                    device.query({'on':False})
                elif device is not None and getattr(device,'serial',None) is not None:
                    device.query({'live': False})
                    device.set_baud(115200)
            except Exception:
                LOG.exception('Could not exit realtime mode')
            if device is not None:
                device.close()
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='WLED USB service / temporary baud recovery')
    parser.add_argument('--restore-baud', action='store_true',
                        help='Find confirmed controller and return it to 115200 without flash writes')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.restore_baud:
        import control
        with control.locked('usb-owner'):
            selected = control.settings().get('controller')
            if not selected:
                raise SystemExit(tr("Select a controller first"))
            recovery = Device(selected['port'], baud=115200, expected_mac=selected['mac'], led_count=selected['count'])
            try:
                recovery.query()
                print(json.dumps(recovery.link_status()))
            finally:
                recovery.close()
    else:
        serve()
