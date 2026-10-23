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


def client(payload=None, pixels=None, link=False, baud=None, enroll=None, expected=None):
    message = dict(kind='pixels', pixels=pixels) if pixels is not None else dict(kind='state', payload=payload)
    if link:
        message = dict(kind='link')
    if baud is not None:
        message = dict(kind='baud', baud=baud)
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
        connection.settimeout(12 if baud is not None or enroll is not None else 4)
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
    prefs = control.settings()
    configured = prefs.get('controller')
    device = Device(configured['port'], expected_mac=configured['mac'],
                    led_count=configured['count']) if configured else None
    device_lock = threading.RLock()
    stop = threading.Event()

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
            old=device
            if old is not None:
                try:
                    old.query({'live':False})
                except Exception:
                    LOG.warning('Previous controller unavailable during explicit enrollment',exc_info=True)
                finally:
                    old.close()
            pinned=command.get('expected')
            candidate=Device(port,expected_mac=pinned['mac'] if pinned else None,
                             led_count=pinned['count'] if pinned else None,discover=not bool(pinned))
            try:
                candidate.query()
                selected=dict(port=port,mac=candidate.expected_mac,count=candidate.led_count)
                control.persist_enrollment(selected)
            except Exception:
                candidate.close()
                raise
            device=candidate
            return selected

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
                            result=device.state(command.get('payload'))
                        elif command['kind']=='pixels':
                            result=device.pixels(command['pixels'])
                        elif command['kind']=='link':
                            result=device.link_status()
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
        while not stop.is_set():
            try:
                with device_lock:
                    if device is not None:
                        device.query()
            except Exception:
                LOG.exception('USB state refresh failed; retrying')
            stop.wait(1)

    def finish(*_):
        stop.set()

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
        poller = threading.Thread(target=refresh, daemon=True)
        poller.start()
        try:
            while not stop.is_set():
                server.handle_request()
        finally:
            stop.set()
            # Join request threads before closing/reconfiguring their Device.
            server.server_close()
            poller.join(timeout=5)
            try:
                if device is not None and device.serial is not None:
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
