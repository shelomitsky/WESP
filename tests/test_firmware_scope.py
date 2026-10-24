from pathlib import Path
from unittest.mock import Mock,patch
import tempfile,unittest,sys
import firmware,control

class NativeOnlyInstallerTest(unittest.TestCase):
    def test_removed_wled_commands_reject_before_start_or_device_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for command in ('firmware-prepare','firmware-connect'):
                firmware.save_job(root,dict(stage='flashed',port='/dev/ttyUSB0',token='test',board={'mac':'680947485628'}))
                with self.subTest(command=command),patch.object(firmware,'state_root',return_value=root),patch.object(firmware,'start',side_effect=AssertionError('removed installer started')),patch.object(control,'execute',side_effect=AssertionError('device accessed')):
                    with self.assertRaises(ValueError):control.dispatch([command,'test'])

    def test_old_prepare_action_and_non_native_saved_jobs_cannot_flash(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            old=dict(stage='prepared',port='/dev/ttyUSB0',identity={},folder=folder,token='test',active=[])
            with patch.object(firmware,'state_root',return_value=root),patch.object(firmware,'validate_port',side_effect=AssertionError('USB accessed')),patch.object(firmware.subprocess,'Popen',side_effect=AssertionError('worker started')),patch.object(firmware,'tool_python',side_effect=AssertionError('tool started')):
                firmware.save_job(root,old)
                with self.assertRaises(ValueError):firmware.start('prepare','/dev/ttyUSB0')
                firmware.save_job(root,old)
                with self.assertRaises(ValueError):firmware.start('install','test')
                with patch.dict(sys.modules,esptool=Mock()):
                    with self.assertRaises(ValueError):firmware.operate(root,old,'install')
                firmware.save_job(root,old)
                with self.assertRaises(ValueError):firmware.launch('install')
            self.assertEqual(firmware.read_job(root)['stage'],'prepared')

    def test_non_native_install_rejects_before_recovery_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            old=dict(stage='prepared',token='test',active=['wled-control-usb.service'],recovery_pending=True)
            firmware.save_job(root,old)
            with patch.object(firmware,'state_root',return_value=root),patch.object(firmware,'systemctl') as service:
                with self.assertRaises(ValueError):firmware.start('install','test')
            service.assert_not_called()
            self.assertEqual(firmware.read_job(root),old)

    def test_native_prepare_uses_verified_bundled_assets_without_download(self):
        import receiver_assets
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(firmware,'state_root',return_value=root),patch.object(firmware,'validate_port',return_value={'serial':'A'}),patch.object(receiver_assets,'stage',return_value={'version':'0.2.1'}) as stage,patch.object(firmware.subprocess,'Popen',return_value=Mock(pid=123)),patch.object(firmware,'process_stamp',return_value='test'):
                result=firmware.start('prepare-native','/dev/ttyUSB0')
            self.assertEqual((result['flavor'],result['version']),('wesp','0.2.1'));stage.assert_called_once()

if __name__=='__main__':unittest.main()
