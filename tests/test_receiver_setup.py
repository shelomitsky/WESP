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
    def test_wifi_configuration_keeps_wifi_route_and_scene_after_verified_write(self):
        import control,wesp_transport
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(control,'CONFIG',Path(folder)/'config'), \
             patch.object(control,'RUNTIME',Path(folder)/'runtime'), \
             patch.object(control,'prepare_enrollment',side_effect=AssertionError('old-layout overlay replay before CFG')):
            control.CONFIG.mkdir()
            selected=dict(backend='wesp',connection='wifi',mac='680947485628',count=2,
                          host='wesp-485628.local',fallback_host='192.0.2.2',port='/dev/ttyUSB8')
            control.write_json(control.CONFIG/'settings.json',dict(controller=selected,equalizer=True))
            device=wesp_transport.Device(**dict(port=selected['port'],connection='wifi',
                expected_mac=selected['mac'],led_count=2,host=selected['host'],fallback_host=selected['fallback_host']))
            callback=self.owner_callback(device,control)
            def configure(outputs,ma,**fields):
                device.led_count=3
                return dict(mac=selected['mac'],count=3,connection='wifi',outputs=outputs,max_milliamps=ma)
            with patch.object(device,'configure',side_effect=configure):
                result=callback(dict(action='configure',mac=selected['mac'],
                    outputs=[dict(gpio=4,count=3,order='RGB')],max_milliamps=700))
            self.assertEqual(result['count'],3)
            saved=control.settings()
            self.assertEqual(saved['controller'],dict(selected,count=3))
            self.assertTrue(saved['equalizer'])

    def owner_callback(self,device,control):
        # Exercise the real nested callback without starting the device service.
        source=Path(receiver_setup.__file__).with_name('usb_transport.py').read_text()
        serve=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='serve')
        callback=next(n for n in serve.body if isinstance(n,ast.FunctionDef) and n.name=='receiver_setup')
        wrapper=ast.parse('def factory(device):\n    pass\n').body[0]
        wrapper.body=[callback,ast.Return(value=ast.Name(id='receiver_setup',ctx=ast.Load()))]
        namespace=dict(control=control,device_lock=threading.RLock(),cancel_calibration=lambda:None)
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

    def test_qt_json_request_with_utf8_charset_reads_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            outputs=[dict(gpio=2,count=10,order='GRB'),dict(gpio=4,count=10,order='GRB')]
            bridge=receiver_setup.Bridge(folder,lambda data:dict(mac='680947485628',outputs=outputs))
            try:
                meta=json.loads(bridge.path.read_text())
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                request=urllib.request.Request(meta['url'],
                    data=b'{"action":"probe","port":"/dev/ttyUSB0","mac":""}',
                    # QML XMLHttpRequest adds this charset to application/json.
                    headers={'Content-Type':'application/json;charset=UTF-8',
                             'Authorization':'Bearer '+meta['bearer']})
                with opener.open(request,timeout=3) as response:
                    result=json.load(response)
                self.assertTrue(result['ok'])
                self.assertEqual(result['receiver']['outputs'],outputs)
            finally: bridge.close()

    def test_bridge_rejects_non_json_media_type_before_callback(self):
        with tempfile.TemporaryDirectory() as folder:
            callback=Mock()
            bridge=receiver_setup.Bridge(folder,callback)
            try:
                meta=json.loads(bridge.path.read_text())
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for content_type in ('text/plain;charset=UTF-8','application/jsonp',''):
                    with self.subTest(content_type=content_type):
                        request=urllib.request.Request(meta['url'],data=b'{"action":"probe"}',
                            headers={'Content-Type':content_type,'Authorization':'Bearer '+meta['bearer']})
                        with opener.open(request,timeout=3) as response:
                            self.assertFalse(json.load(response)['ok'])
                callback.assert_not_called()
            finally: bridge.close()


if __name__=='__main__': unittest.main()
