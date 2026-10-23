"""MAC-pinned WESP v1 transport. Only explicit maintain() renews frames."""
import base64
import copy
import json
import ipaddress
import os
from pathlib import Path
import re
import secrets
import socket
import tempfile
import threading
import time

MAX_LINE = 8192
PARTIAL_TIMEOUT = .250
TOKEN_RE = re.compile(r'[0-9a-fA-F]{64}')
MAC_RE = re.compile(r'[0-9a-f]{12}')
_CREDENTIAL_LOCK = threading.RLock()


def credentials_path():
    import control
    return Path(control.CONFIG) / 'credentials.json'


def _mac(value):
    value = str(value or '').lower().replace(':', '')
    if not MAC_RE.fullmatch(value):
        raise ValueError('Invalid WESP controller MAC')
    return value


def _credentials():
    path = credentials_path()
    if not path.exists():
        return {}
    try:
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('WESP credentials must be a private 0600 file')
        document = json.loads(path.read_text())
        if not isinstance(document, dict):
            raise ValueError()
        return document
    except (OSError, ValueError):
        raise ValueError('Cannot read private WESP credentials') from None


def load_token(mac):
    with _CREDENTIAL_LOCK:
        value = _credentials().get(_mac(mac))
        if not isinstance(value, str) or not TOKEN_RE.fullmatch(value):
            raise ValueError('Pair this WESP controller over USB first')
        return value


def save_token(mac, token):
    mac = _mac(mac)
    if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        raise ValueError('Invalid WESP pairing key')
    with _CREDENTIAL_LOCK:
        document = _credentials()
        document[mac] = token
        path = credentials_path()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.credentials-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(document, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _rgb(color):
    if not isinstance(color, (list, tuple)) or len(color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
        raise ValueError('Invalid WESP RGB values')
    return list(color)


def validate_outputs(outputs, max_milliamps):
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 8:
        raise ValueError('WESP requires 1–8 outputs')
    if type(max_milliamps) is not int or not 100 <= max_milliamps <= 5000:
        raise ValueError('Invalid WESP current limit')
    pins, total, clean = set(), 0, []
    for output in outputs:
        if not isinstance(output, dict):
            raise ValueError('Invalid WESP output')
        gpio, count, order = output.get('gpio'), output.get('count'), output.get('order')
        if type(gpio) is not int or gpio not in {2, 4, 5, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33} or gpio in pins:
            raise ValueError('Invalid or duplicate WESP GPIO')
        if type(count) is not int or not 1 <= count <= 1024 or order not in {'RGB', 'RBG', 'GRB', 'GBR', 'BRG', 'BGR'}:
            raise ValueError('Invalid WESP output count or color order')
        pins.add(gpio)
        total += count
        clean.append(dict(gpio=gpio, count=count, order=order))
    if total > 1024:
        raise ValueError('WESP supports at most 1024 LEDs')
    return clean


class Device:
    tcp_port = 19447
    timeout = 2.0

    def __init__(self, port=None, baud=921600, expected_mac=None, led_count=None,
                 discover=False, host=None, connection='usb', fallback_host=None):
        if connection not in ('usb', 'wifi') or baud != 921600:
            raise ValueError('WESP supports USB 921600 or Wi-Fi TCP')
        self.port, self.baud, self.preferred_baud = port, baud, baud
        self.host, self.connection, self.discover = host, connection, discover
        try:
            self.fallback_host = str(ipaddress.IPv4Address(fallback_host)) if fallback_host else None
        except ipaddress.AddressValueError:
            raise ValueError('Invalid WESP fallback IPv4 address') from None
        self.expected_mac = _mac(expected_mac) if expected_mac else None
        self.led_count = led_count
        if led_count is not None and (type(led_count) is not int or not 0 <= led_count <= 1024):
            raise ValueError('Invalid WESP LED count')
        if connection == 'wifi' and (not host or not self.expected_mac or not led_count):
            raise ValueError('Wi-Fi requires a configured WESP MAC and LED count')
        self.serial = self.sock = None
        self.query_lock = threading.RLock()
        self.write_lock = self.query_lock
        self.document = None
        self.updated = 0
        self.sequence = self.reply_sequence = self.frame_sequence = 0
        self.last_exchange = {}
        self.last_frame = None
        self.color = None
        self.last_frame_at = 0
        self.needs_handshake = False
        self._token = None
        self.session = None
        self._buffer = bytearray()

    def verify_identity(self, document):
        mac = _mac(document.get('mac'))
        count = document.get('count')
        if type(document.get('proto')) is not int or document['proto'] != 1 or type(count) is not int or not 0 <= count <= 1024:
            raise ValueError('Invalid WESP protocol or LED count')
        if self.expected_mac is None and self.discover and self.connection == 'usb':
            self.expected_mac = mac
        if mac != self.expected_mac:
            raise ValueError('A different WESP controller is connected')
        if self.led_count is None and self.discover:
            self.led_count = count
        if count != self.led_count or (count == 0 and not self.discover):
            raise ValueError('WESP LED count changed; check configuration and reconnect')

    def _disconnect(self):
        for transport in (self.serial, self.sock):
            if transport is not None:
                transport.close()
        self.serial = self.sock = None
        self._buffer.clear()
        self.updated = 0
        self.last_frame = None

    def connect(self):
        if self.serial is not None or self.sock is not None:
            return
        self.sequence = 0
        self.session = secrets.token_hex(8)
        try:
            if self.connection == 'wifi':
                self._token = load_token(self.expected_mac)
                try:
                    self.sock = socket.create_connection((self.host, self.tcp_port), timeout=self.timeout)
                except OSError:
                    if not self.fallback_host or self.fallback_host == self.host:
                        raise
                    # Only DNS/connect failures may use the saved IPv4. Once
                    # connected, identity/token/count errors are final.
                    self.sock = socket.create_connection((self.fallback_host, self.tcp_port), timeout=self.timeout)
                self.sock.settimeout(.05)
            else:
                if not self.port or (not self.expected_mac and not self.discover):
                    raise ValueError('Select a WESP USB controller first')
                import serial
                self.serial = serial.Serial(port=None, baudrate=921600, timeout=.05,
                                            write_timeout=.3, exclusive=True)
                self.serial.dtr = self.serial.rts = False
                self.serial.port = self.port
                self.serial.open()
            reply = self._exchange('hello')
            if reply.get('firmware') != 'WESP':
                raise ValueError('WESP receiver firmware is required')
        except Exception:
            self._disconnect()
            raise

    def _exchange(self, op, fields=None):
        self.sequence += 1
        if self.sequence > 2147483647:
            raise ValueError('WESP request sequence exhausted; reconnect')
        request = dict(fields or {}, op=op, id=self.sequence, session=self.session)
        if op != 'hello' or self.connection == 'wifi':
            request['mac'] = self.expected_mac
        if self.connection == 'wifi':
            request['token'] = self._token
        packet = json.dumps(request, separators=(',', ':')).encode() + b'\n'
        if len(packet) > MAX_LINE:
            raise ValueError('WESP request is too large')
        started = time.monotonic()
        if self.sock is not None:
            self.sock.sendall(packet)
        elif self.serial is not None:
            if self.serial.write(packet) != len(packet):
                raise OSError('Incomplete WESP USB write')
        else:
            raise ValueError('WESP disconnected')
        partial_since = None
        deadline = started + self.timeout
        while time.monotonic() < deadline:
            if b'\n' in self._buffer:
                line, _, rest = self._buffer.partition(b'\n')
                self._buffer = bytearray(rest)
                try:
                    reply = json.loads(line)
                except (ValueError, UnicodeError):
                    raise ValueError('Invalid WESP JSON response') from None
                if not isinstance(reply, dict) or type(reply.get('id')) is not int or reply['id'] != self.sequence:
                    raise ValueError('Unexpected WESP acknowledgement ID')
                # Replies to every operation must repeat pinned identity/count.
                self.verify_identity(reply)
                if reply.get('ok') is not True:
                    # Firmware text is untrusted and may contain credentials.
                    raise ValueError('WESP rejected the request')
                if type(reply.get('on')) is not bool or type(reply.get('bri')) is not int or not 0 <= reply['bri'] <= 255:
                    raise ValueError('Invalid WESP state response')
                self.document = {key: copy.deepcopy(reply[key]) for key in
                    ('mac', 'proto', 'count', 'firmware', 'version', 'outputs', 'max_milliamps', 'wifi', 'on', 'bri', 'color', 'watchdog_ms') if key in reply}
                # Never retain arbitrary firmware fields (especially pair token).
                wifi = reply.get('wifi', {})
                if isinstance(wifi, dict):
                    self.document['wifi'] = dict(configured=wifi.get('configured') is True,
                                                 connected=wifi.get('connected') is True,
                                                 ip=wifi.get('ip') if isinstance(wifi.get('ip'), str) and len(wifi['ip']) <= 45 and re.fullmatch(r'[0-9a-fA-F:.]*', wifi['ip']) else '')
                    stable_host = 'wesp-' + self.expected_mac[-6:] + '.local'
                    if wifi.get('host') == stable_host:
                        self.document['wifi']['host'] = stable_host
                else:
                    self.document['wifi'] = {}
                if self.color is None and 'color' in reply:
                    self.color = _rgb(reply['color'])
                self.updated = time.monotonic()
                self.reply_sequence += 1
                self.last_exchange = dict(ok=True, kind=op, tx_bytes=len(packet), rx_bytes=len(line),
                                         elapsed_ms=round((self.updated-started)*1000, 2))
                return reply
            if len(self._buffer) >= MAX_LINE:
                raise ValueError('WESP response is too large')
            if partial_since is not None and time.monotonic()-partial_since > PARTIAL_TIMEOUT:
                raise TimeoutError('Incomplete WESP response timed out')
            try:
                chunk = self.sock.recv(1024) if self.sock is not None else self.serial.read(1024)
            except socket.timeout:
                continue
            if not chunk and self.sock is not None:
                raise OSError('WESP TCP disconnected')
            if chunk:
                partial_since = time.monotonic()
                self._buffer.extend(chunk)
                if len(self._buffer) > MAX_LINE:
                    raise ValueError('WESP response is too large')
        raise TimeoutError('No WESP response')

    def _run(self, op, fields=None):
        with self.query_lock:
            try:
                self.connect()
                return self._exchange(op, fields)
            except Exception:
                self._disconnect()
                raise

    def _state(self):
        document = self.document
        if document is None:
            raise ValueError('No confirmed WESP state')
        color = list(self.color or [0, 0, 0])
        return dict(on=document['on'], bri=document['bri'], live=False, lor=0,
                    seg=[dict(id=0, start=0, stop=self.led_count, len=self.led_count,
                              on=True, bri=255, col=[color, [0, 0, 0], [0, 0, 0]], fx=0,
                              sx=128, ix=128, pal=0, sel=True, rev=False, frz=False)])

    def query(self, payload=None):
        fields = {}
        if payload is not None:
            if not isinstance(payload, dict):
                raise ValueError('Invalid WESP state request')
            unsupported = set(payload) - {'on', 'bri', 'seg', 'tt', 'live', 'lor', 'mainseg'}
            if unsupported:
                raise ValueError('Unsupported WLED state field for WESP')
            for key in ('on', 'bri'):
                if key in payload:
                    value = payload[key]
                    if (key == 'on' and type(value) is not bool) or (key == 'bri' and (type(value) is not int or not 0 <= value <= 255)):
                        raise ValueError('Invalid WESP state value')
                    fields[key] = value
            segments = payload.get('seg', [])
            if isinstance(segments, dict):
                segments = [segments]
            if not isinstance(segments, list) or len(segments) > 1:
                raise ValueError('WESP supports one virtual segment')
            for segment in segments:
                if not isinstance(segment, dict) or segment.get('id', 0) != 0:
                    raise ValueError('WESP supports virtual segment 0 only')
                if segment.get('fx', 0) != 0 or segment.get('pal', 0) != 0:
                    raise ValueError('WESP does not support WLED effects or palettes')
                if set(segment) - {'id', 'col', 'fx', 'pal', 'start', 'stop', 'on', 'bri', 'sx', 'ix', 'sel', 'rev', 'frz'}:
                    raise ValueError('Unsupported WLED segment field for WESP')
                if 'col' in segment:
                    colors = segment['col']
                    if not isinstance(colors, list) or not colors:
                        raise ValueError('Invalid WESP color')
                    fields['color'] = _rgb(colors[0])
        with self.query_lock:
            self._run('state', fields)
            if 'color' in fields:
                self.color = fields['color']
            if not self.document['on']:
                self.last_frame = None
            elif fields.get('on') is True or 'color' in fields:
                # A user action supplies a NEW valid static frame. Polls never
                # acquire/renew a firmware lease; explicit maintain() does.
                self.pixels([list(self.color or [0, 0, 0]) for _ in range(self.led_count)])
            return self._state()

    def state(self, payload=None):
        with self.query_lock:
            return self.query(payload) if payload is not None else self._state()

    def pixels(self, pixels):
        if not isinstance(pixels, (list, tuple)) or not pixels or len(pixels) != self.led_count:
            raise ValueError('WESP frame LED count mismatch')
        raw = bytes(v for rgb in pixels for v in _rgb(rgb))
        with self.query_lock:
            self.connect()
            if not self.document['on']:
                return False
            self._run('frame', dict(count=self.led_count, pixels=base64.b64encode(raw).decode('ascii')))
            self.last_frame = raw
            self.last_frame_at = time.monotonic()
            self.frame_sequence += 1
            return True

    def maintain(self):
        with self.query_lock:
            if self.last_frame is None or self.document is None or not self.document['on'] or time.monotonic()-self.last_frame_at < .5:
                return False
            raw = self.last_frame
            self._run('frame', dict(count=self.led_count, pixels=base64.b64encode(raw).decode('ascii')))
            self.last_frame = raw
            self.last_frame_at = time.monotonic()
            self.frame_sequence += 1
            return True

    def configure(self, outputs, max_milliamps=500, ssid=None, password=None):
        if self.connection != 'usb':
            raise ValueError('WESP configuration requires physical USB')
        fields = dict(outputs=validate_outputs(outputs, max_milliamps), max_milliamps=max_milliamps)
        if ssid is not None:
            if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or not isinstance(password, str) or (password and not 8 <= len(password.encode()) <= 63):
                raise ValueError('Invalid WESP Wi-Fi credentials')
            fields['wifi'] = dict(ssid=ssid, password=password)
        elif password is not None:
            raise ValueError('WESP Wi-Fi SSID is required')
        with self.query_lock:
            self.connect()
            old_count = self.led_count
            self.led_count = sum(output['count'] for output in fields['outputs'])
            try:
                reply = self._run('configure', fields)
            except Exception:
                self.led_count = old_count
                raise
            self.last_frame = None
            # Only explicitly selected, non-secret fields leave this boundary.
            return {key: copy.deepcopy(self.document[key]) for key in
                    ('mac', 'count', 'outputs', 'max_milliamps', 'wifi') if key in self.document}

    def pair(self):
        if self.connection != 'usb':
            raise ValueError('WESP pairing requires physical USB')
        reply = self._run('pair')
        save_token(self.expected_mac, reply.get('token'))
        return dict(paired=True, mac=self.expected_mac)

    def setup_status(self):
        with self.query_lock:
            self.query()
            return {key: copy.deepcopy(self.document[key]) for key in
                    ('mac', 'count', 'outputs', 'max_milliamps', 'wifi', 'firmware', 'version', 'watchdog_ms')
                    if key in self.document}

    get_info = setup_status

    def link_status(self):
        with self.query_lock:
            self.query()
            return dict(backend='wesp', connection=self.connection, baud=self.baud,
                        target_baud=self.baud, fallback=False, mac=self.expected_mac,
                        reply_sequence=self.reply_sequence, frame_sequence=self.frame_sequence,
                        last_reply_age=round(time.monotonic()-self.updated, 3),
                        last_exchange=self.last_exchange.copy())

    def close(self):
        with self.query_lock:
            self._disconnect()
