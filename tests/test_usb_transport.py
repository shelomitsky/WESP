TEST_MAC = '021122334455'
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import time
import json
import threading
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class USBTransportTest(unittest.TestCase):
    def negotiating_device(self, controller_baud=115200, allow_fast=True, mac=None):
        import usb_transport as usb
        class UART:
            is_open = True
            baudrate = 115200
            def __init__(self):
                self.controller_baud = controller_baud
                self.packets = []
                self.buffer = b''
            @property
            def in_waiting(self): return len(self.buffer)
            def flush(self): pass
            def reset_input_buffer(self): self.buffer = b''
            def close(self): self.is_open = False
            def read(self, count):
                result, self.buffer = self.buffer[:count], self.buffer[count:]
                return result
            def write(self, packet):
                self.packets.append((self.baudrate,packet))
                if self.baudrate != self.controller_baud:
                    return len(packet)
                if packet == b'\xb5' and allow_fast:
                    self.controller_baud = 921600
                elif packet == b'\xb0':
                    self.controller_baud = 115200
                elif packet.startswith(b'{'):
                    self.buffer = json.dumps(dict(state=dict(on=True,bri=128),
                        info=dict(mac=mac or TEST_MAC,leds=dict(count=20)))).encode()
                return len(packet)
        device = usb.Device('/dev/ttyUSB8', expected_mac=TEST_MAC, led_count=20)
        device.serial = UART()
        return device

    def test_switch_from_default_to_fast_and_confirm_both_ends(self):
        device = self.negotiating_device()
        with patch('usb_transport.time.sleep'):
            device.negotiate()
        self.assertEqual(device.baud, 921600)
        self.assertEqual(device.serial.baudrate, 921600)
        self.assertEqual(device.serial.controller_baud, 921600)
        packets = device.serial.packets
        switch = next(i for i,(_,p) in enumerate(packets) if p == b'\xb5')
        self.assertTrue(packets[switch-1][1].startswith(b'{'))
        self.assertTrue(packets[-1][1].startswith(b'{'))

    def test_restart_finds_already_fast_device(self):
        device = self.negotiating_device(controller_baud=921600)
        ticks = iter(i*.25 for i in range(1000))
        with patch('usb_transport.time.sleep'), patch('usb_transport.time.monotonic',side_effect=lambda:next(ticks)):
            device.negotiate()
        self.assertEqual(device.baud, 921600)
        self.assertFalse(any(packet == b'\xb5' for _,packet in device.serial.packets))

    def test_failed_fast_switch_keeps_verified_baseline(self):
        device = self.negotiating_device(allow_fast=False)
        ticks = iter(i*.25 for i in range(1000))
        with patch('usb_transport.time.sleep'), patch('usb_transport.time.monotonic',side_effect=lambda:next(ticks)):
            device.negotiate()
        self.assertEqual(device.baud, 115200)
        self.assertEqual(device.serial.controller_baud, 115200)
        self.assertEqual(device.serial.baudrate, 115200)

    def test_wrong_mac_never_gets_speed_command(self):
        device = self.negotiating_device(mac='001122334455')
        with patch('usb_transport.time.sleep'):
            with self.assertRaises(ValueError):
                device.negotiate()
        self.assertFalse(any(packet in (b'\xb0',b'\xb5') for _,packet in device.serial.packets))

    def test_restore_baseline_from_fast_rate(self):
        device = self.negotiating_device(controller_baud=921600)
        device.preferred_baud = 115200
        ticks = iter(i*.25 for i in range(1000))
        with patch('usb_transport.time.sleep'), patch('usb_transport.time.monotonic',side_effect=lambda:next(ticks)):
            device.negotiate()
        self.assertEqual(device.baud, 115200)
        self.assertEqual(device.serial.controller_baud, 115200)

    def test_runtime_baseline_command_reports_confirmed_rate(self):
        device = self.negotiating_device()
        ticks = iter(i*.05 for i in range(1000))
        with patch('usb_transport.time.sleep'), patch('usb_transport.time.monotonic',side_effect=lambda:next(ticks)):
            device.negotiate()
            report = device.set_baud(115200)
        self.assertEqual(report['baud'],115200)
        self.assertFalse(report['fallback'])
        self.assertEqual(report['mac'],'021122334455')

    def test_pending_handshake_is_not_reported_as_verified_link(self):
        device = self.device()
        device.needs_handshake = True
        with self.assertRaises(ValueError):
            device.link_status()

    def test_cached_state_is_not_published_mid_handshake(self):
        device = self.device()
        device.needs_handshake = True
        with self.assertRaises(ValueError):
            device.state()

    def test_esp_reset_is_rediscovered_without_reopening_port(self):
        device = self.negotiating_device()
        with patch('usb_transport.time.sleep'):
            device.negotiate()
        uart = device.serial
        uart.controller_baud = 115200  # ESP rebooted; PC descriptor stays open.
        device.needs_handshake = True
        device.updated = 0
        ticks = iter(i*.25 for i in range(1000))
        with patch('usb_transport.time.sleep'), patch('usb_transport.time.monotonic',side_effect=lambda:next(ticks)):
            device.query()
            self.assertFalse(device.link_status()['fallback'])
        self.assertIs(device.serial, uart)
        self.assertTrue(uart.is_open)
        self.assertEqual(device.baud, 921600)

    def test_host_rejects_fast_rate_before_wled_speed_is_changed(self):
        device = self.negotiating_device()
        uart = device.serial
        class UnsupportedUART(type(uart)):
            @property
            def baudrate(self): return getattr(self, '_host_rate',115200)
            @baudrate.setter
            def baudrate(self, rate):
                if rate == 921600:
                    raise ValueError('unsupported host baud')
                self._host_rate = rate
        device.serial = UnsupportedUART()
        with patch('usb_transport.time.sleep'):
            device.negotiate()
        self.assertEqual(device.baud,115200)
        self.assertFalse(any(packet == b'\xb5' for _,packet in device.serial.packets))

    def test_waiting_pixel_rechecks_off_state_after_refresh(self):
        device = self.device()
        attempted = threading.Event()
        checked = threading.Event()
        results = []
        original = device.state
        def state(payload=None):
            result = original(payload)
            checked.set()
            return result
        def send():
            attempted.set()
            results.append(device.pixels([[255,0,0]]*20))
        device.state = state
        writes = []
        device.serial = SimpleNamespace(is_open=True, baudrate=115200, write=lambda packet:writes.append(packet) or len(packet))
        with device.write_lock:
            thread = threading.Thread(target=send)
            thread.start()
            self.assertTrue(attempted.wait(1))
            # In the broken code validation runs before waiting for write_lock.
            checked.wait(.04)
            device.document['state']['on'] = False
        thread.join(timeout=1)
        self.assertEqual(results, [False])
        self.assertEqual(writes, [])

    def test_json_reply_blocks_pixel_writes_until_transaction_finishes(self):
        device = self.device()
        document = json.dumps(device.document).encode()
        sent = threading.Event()
        outcome = []
        threads = []
        def write(packet):
            if packet.startswith(b'Ada'):
                sent.set()
            return len(packet)
        def read(size):
            thread = threading.Thread(target=lambda:device.pixels([[0,0,0]]*20))
            threads.append(thread)
            thread.start()
            outcome.append(not sent.wait(.04))
            return document
        device.serial = SimpleNamespace(is_open=True, baudrate=115200, in_waiting=len(document),
            reset_input_buffer=lambda:None, flush=lambda:None, write=write, read=read)
        device.query()
        for thread in threads:
            thread.join(timeout=1)
        self.assertEqual(outcome, [True], 'Pixels must not enter UART during JSON reply')
        self.assertTrue(sent.is_set())

    def test_query_timeout_does_not_reset_usb_bridge(self):
        device = self.device()
        closed = []
        device.serial = SimpleNamespace(is_open=True, baudrate=115200, in_waiting=0,
            reset_input_buffer=lambda:None, flush=lambda:None,
            write=lambda b:len(b), read=lambda n:b'', close=lambda:closed.append(True))
        ticks = iter(i*.5 for i in range(100))
        with patch('usb_transport.time.monotonic', side_effect=lambda:next(ticks)):
            with self.assertRaises(TimeoutError):
                device.query()
        self.assertEqual(closed, [])
        self.assertEqual(device.updated, 0)

    def test_uart_query_pixel_stream_and_off_roundtrip(self):
        import usb_transport as usb
        class UART:
            is_open = True
            baudrate = 115200
            def __init__(self):
                self.state = dict(on=True, bri=128, lor=0)
                self.buffer = b''
                self.packets = []
            @property
            def in_waiting(self): return len(self.buffer)
            def reset_input_buffer(self): self.buffer = b''
            def flush(self): pass
            def write(self, packet):
                self.packets.append(packet)
                if packet.startswith(b'{'):
                    self.state.update({k:v for k,v in json.loads(packet).items() if k != 'v'})
                    self.buffer = json.dumps(dict(state=self.state,
                        info=dict(mac=TEST_MAC, leds=dict(count=20)))).encode()+b'\n'
                return len(packet)
            def read(self, size):
                data, self.buffer = self.buffer[:size], self.buffer[size:]
                return data
            def close(self): self.is_open = False
        device = usb.Device('/dev/ttyUSB8', expected_mac=TEST_MAC, led_count=20)
        uart = UART()
        device.serial = uart
        self.assertTrue(device.query()['on'])
        self.assertTrue(device.pixels([[12,34,56]]*20))
        self.assertEqual(uart.packets[-1], usb.adalight([[12,34,56]]*20))
        self.assertFalse(device.state(dict(live=False,on=False))['on'])
        self.assertFalse(device.pixels([[255,0,0]]*20))
        self.assertEqual(json.loads(uart.packets[-1])['live'], False)
        self.assertEqual(device.state()['bri'], 128)
        device.close()
        self.assertFalse(uart.is_open)

    def device(self, mac='021122334455', on=True):
        import usb_transport as usb
        device = usb.Device('/dev/ttyUSB8', expected_mac=TEST_MAC, led_count=20)
        device.document = dict(info=dict(mac=mac, leds=dict(count=20)),
                               state=dict(on=on, bri=128, lor=0))
        device.updated = time.monotonic()
        return device

    def test_wrong_controller_refuses_pixel_write(self):
        device = self.device(mac='001122334455')
        with patch.object(device, 'write') as write:
            with self.assertRaises(ValueError):
                device.pixels([[0,0,0]]*20)
            write.assert_not_called()

    def test_off_strip_refuses_pixels(self):
        device = self.device(on=False)
        with patch.object(device, 'write') as write:
            self.assertFalse(device.pixels([[255,0,0]]*20))
            write.assert_not_called()

    def test_missing_or_stale_state_refuses_pixels(self):
        device = self.device()
        device.updated = 0
        with patch.object(device, 'write') as write:
            with self.assertRaises(ValueError):
                device.pixels([[0,0,0]]*20)
            write.assert_not_called()

    def test_adalight_twenty_pixels(self):
        import usb_transport as usb
        pixels = [[i, 255-i, 0] for i in range(20)]
        packet = usb.adalight(pixels)
        self.assertEqual(packet[:6], b'Ada\x00\x13\x46')
        self.assertEqual(len(packet), 66)
        self.assertEqual(packet[6:9], b'\x00\xff\x00')
        self.assertEqual(packet[-3:], bytes([19,236,0]))
        self.assertLess(len(packet)*60, 115200/10)

    def test_invalid_frame_rejected(self):
        import usb_transport as usb
        for pixels in ([], [[1,2]], [[-1,0,0]], [[0,0,256]], [[1.1,0,0]]):
            with self.assertRaises(ValueError):
                usb.adalight(pixels)
