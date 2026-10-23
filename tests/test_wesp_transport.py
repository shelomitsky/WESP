import json
import socket
import threading
import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path

try:
    import wesp_transport as wesp
except ImportError:
    wesp = None

MAC = '680947485628'
TOKEN = 'ab' * 32


class Receiver:
    def __init__(self, change=None):
        self.change = change
        self.requests = []
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            connection, _ = self.listener.accept()
            with connection, connection.makefile('rb') as stream:
                on, bri = False, 255
                while line := stream.readline():
                    request = json.loads(line)
                    self.requests.append(request)
                    if request['op'] == 'state':
                        on = request.get('on', on)
                        bri = request.get('bri', bri)
                    reply = dict(ok=True, id=request['id'], mac=MAC, proto=1,
                                 firmware='WESP', count=2, outputs=[], on=on,
                                 bri=bri, color=[10, 20, 30], watchdog_ms=1500)
                    if request.get('token') != TOKEN:
                        reply.update(ok=False, error='bad token ' + TOKEN)
                    if self.change:
                        self.change(request, reply)
                    connection.sendall(json.dumps(reply).encode() + b'\n')
        except OSError:
            pass
        finally:
            self.listener.close()

    def close(self):
        self.listener.close()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(wesp, 'native transport must be implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name)
        self.patch = patch.object(wesp, 'credentials_path', return_value=self.config / 'credentials.json')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        wesp.save_token(MAC, TOKEN)

    def device(self, change=None):
        server = Receiver(change)
        self.addCleanup(server.close)
        device = wesp.Device(host='127.0.0.1', connection='wifi', expected_mac=MAC, led_count=2)
        device.tcp_port = server.port
        self.addCleanup(device.close)
        return device, server

    def test_tcp_state_frames_and_explicit_maintenance(self):
        device, server = self.device()
        self.assertFalse(device.query()['on'])
        self.assertFalse(device.pixels([[1, 2, 3]] * 2))
        state = device.query({'on': True, 'bri': 100, 'seg': [{'id': 0, 'col': [[1, 2, 3]], 'fx': 0}]})
        self.assertEqual(state['bri'], 100)
        self.assertEqual(state['seg'][0]['stop'], 2)
        self.assertTrue(device.pixels([[1, 2, 3]] * 2))
        device.last_frame_at -= .51
        self.assertTrue(device.maintain())
        self.assertEqual([r['op'] for r in server.requests].count('frame'), 3)
        device.query({'on': False})
        self.assertFalse(device.maintain())
        self.assertNotIn(TOKEN, json.dumps(device.link_status()))

    def test_wrong_mac_count_and_ack_id_rejected(self):
        for field, value in [('mac', '111111111111'), ('count', 3), ('id', 99)]:
            with self.subTest(field=field):
                device, _ = self.device(lambda req, reply: reply.update({field: value}))
                with self.assertRaises(ValueError):
                    device.query()

    def test_invalid_frames_and_effects_rejected(self):
        device, _ = self.device()
        device.query({'on': True})
        for pixels in [[], [[1, 2, 3]], [[1, 2, 256]] * 2]:
            with self.assertRaises(ValueError):
                device.pixels(pixels)
        with self.assertRaisesRegex(ValueError, 'effect'):
            device.query({'seg': [{'id': 0, 'fx': 42}]})

    def test_credentials_private_and_token_error_redacted(self):
        self.assertEqual((self.config / 'credentials.json').stat().st_mode & 0o777, 0o600)
        device, _ = self.device(lambda req, reply: reply.update(ok=False, error=TOKEN))
        with self.assertRaises(ValueError) as error:
            device.query()
        self.assertNotIn(TOKEN, str(error.exception))

    def test_static_color_and_on_create_fresh_frames_but_poll_does_not(self):
        device, server = self.device()
        self.assertEqual(device.baud, 921600)
        device.query({'seg': [{'id': 0, 'col': [[9, 8, 7]]}]})
        self.assertFalse(any(r['op'] == 'frame' for r in server.requests))
        device.query({'on': True})
        frames = [r for r in server.requests if r['op'] == 'frame']
        self.assertEqual(len(frames), 1)
        self.assertEqual(__import__('base64').b64decode(frames[0]['pixels']), bytes([9, 8, 7]) * 2)
        device.query()
        self.assertEqual(len([r for r in server.requests if r['op'] == 'frame']), 1)
        device.query({'seg': [{'id': 0, 'col': [[5, 4, 3]]}]})
        self.assertEqual(len([r for r in server.requests if r['op'] == 'frame']), 2)
        self.assertEqual(device.state()['seg'][0]['col'][0], [5, 4, 3])

    def test_missing_token_refuses_connection_and_wifi_setup(self):
        (self.config / 'credentials.json').unlink()
        device = wesp.Device(host='127.0.0.1', connection='wifi', expected_mac=MAC, led_count=2)
        with patch.object(socket, 'create_connection') as connect:
            with self.assertRaisesRegex(ValueError, 'Pair'):
                device.query()
            connect.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'USB'):
            device.pair()
        with self.assertRaisesRegex(ValueError, 'USB'):
            device.configure([dict(gpio=2, count=2, order='GRB')], 500)

    def test_setup_status_sanitizes_wifi(self):
        device, _ = self.device(lambda req, reply: reply.update(wifi=dict(configured=True, connected=True, ip='192.0.2.2', host='wesp-485628.local', password='secret', token=TOKEN)))
        status = device.setup_status()
        self.assertEqual(status['wifi']['ip'], '192.0.2.2')
        self.assertEqual(status['wifi']['host'], 'wesp-485628.local')
        self.assertNotIn('password', json.dumps(status))
        self.assertNotIn(TOKEN, json.dumps(status))

    def test_sequence_session_and_private_state(self):
        device, server = self.device()
        device.query()
        device.query({'on': True})
        self.assertEqual([r['id'] for r in server.requests], [1, 2, 3, 4])
        sessions = {r['session'] for r in server.requests}
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(sessions.pop()), 16)
        self.assertEqual(server.requests[0]['mac'], MAC)
        self.assertNotIn('token', device.document)
        state = device.state()
        state['seg'][0]['col'][0][0] = 200
        self.assertEqual(device.state()['seg'][0]['col'][0][0], 10)

    def test_bounded_invalid_json_oversize_partial_and_no_response(self):
        class Stream:
            def __init__(self, chunks):
                self.chunks = list(chunks)
            def write(self, packet):
                return len(packet)
            def read(self, count):
                return self.chunks.pop(0) if self.chunks else b''
            def close(self):
                pass
        for chunks, expected in [([b'not-json\n'], ValueError),
                                 ([b'x' * 8193], ValueError),
                                 ([b'{'], TimeoutError), ([], TimeoutError)]:
            with self.subTest(expected=expected):
                device = wesp.Device(port='/dev/fake', expected_mac=MAC, led_count=2)
                device.serial = Stream(chunks)
                device.session = 'a' * 16
                device.timeout = .03
                started = __import__('time').monotonic()
                with self.assertRaises(expected):
                    device.query()
                self.assertLess(__import__('time').monotonic() - started, .5)
                self.assertIsNone(device.serial)

    def test_usb_configure_pair_and_count_guard(self):
        class Stream:
            def __init__(self):
                self.reply = b''
                self.requests = []
                self.count = 0
            def write(self, packet):
                request = json.loads(packet)
                self.requests.append(request)
                if request['op'] == 'configure':
                    self.count = sum(o['count'] for o in request['outputs'])
                reply = dict(ok=True, id=request['id'], proto=1, mac=MAC,
                             firmware='WESP', count=self.count, on=False, bri=255)
                if request['op'] == 'pair':
                    reply['token'] = TOKEN
                self.reply = json.dumps(reply).encode() + b'\n'
                return len(packet)
            def read(self, size):
                data, self.reply = self.reply, b''
                return data
            def close(self):
                pass
        device = wesp.Device(port='/dev/fake', discover=True)
        device.serial = stream = Stream()
        device.session = 'a' * 16
        device.query()
        self.assertEqual(device.led_count, 0)
        result = device.configure([dict(gpio=2, count=2, order='GRB')], 500,
                                  ssid='test-network', password='test-password')
        self.assertEqual(result['count'], 2)
        self.assertEqual(device.led_count, 2)
        self.assertNotIn('password', json.dumps(result))
        self.assertEqual(device.pair(), dict(paired=True, mac=MAC))
        self.assertEqual(wesp.load_token(MAC), TOKEN)
        self.assertNotIn(TOKEN, json.dumps(device.document))
        self.assertTrue(all('mac' in r for r in stream.requests))

    def test_wrong_token_rejected_and_reconnect_revalidates_count(self):
        wesp.save_token(MAC, 'cd' * 32)
        device, _ = self.device()
        with self.assertRaisesRegex(ValueError, 'rejected'):
            device.query()
        wesp.save_token(MAC, TOKEN)
        device, server = self.device()
        device.query()
        first_session = device.session
        device.close()
        replacement = Receiver(lambda req, reply: reply.update(count=3))
        self.addCleanup(replacement.close)
        device.tcp_port = replacement.port
        with self.assertRaisesRegex(ValueError, 'count changed'):
            device.query()
        self.assertNotEqual(first_session, device.session)
        self.assertEqual(replacement.requests[0]['id'], 1)
        self.assertEqual(replacement.requests[0]['op'], 'hello')

    def test_dns_unavailable_falls_back_but_identity_failure_does_not(self):
        server = Receiver()
        self.addCleanup(server.close)
        real_connect = socket.create_connection
        addresses = []
        def connect(address, timeout):
            addresses.append(address[0])
            if address[0].endswith('.local'):
                raise socket.gaierror('DNS unavailable')
            return real_connect(address, timeout)
        device = wesp.Device(host='wesp-485628.local', fallback_host='127.0.0.1',
                             connection='wifi', expected_mac=MAC, led_count=2)
        device.tcp_port = server.port
        self.addCleanup(device.close)
        with patch.object(socket, 'create_connection', side_effect=connect):
            device.query()
        self.assertEqual(addresses, ['wesp-485628.local', '127.0.0.1'])
        self.assertEqual(device.expected_mac, MAC)
        wrong = Receiver(lambda req, reply: reply.update(mac='111111111111'))
        self.addCleanup(wrong.close)
        device.close()
        device.host = '127.0.0.1'
        device.tcp_port = wrong.port
        addresses.clear()
        with patch.object(socket, 'create_connection', side_effect=connect):
            with self.assertRaisesRegex(ValueError, 'different WESP'):
                device.query()
        self.assertEqual(addresses, ['127.0.0.1'])

    def test_discover_zero_not_enrollable_and_configure_pins(self):
        device = wesp.Device(port='/dev/fake', discover=True)
        hello = dict(ok=True, id=1, mac=MAC, proto=1, firmware='WESP', count=0, on=False, bri=255)
        device.verify_identity(hello)
        self.assertEqual(device.led_count, 0)
        for outputs in [[dict(gpio=0, count=2, order='GRB')], [dict(gpio=2, count=0, order='GRB')]]:
            with self.assertRaises(ValueError):
                device.configure(outputs, 500)


if __name__ == '__main__':
    unittest.main()
