"""MAC-pinned WESP v1 transport. Only explicit maintain() renews frames."""
import base64
import copy
import json
import ipaddress
import math
import hashlib
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


class ConfigurationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code=code


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
    udp_port = 19448
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
        self.fast_lock=threading.RLock()
        self.fast=None
        self.fast_retry_ns=0
        self.fast_stats=dict(sent=0,bytes=0,suppressed=0,dropped=0,max_source_age_ms=0)
        self.last_frame = None
        self.last_scene = None
        self.last_event_ref = {}
        self.last_palette = None
        self.last_heartbeat = 0
        self.audio_sequence = 0
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
        self.revoke_realtime()
        for transport in (self.serial, self.sock):
            if transport is not None:
                transport.close()
        self.serial = self.sock = None
        self._buffer.clear()
        self.updated = 0
        self.last_frame = None
        self.last_scene = None
        self.last_palette = None

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
                # CP2102 boards may reset as the port opens. Wait for firmware
                # startup, then discard ROM/banner bytes before the first hello.
                time.sleep(2)
                self.serial.reset_input_buffer()
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
        if op != 'hello' or self.expected_mac:
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
                allowed=('mac','proto','count','firmware','version','outputs','max_milliamps','wifi','capabilities','effects','ota_trial','build_sha256','audio_stats','on','bri','color','watchdog_ms')
                previous={} if op=='hello' else self.document or {}
                self.document={key:copy.deepcopy(previous[key]) for key in allowed if key in previous}
                self.document.update({key:copy.deepcopy(reply[key]) for key in allowed if key in reply})
                if 'capabilities' in reply:
                    caps=reply['capabilities']
                    self.document['capabilities']={key:caps.get(key) is True for key in ('wifi_configure','native_effects','realtime_audio','ota','preview') if isinstance(caps,dict) and key in caps}
                    if isinstance(caps,dict) and type(caps.get('max_presets')) is int and 1<=caps['max_presets']<=8:
                        self.document['capabilities']['max_presets']=caps['max_presets']
                if 'effects' in reply:
                    import effects_config
                    self.document['effects']=effects_config.validate(reply['effects'],self.led_count)
                if 'build_sha256' in reply and (not isinstance(reply['build_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',reply['build_sha256'])):
                    raise ValueError('Invalid native build identity')
                if 'audio_stats' in reply:
                    stats=reply['audio_stats'] if isinstance(reply['audio_stats'],dict) else {}
                    fields=('received','accepted','rejected','stale','reordered','age_ms','paint_delay_max_ms','render_age_ms','auth_us_max')
                    self.document['audio_stats']={key:stats[key] for key in fields if type(stats.get(key)) is int
                        and (-0x80000000 if key in ('age_ms','render_age_ms') else 0)<=stats[key]<=0xffffffff}
                # Never retain arbitrary firmware fields (especially pair token).
                wifi = reply.get('wifi')
                if 'wifi' in reply and isinstance(wifi, dict):
                    self.document['wifi'] = dict(configured=wifi.get('configured') is True,
                                                 connected=wifi.get('connected') is True,
                                                 ip=wifi.get('ip') if isinstance(wifi.get('ip'), str) and len(wifi['ip']) <= 45 and re.fullmatch(r'[0-9a-fA-F:.]*', wifi['ip']) else '')
                    stable_host = 'wesp-' + self.expected_mac[-6:] + '.local'
                    if wifi.get('host') == stable_host:
                        self.document['wifi']['host'] = stable_host
                elif 'wifi' in reply:
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
                chunk = (self.sock.recv(1024) if self.sock is not None else
                         self.serial.read(min(1024,max(1,getattr(self.serial,'in_waiting',0)))))
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
        if payload and payload.get('on') is False:self.revoke_realtime()
        with self.query_lock:
            if payload is None and self.realtime_active():return self._state()
            if payload is None and self.last_scene and self.native_effects():
                interval=(self.last_scene['config']['wallpaper_timeout_ms']*.000875 if self.last_scene['mode']!='music' else .25)
                if time.monotonic()-self.updated<interval:
                    return self._state()
            self._run('state', fields)
            if 'color' in fields:
                self.color = fields['color']
            if not self.document['on']:
                self.last_frame = None
                self.last_scene = None
            elif fields.get('on') is True or 'color' in fields:
                # A user action supplies a NEW valid static frame. Polls never
                # acquire/renew a firmware lease; explicit maintain() does.
                if self.native_effects() and self.document.get('effects'):
                    if 'color' in fields:self.effect('solid',fields['color'],self.document['effects'])
                else:
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
            self.revoke_realtime()
            self._run('frame', dict(count=self.led_count, pixels=base64.b64encode(raw).decode('ascii')))
            self.last_frame = raw
            self.last_scene = None
            self.last_frame_at = time.monotonic()
            self.frame_sequence += 1
            return True

    def maintain(self):
        with self.query_lock:
            if self.last_scene is not None:
                if not self.document or not self.document['on'] or self.last_scene['mode']=='music':return False
                interval=self.last_scene['config']['wallpaper_timeout_ms']*.000875
                if time.monotonic()-self.last_heartbeat<interval:return False
                sent_at=time.monotonic()
                self._run('heartbeat',{'revision':self.last_scene['config']['revision']})
                self.last_heartbeat=sent_at
                return True
            if self.last_frame is None or self.document is None or not self.document['on'] or time.monotonic()-self.last_frame_at < .5:
                return False
            raw = self.last_frame
            self._run('frame', dict(count=self.led_count, pixels=base64.b64encode(raw).decode('ascii')))
            self.last_frame = raw
            self.last_frame_at = time.monotonic()
            self.frame_sequence += 1
            return True

    def refresh_interval(self):
        """Wake at the actual deadline even for the shortest wallpaper lease."""
        with self.query_lock:
            if self.last_scene and self.last_scene['mode']!='music':
                due=self.last_heartbeat+self.last_scene['config']['wallpaper_timeout_ms']*.000875
                return max(.001,min(.25,due-time.monotonic()))
            return .25

    def supports_realtime(self):
        return self.connection=='wifi' and bool(self.document and self.document.get('capabilities',{}).get('realtime_audio'))

    def revoke_realtime(self):
        with self.fast_lock:
            previous,self.fast=self.fast,None
            if previous is not None:previous['socket'].close()

    def realtime_active(self):
        import realtime_protocol as rt
        with self.fast_lock:
            return bool(self.fast and self.fast['clock'].valid(rt.now_ns()))

    def realtime_palette(self,colors,config):
        if colors is None and self.last_palette is None:return
        import effects_config
        palette=(effects_config.colors(colors) if colors is not None else
            next(p['colors'] for p in config['presets'] if p['id']==config['active']))
        if palette==self.last_palette:return
        self._run('palette',{'revision':config['revision'],'colors':palette})
        self.last_palette=palette if colors is not None else None

    def prepare_realtime(self,config,colors=None):
        import realtime_protocol as rt
        with self.query_lock:
            self.connect()
            if not self.supports_realtime() or not self.document.get('on'):
                self.revoke_realtime();return False
            self.effects_configure(config)
            with self.fast_lock:current=self.fast
            if current and current['revision']==config['revision'] and current['session']==self.session:
                self.realtime_palette(colors,config)
                now=rt.now_ns()
                if now-current['clock'].received_ns<5_000_000_000:return True
                if now-current.get('sync_attempt_ns',0)<1_000_000_000:return current['clock'].valid(now)
                current['sync_attempt_ns']=now
                sent=rt.now_ns();reply=self._run('audio_clock');received=rt.now_ns()
                with self.fast_lock:
                    if self.fast is current:current['clock'].sync(sent,received,reply.get('audio_clock_ms'))
                return self.realtime_active()
            if rt.now_ns()<self.fast_retry_ns:return False
            self.fast_retry_ns=rt.now_ns()+1_000_000_000
            sent=rt.now_ns();reply=self._run('audio_open',{'revision':config['revision']});received=rt.now_ns()
            value=reply.get('audio_stream',{})
            if (not isinstance(value,dict) or not isinstance(value.get('id'),str) or not re.fullmatch('[0-9a-f]{16}',value['id'])
                    or not isinstance(value.get('key'),str) or not re.fullmatch('[0-9a-f]{64}',value['key']) or value.get('port')!=self.udp_port):
                raise ValueError('Invalid real-time audio grant')
            clock=rt.AudioClock()
            if not clock.sync(sent,received,value.get('clock_ms')):return False
            udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.setblocking(False)
            target=(self.sock.getpeername()[0],self.udp_port)
            self.last_palette=None
            try:self.realtime_palette(colors,config)
            except Exception:udp.close();raise
            with self.fast_lock:
                self.revoke_realtime()
                self.fast=dict(socket=udp,target=target,key=bytes.fromhex(value['key']),sid=bytes.fromhex(value['id']),
                    sequence=0,clock=clock,delta=rt.DeltaPolicy(),revision=config['revision'],session=self.session)
            self.fast_retry_ns=0
            self.last_scene=dict(mode='music',config=copy.deepcopy(config),updated=time.monotonic())
            self.last_frame=None
            return True

    def send_realtime(self,mac,count,captured_ns,rms,bass):
        import realtime_protocol as rt
        with self.fast_lock:
            context=self.fast
            if (not context or mac!=self.expected_mac or count!=self.led_count or not self.document
                    or not self.document.get('on') or context['session']!=self.session):return False
            now=rt.now_ns()
            try:stamp=context['clock'].stamp(captured_ns,now)
            except ValueError:self.fast_stats['dropped']+=1;return False
            if not context['delta'].eligible(rms,bass,now):self.fast_stats['suppressed']+=1;return False
            sequence=context['sequence']+1
            if sequence>0x7fffffff:self.revoke_realtime();return False
            packet=rt.pack_audio(context['key'],context['sid'],sequence,stamp,rms,bass)
            try:
                if context['socket'].sendto(packet,context['target'])!=rt.PACKET_SIZE:raise OSError('Incomplete audio datagram')
            except OSError:self.fast_stats['dropped']+=1;return False
            context['sequence']=sequence;context['delta'].sent(rms,bass,now)
            self.fast_stats['sent']+=1;self.fast_stats['bytes']+=len(packet)
            self.fast_stats['max_source_age_ms']=max(self.fast_stats['max_source_age_ms'],(now-captured_ns)/1e6)
            self.audio_sequence+=1
            return True

    def native_effects(self):
        return bool(self.document and self.document.get('capabilities',{}).get('native_effects'))

    def effects_configure(self,config):
        import effects_config
        if self.document and self.document.get('effects')==config:return self.document['effects']
        clean=effects_config.validate(config,self.led_count)
        with self.query_lock:
            self.connect()
            if not self.native_effects():raise ValueError('Update native firmware to enable local effects')
            if self.document.get('effects')==clean:return clean
            self.revoke_realtime()
            self._run('effects_configure',{'effects':clean})
            actual=self.setup_status().get('effects')
            if actual!=clean:raise ConfigurationError('configuration_unconfirmed','Native effects configuration read-back failed')
            if self.last_scene:self.last_scene['config']=copy.deepcopy(clean)
            self.last_palette=None
            return actual

    def features(self,rms,bass,config,colors=None):
        if any(type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=1 for n in (rms,bass)):
            raise ValueError('Invalid raw audio features')
        with self.query_lock:
            self.connect()
            if not self.document['on']:return False
            self.effects_configure(config)
            self.revoke_realtime()
            self._run('audio',dict(rms=rms,bass=bass,revision=config['revision']))
            self.last_scene=dict(mode='music',config=copy.deepcopy(config),rms=rms,bass=bass,updated=time.monotonic())
            self.last_frame=None;self.audio_sequence+=1
            if colors is not None and colors!=self.last_palette:
                import effects_config
                palette=effects_config.colors(colors)
                self._run('palette',dict(revision=config['revision'],colors=palette))
                self.last_palette=palette
            return True

    def effect(self,mode,color,config):
        color=_rgb(color)
        if mode not in ('solid','runner'):raise ValueError('Unknown native effect')
        with self.query_lock:
            self.connect()
            if not self.document['on']:return False
            self.effects_configure(config)
            if self.last_scene and self.last_scene['mode']==mode and self.last_scene.get('color')==color:return True
            self.revoke_realtime()
            sent_at=time.monotonic()
            self._run('effect',dict(mode=mode,color=color,revision=config['revision']))
            self.color=list(color)
            self.last_scene=dict(mode=mode,color=color,config=copy.deepcopy(config),updated=time.monotonic())
            self.last_frame=None;self.last_heartbeat=sent_at
            return True

    def event(self,kind,ref,value,config):
        if kind not in ('notification','volume','clear','clear_volume') or not isinstance(ref,str) or not re.fullmatch('[0-9a-f]{16}',ref):
            raise ValueError('Invalid native event')
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('Invalid native event value')
        with self.query_lock:
            self.connect()
            if not self.document['on']:return False
            self.effects_configure(config)
            if self.last_event_ref.get(kind)==ref:return True
            if not self.last_scene:self.effect('solid',list(self.color or [0,0,0]),config)
            self._run('event',dict(kind=kind,ref=ref,value=value,revision=config['revision']))
            self.last_event_ref[kind]=ref
            if kind=='notification':self.last_event_ref.pop('clear',None)
            if kind=='volume':self.last_event_ref.pop('clear_volume',None)
            return True

    def ota_upload(self,image,progress=None):
        if not isinstance(image,bytes) or not 256<=len(image)<=1310720 or image[0]!=0xe9:
            raise ValueError('Invalid ESP32 application image')
        with self.query_lock:
            self.connect()
            if not self.document.get('capabilities',{}).get('ota'):raise ValueError('Update firmware over USB once to enable OTA')
            self.query({'on':False})
            try:
                started=time.monotonic()
                self._run('ota_begin',dict(size=len(image),sha256=hashlib.sha256(image).hexdigest()))
                last=-1
                for offset in range(0,len(image),1024):
                    if time.monotonic()-started>60:raise TimeoutError('OTA upload timed out')
                    chunk=image[offset:offset+1024]
                    self._run('ota_chunk',dict(offset=offset,data=base64.b64encode(chunk).decode('ascii')))
                    percent=int((offset+len(chunk))*100/len(image))
                    if progress and percent!=last:progress(percent);last=percent
                self._run('ota_finish')
            except Exception:
                if self.serial is not None or self.sock is not None:
                    try:self._exchange('ota_abort')
                    except Exception:pass
                raise
            finally:
                self._disconnect()

    def preview(self):
        with self.query_lock:
            self.connect()
            if not self.document.get('capabilities',{}).get('preview') or not self.led_count:return None
            reply=self._run('preview')
            value=reply.get('pixels')
            if not isinstance(value,str) or len(value)!=self.led_count*4:raise ValueError('Invalid ESP preview')
            try:raw=base64.b64decode(value,validate=True)
            except ValueError:raise ValueError('Invalid ESP preview') from None
            if len(raw)!=self.led_count*3:raise ValueError('Invalid ESP preview count')
            return dict(target='device',mac=self.expected_mac,pixels=[list(raw[i:i+3]) for i in range(0,len(raw),3)],
                        brightness=255,source='esp',updated=time.monotonic(),sequence=self.reply_sequence,stale=False)

    def configure(self, outputs, max_milliamps=500, ssid=None, password=None):
        fields = dict(outputs=validate_outputs(outputs, max_milliamps), max_milliamps=max_milliamps)
        if self.connection != 'usb' and (ssid is not None or password is not None):
            raise ConfigurationError('network_requires_usb','Use USB to change the WESP Wi-Fi network')
        if ssid is not None:
            if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or not isinstance(password, str) or (password and not 8 <= len(password.encode()) <= 63):
                raise ValueError('Invalid WESP Wi-Fi credentials')
            fields['wifi'] = dict(ssid=ssid, password=password)
        elif password is not None:
            raise ValueError('WESP Wi-Fi SSID is required')
        with self.query_lock:
            if self.connection=='wifi':
                if not self.setup_status(refresh_count=True).get('capabilities',{}).get('wifi_configure'):
                    raise ConfigurationError('firmware_update_required','Update WESP receiver firmware over USB to configure outputs over Wi-Fi')
            else:
                self.connect()
            self.revoke_realtime()
            old_count = self.led_count
            self.last_frame = None
            self.led_count = sum(output['count'] for output in fields['outputs'])
            try:
                self._run('configure', fields)
            except Exception:
                self.led_count = old_count
                raise
            # A write ACK is insufficient: read the exact same authenticated
            # receiver again before reporting success to the UI or persisting.
            result=self.setup_status()
            if result.get('outputs')!=fields['outputs'] or result.get('max_milliamps')!=max_milliamps:
                raise ConfigurationError('configuration_unconfirmed','Could not confirm the saved WESP configuration; read settings again')
            # Only explicitly selected, non-secret fields leave this boundary.
            return result

    def pair(self):
        if self.connection != 'usb':
            raise ValueError('WESP pairing requires physical USB')
        reply = self._run('pair')
        save_token(self.expected_mac, reply.get('token'))
        return dict(paired=True, mac=self.expected_mac)

    def setup_status(self,refresh_count=False):
        with self.query_lock:
            # State/frame ACKs intentionally contain only the common fields.
            # Request full current metadata, including asynchronous Wi-Fi join.
            previous_count,previous_discover=self.led_count,self.discover
            if refresh_count:
                # Explicit management reads can recover an uncertain CFG ACK.
                # MAC/token checks remain mandatory; ordinary frames/polls
                # never use this exception to the saved-count guard.
                self.led_count=None;self.discover=True
            try:
                self._run('hello')
                if self.led_count!=previous_count:
                    self.last_frame=None
            except Exception:
                self.led_count=previous_count
                raise
            finally:
                self.discover=previous_discover
            result = {key: copy.deepcopy(self.document[key]) for key in
                      ('mac', 'count', 'outputs', 'max_milliamps', 'wifi', 'capabilities', 'effects', 'ota_trial', 'build_sha256', 'audio_stats', 'firmware', 'version', 'watchdog_ms')
                      if key in self.document}
            result['connection'] = self.connection
            return result

    get_info = setup_status

    def link_status(self):
        with self.query_lock:
            self.query()
            return dict(backend='wesp', connection=self.connection, baud=self.baud,
                        target_baud=self.baud, fallback=False, mac=self.expected_mac,
                        reply_sequence=self.reply_sequence, frame_sequence=self.frame_sequence,
                        audio_sequence=self.audio_sequence,
                        realtime=self.fast_stats.copy(),
                        last_reply_age=round(time.monotonic()-self.updated, 3),
                        last_exchange=self.last_exchange.copy())

    def close(self):
        with self.query_lock:
            self._disconnect()
