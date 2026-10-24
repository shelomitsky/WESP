import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
import sys

import firmware


class FirmwareTest(unittest.TestCase):
    def test_previous_failed_read_uses_base_baud_on_next_prepare(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            firmware.save_job(root,dict(stage='failed',error='ROM read failed',backup_baud=460800))
            with patch.object(firmware,'state_root',return_value=root), \
                 patch.object(firmware,'validate_port',return_value=dict(port='/dev/ttyUSB0')), \
                 patch.object(firmware.subprocess,'Popen',return_value=Mock(pid=123)), \
                 patch.object(firmware,'process_stamp',return_value='test'), \
                 patch('receiver_assets.stage',return_value={'version':'0.2.1'}):
                result=firmware.start('prepare-native','/dev/ttyUSB0')
            self.assertEqual(result['backup_start_baud'],115200)

    def test_backup_read_error_restarts_once_at_base_speed_and_checks_chip_digest(self):
        image=b'x'*firmware.FLASH_SIZE
        esp=Mock()
        esp.read_flash.side_effect=[OSError('read block failed'),image]
        esp.flash_md5sum.return_value=hashlib.md5(image).hexdigest()
        result=firmware.read_verified_backup(esp,Mock(),(OSError,))
        self.assertEqual(result,image)
        esp.change_baud.assert_called_once_with(115200)
        esp.flush_input.assert_called_once()
        esp.connect.assert_called_once_with(mode='no_reset',attempts=1,warnings=False)
        esp.flash_set_parameters.assert_called_once_with(firmware.FLASH_SIZE)
        self.assertEqual(esp.read_flash.call_count,2)
        esp.flash_md5sum.assert_called_once_with(0,firmware.FLASH_SIZE)

    def test_corrupt_backup_and_second_read_failure_do_not_succeed(self):
        esp=Mock();esp.read_flash.return_value=b'x'*firmware.FLASH_SIZE
        esp.flash_md5sum.return_value='0'*32
        with self.assertRaises(ValueError):firmware.read_verified_backup(esp,Mock(),(OSError,))
        self.assertEqual(esp.read_flash.call_count,2)
        esp=Mock();esp.read_flash.side_effect=OSError('still failing')
        with self.assertRaises(OSError):firmware.read_verified_backup(esp,Mock(),(OSError,))
        self.assertEqual(esp.read_flash.call_count,2)

    def test_backup_cancellation_is_never_retried(self):
        esp=Mock();esp.read_flash.side_effect=RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):firmware.read_verified_backup(esp,Mock(),(OSError,))
        esp.change_baud.assert_not_called()

    def test_wrong_board_size_security_or_identity_never_reaches_write(self):
        good = dict(chip='ESP32', mac='680947485628', size=4194304, secure=False)
        firmware.validate_board(good)
        for changed in (dict(chip='ESP32-S3'), dict(size=8388608), dict(secure=True),
                        dict(mac=''), dict(mac='a0b7652d2050')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                firmware.validate_board(dict(good, **changed), expected=good)

    def test_backup_must_have_exact_size_and_original_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'flash.bin'
            p.write_bytes(b'1234')
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            firmware.check_file(p, digest, size=4)
            for bad_hash, size in ((digest, 5), ('0'*64, 4)):
                with self.assertRaises(ValueError):
                    firmware.check_file(p, bad_hash, size=size)

    def test_restore_restarts_only_previously_active_services(self):
        with patch.object(firmware, 'systemctl') as run:
            firmware.restore_services(['wled-control-usb.service'])
            run.assert_called_once_with('start', 'wled-control-usb.service')

    def test_port_is_explicit_and_currently_enumerated(self):
        with patch.object(firmware, 'port_identity', return_value={'port':'/dev/ttyUSB1'}):
            for port in ('/dev/ttyS0', '/tmp/serial', '', '/dev/ttyUSB0;echo bad'):
                with self.assertRaises(ValueError):
                    firmware.validate_port(port)

    def test_finish_failure_retains_backup_and_restores_services(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            data=dict(stage='writing', active=['wled-control-usb.service'],
                      backup='/preserved/flash.bin', error='')
            firmware.save_job(root, data)
            with patch.object(firmware, 'restore_services') as restore:
                firmware.finish(root, data, error=RuntimeError('write failed'))
            restore.assert_called_once_with(['wled-control-usb.service'])
            result=firmware.read_job(root)
            self.assertEqual(result['backup'], '/preserved/flash.bin')
            self.assertEqual(result['stage'], 'failed')
            self.assertIn('write failed', result['error'])

    def test_same_exclusive_connection_validates_and_writes(self):
        board=dict(chip='ESP32', mac='680947485628', size=4194304, secure=False)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            data=dict(stage='starting', flavor='wesp', port='/dev/ttyUSB0', identity={'serial':'A'},
                      board=board, backup=str(root/'original.bin'), backup_sha256='a'*64, folder=folder)
            esp=Mock()
            tool=Mock()
            tool.detect_chip.return_value=esp
            with patch.dict(sys.modules, esptool=tool), \
                 patch.object(firmware, 'validate_port', return_value={'serial':'A'}), \
                 patch.object(firmware, 'pause_services'), patch.object(firmware, 'require_free_port'), \
                 patch.object(firmware, 'board_info', return_value=board), \
                 patch.object(firmware, 'check_file') as verified, \
                 patch('receiver_assets.merged', return_value=root/'combined.bin'):
                firmware.operate(root, data, 'install')
            tool.detect_chip.assert_called_once_with('/dev/ttyUSB0', baud=115200)
            self.assertIs(tool.main.call_args.kwargs['esp'], esp)
            self.assertIn('--no-stub', tool.main.call_args.args[0])
            verified.assert_called_once_with(root/'original.bin', 'a'*64, size=4194304)
            esp.hard_reset.assert_called_once()
            esp._port.close.assert_called_once()
            self.assertEqual(data['stage'], 'flashed')

    def test_swapped_board_closes_port_without_write(self):
        board=dict(chip='ESP32', mac='680947485628', size=4194304, secure=False)
        with tempfile.TemporaryDirectory() as folder:
            data=dict(flavor='wesp',port='/dev/ttyUSB0', identity={}, board=dict(board,mac='a0b7652d2050'))
            tool=Mock()
            esp=tool.detect_chip.return_value
            with patch.dict(sys.modules, esptool=tool), \
                 patch.object(firmware, 'validate_port', return_value={}), \
                 patch.object(firmware, 'pause_services'), patch.object(firmware, 'require_free_port'), \
                 patch.object(firmware, 'board_info', return_value=board):
                with self.assertRaises(ValueError):
                    firmware.operate(Path(folder), data, 'install')
            tool.main.assert_not_called()
            esp._port.close.assert_called_once()

    def test_dead_worker_recovers_original_services(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            data=dict(stage='backup', pid=42, stamp='old', active=['wled-control-usb.service'])
            firmware.save_job(root,data)
            with patch.object(firmware, 'state_root', return_value=root), \
                 patch.object(firmware, 'process_stamp', return_value=None), \
                 patch.object(firmware, 'restore_services') as restore:
                result=firmware.status()
            self.assertEqual(result['stage'],'failed')
            restore.assert_called_once_with(['wled-control-usb.service'])

    def test_foreign_uart_owner_is_not_killed(self):
        with patch.object(firmware.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            with self.assertRaises(ValueError):
                firmware.require_free_port('/dev/ttyUSB0')
            self.assertEqual(run.call_args.args[0],['fuser','/dev/ttyUSB0'])

    def test_failed_service_recovery_is_retried_before_new_job(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            firmware.save_job(root,dict(stage='failed',active=['wled-control-usb.service'],
                                        error='retry',recovery_pending=True))
            with patch.object(firmware,'state_root',return_value=root), \
                 patch.object(firmware,'restore_services',side_effect=[RuntimeError('busy'),None]) as restore:
                self.assertTrue(firmware.status()['recovery_pending'])
                result=firmware.status()
            self.assertFalse(result['recovery_pending'])
            self.assertEqual(restore.call_count,2)
            self.assertEqual(result['active'],[])

    def test_mac_pinned_discovery_cannot_learn_led_count_from_other_board(self):
        from usb_transport import Device
        device=Device('/dev/ttyUSB0',expected_mac='680947485628',discover=True)
        with self.assertRaises(ValueError):
            device.verify_identity(dict(info=dict(mac='a0b7652d2050',leds=dict(count=20))))
        self.assertIsNone(device.led_count)
        device.verify_identity(dict(info=dict(mac='680947485628',leds=dict(count=30))))
        self.assertEqual(device.led_count,30)



if __name__ == '__main__':
    unittest.main()
