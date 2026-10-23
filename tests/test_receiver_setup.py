import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.request
import ast
import contextlib
import threading
from unittest.mock import Mock,patch

import receiver_setup


class SetupBridgeTest(unittest.TestCase):
    def owner_callback(self,device,control):
        # Exercise the real nested callback without starting the device service.
        source=Path(receiver_setup.__file__).with_name('usb_transport.py').read_text()
        serve=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='serve')
        callback=next(n for n in serve.body if isinstance(n,ast.FunctionDef) and n.name=='receiver_setup')
        wrapper=ast.parse('def factory(device):\n    pass\n').body[0]
        wrapper.body=[callback,ast.Return(value=ast.Name(id='receiver_setup',ctx=ast.Load()))]
        namespace=dict(control=control,device_lock=threading.RLock())
        module=ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[]))
        exec(compile(module,'<owner-setup-test>','exec'),namespace)
        return namespace['factory'](device)

    def test_wrong_mac_and_readonly_status_never_restore_previous_effect(self):
        import wesp_transport
        device=wesp_transport.Device('/dev/ttyUSB0',expected_mac='680947485628',led_count=20)
        control=Mock();control.locked.side_effect=lambda:contextlib.nullcontext()
        callback=self.owner_callback(device,control)
        with self.assertRaises(ValueError): callback(dict(action='configure',mac='a0b7652d2050'))
        with patch.object(device,'setup_status',return_value=dict(mac=device.expected_mac)):
            self.assertEqual(callback(dict(action='status',mac=device.expected_mac))['mac'],device.expected_mac)
        with self.assertRaises(ValueError): callback(dict(action='unknown',mac=device.expected_mac))
        control.prepare_enrollment.assert_not_called()

    def test_private_bridge_requires_bearer_and_does_not_echo_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            observed=[]
            def callback(data):
                observed.append(data)
                return dict(mac='680947485628',count=20)
            bridge=receiver_setup.Bridge(Path(folder),callback)
            try:
                meta=json.loads((Path(folder)/'receiver-setup.json').read_text())
                self.assertEqual((Path(folder)/'receiver-setup.json').stat().st_mode&0o777,0o600)
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def request(token):
                    return urllib.request.Request(meta['url'],data=b'{"password":"private-test-value"}',
                        headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
                with self.assertRaises(urllib.error.HTTPError): opener.open(request('wrong'),timeout=3)
                self.assertEqual(observed,[])
                with opener.open(request(meta['bearer']),timeout=3) as response:
                    result=response.read()
                self.assertNotIn(b'private-test-value',result)
                self.assertEqual(len(observed),1)
            finally: bridge.close()
            self.assertFalse((Path(folder)/'receiver-setup.json').exists())


if __name__=='__main__': unittest.main()
