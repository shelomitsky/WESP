"""Real AF_UNIX service/client processes; only the physical serial link is fake.

Socket permission failures are failures, not skipped acceptance. Run the release
gate on an unrestricted Linux runner when the local sandbox forbids AF_UNIX.
"""
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAC = '021122334455'
PORT = '/dev/ttyUSB8'
SECOND_PORT = '/dev/ttyUSB9'
SECOND_MAC = '021122334466'


class UART:
    """Small WLED serial peer: JSON state, temporary baud and Adalight sink."""

    def __init__(self, port, baudrate, timeout, write_timeout, exclusive):
        self.port = port
        self.baudrate = baudrate
        self.is_open = False
        self.buffer = b''
        self.state = dict(on=True, bri=128, lor=0, live=False)

    def open(self):
        if self.port not in (PORT, SECOND_PORT):
            raise ValueError('Test peer refuses any other serial endpoint')
        self.is_open = True

    @property
    def in_waiting(self):
        return len(self.buffer)

    def flush(self):
        pass

    def reset_input_buffer(self):
        self.buffer = b''

    def write(self, packet):
        peer_file = Path(os.environ['WLED_TEST_UART_PEER'])
        peer = json.loads(peer_file.read_text()) if peer_file.exists() else {}
        if self.port in peer.get('offline', []):
            raise OSError('Test controller disconnected')
        with Path(os.environ['WLED_TEST_UART_TRACE']).open('a') as stream:
            stream.write(json.dumps(packet.hex()) + '\n')
        if packet.startswith(b'{'):
            self.state.update({k: v for k, v in json.loads(packet).items() if k != 'v'})
            info = peer.get('ports', {}).get(self.port, {})
            mac = info.get('mac', SECOND_MAC if self.port == SECOND_PORT else MAC)
            document = dict(state=self.state,
                info=dict(mac=mac, leds=dict(count=info.get('count', 2))))
            self.buffer = json.dumps(document).encode() + b'\n'
        return len(packet)

    def read(self, count):
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def close(self):
        self.is_open = False


def serve_test_peer():
    # Patch the physical dependency before loading the real service. No fake
    # Device, Handler, socket, client, identity check or file lock is involved.
    from unittest.mock import patch
    sys.path.insert(0, str(ROOT))
    import usb_transport
    with patch('serial.Serial', UART):
        usb_transport.serve()


class IPCIntegrationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='wled-ipc-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.env = dict(os.environ, HOME=str(self.base / 'home'),
            XDG_CONFIG_HOME=str(self.base / 'config'),
            XDG_DATA_HOME=str(self.base / 'data'),
            XDG_STATE_HOME=str(self.base / 'state'),
            XDG_CACHE_HOME=str(self.base / 'cache'),
            XDG_RUNTIME_DIR=str(self.base / 'runtime'),
            WLED_CONFIG_DIR=str(self.base / 'config/app'),
            WLED_RUNTIME_DIR=str(self.base / 'runtime/app'),
            WLED_TEST_UART_TRACE=str(self.base / 'uart.jsonl'),
            WLED_TEST_UART_PEER=str(self.base / 'peer.json'),
            # Keep the invoking interpreter's installed dependencies available
            # even when they are in its user site; HOME still stays isolated.
            PYTHONPATH=os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p),
            DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(self.base / 'no-user-bus'),
            LANGUAGE='en', LC_ALL='C.UTF-8', PYTHONDONTWRITEBYTECODE='1')
        self.env.pop('WLED_TRANSPORT', None)
        self.socket = self.base / 'runtime/app/usb.sock'
        self.settings_file = self.base / 'config/app/settings.json'
        self.settings_file.parent.mkdir(parents=True)
        self.configure()

    def configure(self, mac=MAC, count=2):
        selected = None if mac is None else dict(port=PORT, mac=mac, count=count)
        temporary = self.settings_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(controller=selected)))
        temporary.replace(self.settings_file)

    def start_service(self):
        log = (self.base / ('service-' + str(time.monotonic_ns()) + '.log')).open('w+')
        self.addCleanup(log.close)
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve'],
            env=self.env, cwd=ROOT, stdout=log, stderr=log)
        self.addCleanup(self.stop_service, process)
        process.test_log = log
        return process

    def stop_service(self, process):
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
            self.fail('USB service did not stop after SIGTERM')
        self.assertEqual(process.returncode, 0)

    def client(self, expression):
        # Independent config import and process for every ordinary client call.
        code = ('import json,usb_transport as usb,control\n'
                'try:\n result=' + expression + '\n'
                'except Exception as error:\n print(json.dumps(dict(ok=False,error=str(error))))\n'
                'else:\n print(json.dumps(dict(ok=True,result=result)))\n')
        result = subprocess.run([sys.executable, '-c', code], env=self.env, cwd=ROOT,
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def wait_ready(self, process, configured=True):
        deadline = time.monotonic() + 15
        last = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                process.test_log.seek(0)
                self.fail('USB service exited: ' + process.test_log.read())
            if self.socket.exists():
                if not configured:
                    return
                last = self.client('usb.client(link=True)')
                if last['ok']:
                    return last['result']
            time.sleep(.02)
        self.fail('USB service was not ready: ' + str(last))

    def packets(self):
        file = self.base / 'uart.jsonl'
        return [bytes.fromhex(json.loads(line)) for line in file.read_text().splitlines()] if file.exists() else []

    def test_state_frames_power_and_graceful_shutdown_across_processes(self):
        process = self.start_service()
        self.wait_ready(process)
        self.assertEqual(stat.S_IMODE(self.socket.stat().st_mode), 0o600)
        self.assertEqual(self.client('usb.client()')['result']['bri'], 128)
        changed = self.client("control.request(control.settings(), {'bri':73})")
        self.assertTrue(changed['ok'], changed)
        self.assertEqual(changed['result']['bri'], 73)
        self.assertFalse(changed['result']['live'])
        self.assertEqual(self.client('usb.client(pixels=[[12,34,56],[44,55,66]])'),
                         dict(ok=True, result=True))
        # Two RGB pixels: count-1=1, checksum=0x54, literal RGB payload.
        frames = [packet for packet in self.packets() if packet.startswith(b'Ada')]
        self.assertEqual(frames, [bytes.fromhex('4164610001540c22382c3742')])
        self.assertEqual(self.client('usb.client(link=True)')['result']['frame_sequence'], 1)
        self.assertFalse(self.client("control.request(control.settings(), {'on':False})")['result']['on'])
        self.assertEqual(self.client('usb.client(pixels=[[255,0,0],[255,0,0]])'),
                         dict(ok=True, result=False))
        self.assertEqual(len([p for p in self.packets() if p.startswith(b'Ada')]), 1)
        self.assertTrue(self.client("usb.client(payload={'on':True,'live':True})")['result']['live'])
        before_shutdown = len(self.packets())
        self.stop_service(process)
        self.assertFalse(self.socket.exists())
        packets = self.packets()[before_shutdown:]
        self.assertTrue(any(p.startswith(b'{') and json.loads(p).get('live') is False for p in packets))
        self.assertIn(b'\xb0', packets)

    def test_unconfigured_enrollment_and_stale_selection_reject_frames(self):
        self.configure(mac=None)
        process = self.start_service()
        self.wait_ready(process, configured=False)
        self.assertFalse(self.client('usb.client()')['ok'])
        self.assertFalse(self.client("usb.client(enroll='/dev/ttyS0')")['ok'])
        self.assertEqual(self.packets(), [])
        wrong = self.client("usb.client(enroll='/dev/ttyUSB8', expected={'mac':'020000000099','count':2})")
        self.assertFalse(wrong['ok'])
        self.assertFalse(any(p in (b'\xb0', b'\xb5') for p in self.packets()))
        enrolled = self.client("usb.client(enroll='/dev/ttyUSB8')")
        self.assertEqual(enrolled, dict(ok=True, result=dict(port=PORT, mac=MAC, count=2)))
        self.configure()
        self.assertTrue(self.client('usb.client()')['ok'])
        for mac, count in (('020000000099', 2), (MAC, 3)):
            self.configure(mac=mac, count=count)
            self.assertFalse(self.client('usb.client(pixels=[[1,2,3],[4,5,6]])')['ok'])
        self.assertFalse(any(p.startswith(b'Ada') for p in self.packets()))
        self.configure()
        self.assertTrue(self.client('usb.client()')['ok'])

    def test_malformed_requests_do_not_kill_service_or_write_frames(self):
        process = self.start_service()
        self.wait_ready(process)
        for packet in (b'not-json\n', b'[]\n',
                       b'{"kind":"pixels","controller_mac":"021122334455","controller_count":2,"pixels":[]}\n'):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(4)
                connection.connect(str(self.socket))
                connection.sendall(packet)
                with connection.makefile('rb') as stream:
                    response = json.loads(stream.readline())
            self.assertFalse(response['ok'], response)
            self.assertTrue(response['error'])
            self.assertTrue(self.client('usb.client(link=True)')['ok'])
        self.assertFalse(any(p.startswith(b'Ada') for p in self.packets()))

    def test_second_owner_preserves_first_socket_then_takes_over_after_shutdown(self):
        first = self.start_service()
        self.wait_ready(first)
        inode = self.socket.stat().st_ino
        second = self.start_service()
        try:
            # The second process has started and must wait on the real owner
            # lock. Repeated clients must still reach the original service.
            for _ in range(3):
                self.assertTrue(self.client('usb.client(link=True)')['ok'])
                self.assertEqual(self.socket.stat().st_ino, inode)
                self.assertIsNone(second.poll())
            self.stop_service(first)
            self.wait_ready(second)
            self.assertTrue(self.client('usb.client()')['ok'])
        finally:
            # A blocked flock cannot process SIGTERM until the first exits.
            self.stop_service(first)
            self.stop_service(second)
        self.assertFalse(self.socket.exists())

    def test_explicit_enrollment_recovers_when_previous_board_is_unavailable_or_changed(self):
        cases = (
            (dict(offline=[PORT]), SECOND_PORT, SECOND_MAC, 2),
            (dict(ports={PORT:dict(mac=SECOND_MAC)}), PORT, SECOND_MAC, 2),
            (dict(ports={PORT:dict(count=3)}), PORT, MAC, 3),
        )
        for peer, port, mac, count in cases:
            with self.subTest(peer=peer):
                self.configure()
                peer_file = self.base/'peer.json'
                peer_file.write_text('{}')
                process = self.start_service()
                try:
                    self.wait_ready(process)
                    peer_file.write_text(json.dumps(peer))
                    result = self.client("control.dispatch(['enroll'," + repr(port) + "])")
                    self.assertTrue(result['ok'], result)
                    self.assertEqual(result['result']['settings']['controller'],
                                     dict(port=port, mac=mac, count=count))
                    self.assertEqual(self.client('usb.client(link=True)')['result']['mac'], mac)
                finally:
                    self.stop_service(process)

    def test_failed_enrollment_persistence_keeps_service_and_saved_selection_consistent(self):
        process = self.start_service()
        self.wait_ready(process)
        runtime = self.base/'runtime/app/state.json'
        runtime.write_text(json.dumps(dict(controller_mac=MAC, ids=[], volumeUntil=0,
            base={'4':dict(fx=9)}, suspended=False, resume=None)))
        before = {p:p.read_bytes() for p in (self.settings_file, runtime)}
        # This is a real filesystem failure in both the CLI and server process,
        # not a mocked enrollment callback. Per-user acceptance runs unprivileged.
        self.settings_file.parent.chmod(0o500)
        try:
            result = self.client("control.dispatch(['enroll','/dev/ttyUSB9'])")
            self.assertFalse(result['ok'], result)
        finally:
            self.settings_file.parent.chmod(0o700)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        healthy = self.client('usb.client(payload={})')
        self.assertTrue(healthy['ok'], healthy)
        self.assertEqual(self.client('usb.client(link=True)')['result']['mac'], MAC)

    def test_enrollment_cannot_interleave_with_an_old_snapshot_restore(self):
        process = self.start_service()
        self.wait_ready(process)
        ready, release = self.base/'restore-ready', self.base/'restore-release'
        holder_code = '''import control,time
from pathlib import Path
with control.locked():
    prefs=control.settings()
    Path(%r).touch()
    deadline=time.monotonic()+12
    while not Path(%r).exists():
        if time.monotonic()>deadline: raise RuntimeError('restore release timeout')
        time.sleep(.01)
    control.request(prefs,{'seg':[{'id':0,'fx':77,'col':[[100,20,30]]}]})
''' % (str(ready), str(release))
        holder = subprocess.Popen([sys.executable,'-c',holder_code],env=self.env,cwd=ROOT,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        enrollment = None
        try:
            deadline = time.monotonic()+4
            while not ready.exists() and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists())
            enrollment = subprocess.Popen([sys.executable,'-c',
                "import json,usb_transport; print(json.dumps(usb_transport.client(enroll='/dev/ttyUSB9')))"],
                env=self.env,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            # The direct protocol operation must wait for the in-flight
            # command, even though candidate identity can be verified quickly.
            with self.assertRaises(subprocess.TimeoutExpired):
                enrollment.communicate(timeout=2.5)
            release.touch()
            stdout, stderr = holder.communicate(timeout=8)
            self.assertEqual(holder.returncode,0,stderr)
            stdout, stderr = enrollment.communicate(timeout=8)
            self.assertEqual(enrollment.returncode,0,stderr)
            self.assertEqual(json.loads(stdout)['mac'],SECOND_MAC)
            state = self.client('usb.client(payload={})')
            self.assertTrue(state['ok'],state)
            self.assertNotIn('seg',state['result'],'old snapshot reached the new board')
        finally:
            release.touch()
            for child in (holder,enrollment):
                if child is not None and child.poll() is None:
                    try:
                        child.communicate(timeout=8)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.communicate(timeout=3)


if __name__ == '__main__':
    if sys.argv[1:] == ['--serve']:
        serve_test_peer()
    else:
        unittest.main()
