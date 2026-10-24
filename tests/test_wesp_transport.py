import json
import socket
import threading
import unittest
from unittest.mock import patch,Mock
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
    def effects_peer(self):
        stored={}
        def respond(request,reply):
            reply['capabilities']={'native_effects':True,'wifi_configure':True,'ota':True,'max_presets':8}
            if request['op']=='effects_configure':stored['effects']=request['effects']
            if request['op']=='hello':reply.update(stored)
        return self.device(respond)

    def fx_config(self):
        import effects_config,layout
        return effects_config.from_preferences({'controller':{'count':2},'sections':layout.legacy(2)})

    def test_realtime_audio_uses_udp_without_waiting_for_control_lock(self):
        import realtime_protocol as rt,time
        udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0));udp.settimeout(.5);self.addCleanup(udp.close)
        stored={};key=b'x'*32;sid=b'12345678'
        def respond(request,reply):
            reply['capabilities']={'native_effects':True,'realtime_audio':True}
            if request['op']=='effects_configure':stored['effects']=request['effects']
            if request['op']=='hello':reply.update(stored)
            if request['op']=='audio_open':reply['audio_stream']=dict(id=sid.hex(),key=key.hex(),port=udp.getsockname()[1],clock_ms=1000)
            if request['op']=='audio_clock':reply['audio_clock_ms']=1000
        device,peer=self.device(respond);device.udp_port=udp.getsockname()[1];device.query({'on':True})
        self.assertTrue(device.prepare_realtime(self.fx_config()))
        count=len(peer.requests);locked=threading.Event();release=threading.Event()
        def block_control():
            with device.query_lock:locked.set();release.wait(2)
        thread=threading.Thread(target=block_control);thread.start();self.addCleanup(release.set);locked.wait(1)
        started=time.monotonic();self.assertTrue(device.send_realtime(MAC,2,rt.now_ns(),12000,4000));self.assertLess(time.monotonic()-started,.1)
        packet,_=udp.recvfrom(100);self.assertEqual(len(packet),40);self.assertEqual(rt.unpack_audio(packet,key,sid)[2:],(12000,4000))
        self.assertEqual(len(peer.requests),count,'audio must not perform a TCP operation')
        self.assertFalse(device.send_realtime('a0b7652d2050',2,rt.now_ns(),22000,4000))
        self.assertFalse(device.send_realtime(MAC,3,rt.now_ns(),22000,4000))
        self.assertFalse(device.send_realtime(MAC,2,rt.now_ns()-200_000_000,22000,4000))
        release.set();thread.join(1)
        palette=[[10,20,30]]*10
        device.prepare_realtime(self.fx_config(),palette)
        self.assertEqual(peer.requests[-1]['op'],'palette')
        before_palette=len(peer.requests);device.prepare_realtime(self.fx_config(),palette)
        self.assertEqual(len(peer.requests),before_palette,'unchanged transient palette must not repeat')
        device.query({'on':False})
        self.assertFalse(device.send_realtime(MAC,2,rt.now_ns(),22000,4000))
        self.assertNotIn(key.hex(),json.dumps(device.document))

    def test_native_audio_sends_raw_features_and_config_once_without_rgb_frames(self):
        device,peer=self.effects_peer();device.query({'on':True})
        peer.requests.clear()
        config=self.fx_config()
        self.assertTrue(device.features(.2,.3,config))
        self.assertTrue(device.features(.4,.1,config))
        self.assertEqual([r['op'] for r in peer.requests],['effects_configure','hello','audio','audio'])
        self.assertEqual(peer.requests[-1]['rms'],.4)
        self.assertEqual(peer.requests[-1]['bass'],.1)
        self.assertNotIn('pixels',json.dumps(peer.requests))
        self.assertEqual(device.setup_status()['effects'],config)

    def test_wallpaper_heartbeat_is_seven_eighths_and_off_cannot_resume_it(self):
        device,peer=self.effects_peer();device.query({'on':True})
        config=self.fx_config()
        with patch.object(wesp.time,'monotonic',return_value=100):
            self.assertTrue(device.effect('solid',[1,2,3],config))
        peer.requests.clear()
        with patch.object(wesp.time,'monotonic',return_value=106.9):self.assertFalse(device.maintain())
        with patch.object(wesp.time,'monotonic',return_value=107):self.assertTrue(device.maintain())
        self.assertEqual([r['op'] for r in peer.requests],['heartbeat'])
        device.query({'on':False});peer.requests.clear()
        with patch.object(wesp.time,'monotonic',return_value=120):self.assertFalse(device.maintain())
        self.assertEqual(peer.requests,[])

    def test_native_event_is_one_command_and_duplicate_does_not_restart_it(self):
        device,peer=self.effects_peer();device.query({'on':True});config=self.fx_config()
        device.features(.2,.2,config);peer.requests.clear()
        self.assertTrue(device.event('notification','123456789abcdef0',0,config))
        self.assertTrue(device.event('notification','123456789abcdef0',0,config))
        device.features(.3,.1,config)
        self.assertEqual([r['op'] for r in peer.requests],['event','audio'])

    def test_ota_upload_is_off_first_sequential_and_hashes_exact_image(self):
        import base64,hashlib
        device,peer=self.effects_peer();device.query({'on':True});peer.requests.clear()
        image=b'\xe9'+b'firmware'*400;progress=[]
        device.ota_upload(image,progress.append)
        ops=[r['op'] for r in peer.requests]
        self.assertEqual(ops[:2],['state','ota_begin'])
        self.assertFalse(peer.requests[0]['on'])
        self.assertEqual(peer.requests[1]['sha256'],hashlib.sha256(image).hexdigest())
        offset=0;actual=b''
        for r in peer.requests[2:-1]:
            self.assertEqual(r['op'],'ota_chunk');self.assertEqual(r['offset'],offset)
            chunk=base64.b64decode(r['data']);self.assertLessEqual(len(chunk),1024)
            offset+=len(chunk);actual+=chunk
        self.assertEqual(actual,image);self.assertEqual(ops[-1],'ota_finish')
        self.assertEqual(progress[-1],100)

    def test_preview_reads_esp_pixels_without_sending_frames_or_renewing_lease(self):
        import base64
        def respond(request,reply):
            reply['capabilities']={'native_effects':True,'preview':True}
            if request['op']=='preview':reply['pixels']=base64.b64encode(bytes([1,2,3,4,5,6])).decode()
        device,peer=self.device(respond)
        result=device.preview()
        self.assertEqual(result['pixels'],[[1,2,3],[4,5,6]])
        self.assertEqual(result['brightness'],255)
        self.assertEqual(result['source'],'esp')
        self.assertEqual([r['op'] for r in peer.requests],['hello','preview'])

    def test_cfg_change_does_not_replay_old_audio_or_renew_its_timestamp(self):
        import effects_config,copy
        device,peer=self.effects_peer();device.query({'on':True});config=self.fx_config()
        with patch.object(wesp.time,'monotonic',return_value=100):device.features(.2,.2,config)
        peer.requests.clear();changed=copy.deepcopy(config)
        changed['presets'][0]['sensitivity']=110;changed['revision']=effects_config.revision(changed)
        with patch.object(wesp.time,'monotonic',return_value=100.1):device.effects_configure(changed)
        self.assertEqual([r['op'] for r in peer.requests],['effects_configure','hello'])
        self.assertEqual(device.last_scene['updated'],100)

    def test_heartbeat_schedule_uses_send_time_even_when_ack_is_delayed(self):
        device=wesp.Device(host='127.0.0.1',connection='wifi',expected_mac=MAC,led_count=2)
        device.document={'on':True};device.last_scene={'mode':'solid','config':{'wallpaper_timeout_ms':2000,'revision':'1'*16}}
        device.last_heartbeat=0;clock=[1.75]
        def exchange(*args):clock[0]+=.3
        with patch.object(wesp.time,'monotonic',side_effect=lambda:clock[0]),patch.object(device,'_run',side_effect=exchange):
            self.assertTrue(device.maintain())
            self.assertEqual(device.last_heartbeat,1.75)
            clock[0]=3.5
            self.assertTrue(device.maintain())


    def test_usb_reads_available_reply_without_waiting_for_full_buffer(self):
        clock=[0.0]
        class Serial:
            data=b''
            @property
            def in_waiting(self):return len(self.data)
            def write(self,packet):
                request=json.loads(packet)
                self.data=json.dumps(dict(ok=True,id=request['id'],mac=MAC,proto=1,count=2,on=False,bri=255)).encode()+b'\n'
                return len(packet)
            def read(self,size):
                if size>len(self.data):clock[0]+=.05  # Real pyserial waits for its timeout.
                result,self.data=self.data[:size],self.data[size:]
                return result
            def close(self):pass
        device=wesp.Device(port='/dev/fake',expected_mac=MAC,led_count=2)
        device.serial=Serial();device.session='a'*16
        with patch.object(wesp.time,'monotonic',side_effect=lambda:clock[0]):device.query()
        self.assertLess(device.last_exchange['elapsed_ms'],10)

    def test_usb_hello_waits_for_boot_and_discards_boot_bytes(self):
        events=[]
        stream=Mock()
        stream.open.side_effect=lambda:events.append('open')
        stream.reset_input_buffer.side_effect=lambda:events.append('discard boot bytes')
        device=wesp.Device(port='/dev/fake',discover=True)
        def hello(op):
            self.assertEqual(events,['open','settle','discard boot bytes'])
            return dict(firmware='WESP')
        with patch('serial.Serial',return_value=stream), \
             patch.object(wesp.time,'sleep',side_effect=lambda delay:events.append('settle')), \
             patch.object(device,'_exchange',side_effect=hello):
            device.connect()
        device.close()

    def test_minimal_state_ack_keeps_metadata_and_setup_gets_fresh_wifi(self):
        joined=[False]
        def reply(req,document):
            if req['op']=='hello':
                document['wifi']=dict(configured=True,connected=joined[0],ip='192.0.2.2' if joined[0] else '')
            else:
                for key in ('firmware','outputs','color','watchdog_ms'):
                    document.pop(key,None)
        device,server=self.device(reply)
        device.query()
        self.assertEqual(device.document.get('firmware'),'WESP')
        joined[0]=True
        self.assertTrue(device.setup_status()['wifi']['connected'])
        self.assertEqual(server.requests[-1]['op'],'hello')

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
        with self.assertRaisesRegex(ValueError, 'Pair'):
            device.configure([dict(gpio=2, count=2, order='GRB')], 500)

    def configured_peer(self, mismatch=False, supported=True):
        stored=dict(outputs=[dict(gpio=2,count=2,order='GRB')],max_milliamps=500)
        def respond(request,reply):
            if request['op']=='configure':
                stored.update(outputs=request['outputs'],max_milliamps=request['max_milliamps'])
            reply.update(count=sum(o['count'] for o in stored['outputs']))
            if request['op'] in ('hello','configure'):
                reply.update(stored)
                reply['capabilities']={'wifi_configure':supported,'token':TOKEN}
                if mismatch and request['op']=='hello' and any(r['op']=='configure' for r in peer.requests):
                    reply['max_milliamps']=500
        device,peer=self.device(respond)
        return device,peer

    def test_wifi_configure_reads_back_same_board_and_new_count_without_pairing(self):
        device,peer=self.configured_peer()
        result=device.configure([dict(gpio=4,count=3,order='RGB')],700)
        self.assertEqual(result['outputs'],[dict(gpio=4,count=3,order='RGB')])
        self.assertEqual(result['max_milliamps'],700)
        self.assertEqual(result['count'],3)
        self.assertEqual(result['connection'],'wifi')
        self.assertEqual([r['op'] for r in peer.requests],['hello','hello','configure','hello'])
        self.assertTrue(all(r['mac']==MAC and r['token']==TOKEN for r in peer.requests))
        self.assertNotIn(TOKEN,json.dumps(result))
        self.assertEqual(device.setup_status()['capabilities'],{'wifi_configure':True})

    def test_wifi_configure_old_firmware_and_network_change_fail_before_write(self):
        device,peer=self.configured_peer(supported=False)
        with self.assertRaisesRegex(ValueError,'firmware'):
            device.configure([dict(gpio=4,count=3,order='RGB')],700)
        self.assertFalse(any(r['op']=='configure' for r in peer.requests))
        device,peer=self.configured_peer()
        with self.assertRaisesRegex(ValueError,'USB'):
            device.configure([dict(gpio=4,count=3,order='RGB')],700,ssid='network',password='password')
        self.assertEqual(peer.requests,[])

    def test_configure_ack_without_matching_readback_is_not_success(self):
        device,peer=self.configured_peer(mismatch=True)
        with self.assertRaisesRegex(ValueError,'confirm'):
            device.configure([dict(gpio=4,count=3,order='RGB')],700)
        self.assertEqual(device.led_count,3)
        self.assertIsNone(device.last_frame)

    def test_explicit_settings_read_recovers_count_without_weakening_frame_guard(self):
        device,peer=self.device(lambda req,reply:reply.update(count=3))
        result=device.setup_status(refresh_count=True)
        self.assertEqual(result['count'],3)
        self.assertEqual(device.led_count,3)
        with self.assertRaises(ValueError):device.pixels([[1,2,3]]*2)
        peer.change=lambda req,reply:reply.update(count=4)
        with self.assertRaisesRegex(ValueError,'count changed'):device.query()

    def test_setup_status_sanitizes_wifi(self):
        device, _ = self.device(lambda req, reply: reply.update(wifi=dict(configured=True, connected=True, ip='192.0.2.2', host='wesp-485628.local', password='secret', token=TOKEN)))
        status = device.setup_status()
        self.assertEqual(status['wifi']['ip'], '192.0.2.2')
        self.assertEqual(status['wifi']['host'], 'wesp-485628.local')
        self.assertNotIn('password', json.dumps(status))
        self.assertNotIn(TOKEN, json.dumps(status))

    def test_setup_status_reports_host_transport_instead_of_peer_claim(self):
        device, _ = self.device(lambda req, reply: reply.update(connection='usb'))
        self.assertEqual(device.setup_status().get('connection'),'wifi')

    def test_fresh_settings_read_does_not_keep_a_removed_firmware_capability(self):
        device,peer=self.configured_peer()
        self.assertTrue(device.setup_status()['capabilities']['wifi_configure'])
        peer.change=lambda request,reply:None
        self.assertFalse(device.setup_status().get('capabilities',{}).get('wifi_configure',False))

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
                self.outputs=[]
                self.max_milliamps=500
            def write(self, packet):
                request = json.loads(packet)
                self.requests.append(request)
                if request['op'] == 'configure':
                    self.count = sum(o['count'] for o in request['outputs'])
                    self.outputs=request['outputs'];self.max_milliamps=request['max_milliamps']
                reply = dict(ok=True, id=request['id'], proto=1, mac=MAC,
                             firmware='WESP', count=self.count, on=False, bri=255)
                if request['op'] in ('hello','configure'):
                    reply.update(outputs=self.outputs,max_milliamps=self.max_milliamps)
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
        self.assertEqual(result['connection'], 'usb')
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
