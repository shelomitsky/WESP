import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class OtaUpdateTest(unittest.TestCase):
    def exercise(self,wrong_build=False):
        import control,ota_update
        class Device:
            connection='wifi';expected_mac='680947485628';confirmed=False;booted=False;image=None
            def setup_status(self):
                return dict(mac=self.expected_mac,count=2,outputs=[{'gpio':2,'count':2,'order':'GRB'}],
                    capabilities={'ota':True},version='0.2.0',ota_trial=self.booted and not self.confirmed,
                    build_sha256=('2' if wrong_build else '1')*64)
            def ota_upload(self,image,progress):self.image=image;progress(100);self.booted=True
            def _disconnect(self):pass
            def _run(self,op):
                if op=='ota_confirm':self.confirmed=True
        with tempfile.TemporaryDirectory() as folder,patch.object(control,'RUNTIME',Path(folder)), \
             patch.object(ota_update,'__file__',str(Path(folder)/'ota_update.py')):
            assets=Path(folder)/'receiver-firmware';assets.mkdir();(assets/'firmware.bin').write_bytes(b'checked-image')
            data={'id':'test-job','mac':'680947485628'};ota_update.save(data,'queued')
            manifest={'version':'0.2.0','elf_sha256':'1'*64}
            device=Device();clock=[0]
            def tick():clock[0]+=10;return clock[0]
            with patch('receiver_assets.validated',return_value=manifest), \
                 patch.object(ota_update.time,'sleep'),patch.object(ota_update.time,'monotonic',side_effect=tick):
                if wrong_build:
                    with self.assertRaises(ValueError):ota_update.perform(device,'test-job')
                    self.assertEqual(ota_update.status()['stage'],'failed')
                    self.assertFalse(device.confirmed)
                else:
                    self.assertTrue(ota_update.perform(device,'test-job'))
                    self.assertEqual(ota_update.status()['stage'],'complete')
                    self.assertTrue(device.confirmed)
                    self.assertEqual(device.image,b'checked-image')

    def test_confirm_requires_exact_reconnected_build_and_preserved_outputs(self):self.exercise()
    def test_wrong_build_never_gets_confirmed(self):self.exercise(wrong_build=True)

    def test_changed_mac_is_rejected_before_image_or_network_work(self):
        import control,ota_update
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder,patch.object(control,'RUNTIME',Path(folder)):
            ota_update.save({'id':'job','mac':'680947485628'},'queued')
            with self.assertRaises(ValueError):ota_update.perform(SimpleNamespace(expected_mac='a0b7652d2050'),'job')
            self.assertEqual(ota_update.status()['stage'],'queued')

    def test_worker_refusal_is_immediate_failure_not_a_stuck_queued_job(self):
        import control,ota_update
        with tempfile.TemporaryDirectory() as folder,patch.object(control,'RUNTIME',Path(folder)),patch.object(control,'CONFIG',Path(folder)):
            ota_update.save({'id':'job','mac':'680947485628'},'queued')
            with patch('usb_transport.client',return_value=False):ota_update.worker('job')
            self.assertEqual(ota_update.status()['stage'],'failed')


if __name__=='__main__':unittest.main()
