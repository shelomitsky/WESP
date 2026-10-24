#!/usr/bin/env python3
"""Actual standalone Qt window and controls, isolated from devices and user state."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QMetaObject, QObject, Q_ARG
from PySide6.QtGui import QGuiApplication


def find_item(window,name):
    # Repeater delegates are in the visual tree, not QObject ownership tree.
    pending=[window.contentItem()]
    while pending:
        item=pending.pop()
        if item.objectName()==name:return item
        pending.extend(item.childItems())
    return None


class DesktopWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_local_frames_continue_while_control_lane_is_busy_and_skip_esp_reads(self):
        import desktop
        class Model:
            demo=None
            def local_frame(self,data):return dict(source='music-local',mac='680947485628',pixels=[[8,4,2]],sequence=1)
            def close(self):pass
        bridge=desktop.AppBridge(Model());self.addCleanup(bridge.close);bridge.timer.stop()
        bridge.receive(dict(action='poll',ok=True,data=dict(target='device',online=True,native_effects=True,state={'on':True},settings={'equalizer':True,'controller':{'mac':'680947485628','count':1}})))
        self.assertTrue(hasattr(bridge,'refresh_local_frame'))
        bridge._busy=True;bridge.current_action='power'
        bridge.refresh_local_frame()
        self.assertEqual(json.loads(bridge.dataJson)['frame']['source'],'music-local')
        bridge._busy=False
        bridge.receive(dict(action='poll',ok=True,data=dict(target='device',online=True,native_effects=True,state={'on':True},settings={'equalizer':True,'controller':{'mac':'680947485628','count':1}})))
        self.assertEqual((json.loads(bridge.dataJson).get('frame') or {}).get('source'),'music-local','status must not blank a fresh local frame')
        with patch.object(bridge,'executor') as executor:
            bridge.refresh()
            executor.submit.assert_not_called()
        bridge.generation+=1
        old=bridge.dataJson;bridge.refresh_local_frame();self.assertEqual(bridge.dataJson,old)

    def test_native_preview_does_not_make_controls_busy_or_starve_full_status(self):
        import desktop
        class Model:
            demo=None
            def __init__(self):self.polls=0
            def poll(self):
                self.polls+=1
                return dict(target='device',native_effects=True,settings={},state={'on':True})
            def preview_frame(self):return {'source':'esp','pixels':[[1,2,3]]}
            def close(self):pass
        model=Model();bridge=desktop.AppBridge(model);self.addCleanup(bridge.close);bridge.timer.stop()
        bridge.receive(dict(action='poll',ok=True,data=model.poll()))
        bridge.device_ticks=13;bridge.refresh()
        self.assertFalse(bridge.busy,'read-only preview must not disable controls')
        deadline=time.monotonic()+2
        while bridge._busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
        bridge.refresh()
        deadline=time.monotonic()+2
        while bridge._busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
        self.assertEqual(model.polls,2,'full status must still run after the preview interval')

    def test_native_preview_is_sparse_and_off_never_queries_rgb(self):
        import desktop
        class Model:
            demo=None
            def __init__(self):self.previews=0
            def preview_frame(self):self.previews+=1;return {'source':'esp'}
            def close(self):pass
        model=Model();bridge=desktop.AppBridge(model);self.addCleanup(bridge.close);bridge.timer.stop()
        bridge.receive(dict(action='poll',ok=True,data=dict(native_effects=True,settings={},state={'on':False})))
        for _ in range(5):
            bridge.refresh()
            deadline=time.monotonic()+1
            while bridge._busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
        self.assertEqual(model.previews,0,'Off must not request rendered RGB')
        bridge.receive(dict(action='poll',ok=True,data=dict(native_effects=True,settings={},state={'on':True})))
        for _ in range(5):
            bridge.refresh()
            deadline=time.monotonic()+1
            while bridge._busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
        self.assertLessEqual(model.previews,1,'back-to-back timer ticks must not duplicate preview network traffic')
        self.assertEqual(json.loads(bridge.dataJson)['frame'],{'source':'esp'},'native frame must persist between sparse reads')

    def test_named_preset_save_from_real_window_keeps_power_off(self):
        import control,desktop,desktop_bridge
        class Backend:
            def command(self,args):
                if args[0]=='firmware-status':return {'ok':True,'firmware':{}}
                return control.execute(args)
        with tempfile.TemporaryDirectory() as folder,patch.object(control,'CONFIG',Path(folder)),patch.object(control,'RUNTIME',Path(folder)/'runtime'):
            model=desktop_bridge.DesktopModel(Backend());engine,bridge=desktop.create_window(model);self.addCleanup(bridge.close)
            window=engine.rootObjects()[0];window.setProperty('page',1)
            field=window.findChild(QObject,'presetNameField');self.assertIsNotNone(field)
            field.setProperty('text','Evening')
            QMetaObject.invokeMethod(window.findChild(QObject,'savePresetButton'),'click')
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and not control.settings()['native_presets']:
                self.app.processEvents();time.sleep(.01)
            self.assertEqual(control.settings()['native_presets'][0]['name'],'Evening')
            self.assertFalse(control.settings()['equalizer'])
            self.assertFalse((control.CONFIG/'credentials.json').exists())
            window.close()

    def test_paired_wifi_receiver_can_be_read_and_configured_without_usb(self):
        import control,desktop,desktop_bridge
        class Backend:
            def __init__(self):self.calls=[]
            def command(self,args):
                return {'ok':True,'state':{'on':False,'bri':100}} if args[0]=='status' else {'ok':True,'firmware':{}}
            def setup(self,action,fields):
                self.calls.append((action,fields))
                return dict(ok=True,receiver=dict(mac='680947485628',connection='wifi',count=10,
                    outputs=[dict(gpio=2,count=10,order='GRB')],max_milliamps=500,
                    capabilities={'wifi_configure':True},wifi={'connected':True,'ip':'192.0.2.2'}))
        prefs={'controller':{'mac':'680947485628','count':10,'connection':'wifi','backend':'wesp'},'sections':[]}
        with patch.object(control,'settings',return_value=prefs):
            backend=Backend();model=desktop_bridge.DesktopModel(backend)
            engine,bridge=desktop.create_window(model,demo_capture=False);self.addCleanup(bridge.close)
            window=engine.rootObjects()[0];window.setProperty('page',4)
            bridge.receive(dict(action='poll',ok=True,data=model.poll()));self.app.processEvents()
            read=window.findChild(QObject,'readReceiverButton')
            self.assertIsNotNone(read,'an existing Wi-Fi device needs a discoverable read action')
            self.assertTrue(read.property('enabled'),'reading a paired Wi-Fi receiver must not require a USB port')
            QMetaObject.invokeMethod(read,'click')
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and not model.receiver:
                self.app.processEvents();time.sleep(.01)
            self.assertEqual(backend.calls[0][0],'status')
            self.assertEqual(backend.calls[0][1]['mac'],'680947485628')
            save=window.findChild(QObject,'saveOutputsButton')
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and not save.property('enabled'):
                self.app.processEvents();time.sleep(.01)
            self.assertTrue(save.property('enabled'))
            QMetaObject.invokeMethod(save,'click')
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and len(backend.calls)<2:
                self.app.processEvents();time.sleep(.01)
            self.assertEqual(backend.calls[-1][0],'configure')
            self.assertNotIn('ssid',backend.calls[-1][1])
            self.assertNotIn('password',backend.calls[-1][1])
            window.close()

    def test_unsaved_output_text_survives_poll_and_invalid_gpio_explains_save(self):
        import desktop
        class Model:
            demo=None
            def poll(self):
                return dict(target='device',configured=True,online=True,ports=[],firmware={},sections=[],settings={'controller':{'mac':'680947485628'}},
                    state={'on':False},receiver=dict(mac='680947485628',connection='usb',
                        outputs=[dict(gpio=2,count=10,order='GRB')],max_milliamps=500))
            def close(self):pass
        model=Model();engine,bridge=desktop.create_window(model);self.addCleanup(bridge.close)
        bridge.timer.stop();window=engine.rootObjects()[0];window.setProperty('page',4)
        bridge.receive(dict(action='poll',ok=True,data=model.poll()));self.app.processEvents()
        count=find_item(window,'outputCount0');self.assertIsNotNone(count)
        count.property('contentItem').setProperty('text','24')
        bridge.receive(dict(action='poll',ok=True,data=model.poll()));self.app.processEvents()
        self.assertEqual(find_item(window,'outputCount0').property('contentItem').property('text'),'24')
        QMetaObject.invokeMethod(window,'editOutput',Q_ARG('QVariant',0),Q_ARG('QVariant','gpio'),Q_ARG('QVariant',-1))
        self.app.processEvents()
        self.assertFalse(window.findChild(QObject,'saveOutputsButton').property('enabled'))
        self.assertTrue(window.findChild(QObject,'outputValidation').property('text'))
        window.close()

    def test_demo_direction_test_stops_on_off(self):
        import control,desktop,desktop_bridge
        with tempfile.TemporaryDirectory() as folder,patch.object(control,'CONFIG',Path(folder)), \
             patch.object(control,'RUNTIME',Path(folder)/'runtime'), \
             patch.object(desktop_bridge.DeviceBackend,'command',side_effect=AssertionError('device command')):
            model=desktop_bridge.DesktopModel();model.set_demo(True,capture=False)
            engine,bridge=desktop.create_window(model,demo_capture=False);self.addCleanup(bridge.close)
            window=engine.rootObjects()[0];window.setProperty('page',2)
            bridge.receive(dict(action='poll',ok=True,data=model.poll()));self.app.processEvents()
            button=find_item(window,'directionTest0');self.assertIsNotNone(button)
            QMetaObject.invokeMethod(button,'click')
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and (not model.demo.test_status()['active'] or bridge.busy):
                self.app.processEvents();time.sleep(.01)
            self.assertTrue(model.demo.test_status()['active'])
            QMetaObject.invokeMethod(window.findChild(QObject,'powerSwitch'),'click')
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and model.demo.on:
                self.app.processEvents();time.sleep(.01)
            self.assertFalse(model.demo.test_status()['active'])
            window.close()

    def test_real_window_edits_demo_without_a_device_command(self):
        import control
        import desktop
        import desktop_bridge
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(control, 'CONFIG', Path(folder)), \
             patch.object(control, 'RUNTIME', Path(folder) / 'runtime'), \
             patch.object(desktop_bridge.DeviceBackend, 'command', side_effect=AssertionError('device command')):
            model = desktop_bridge.DesktopModel()
            model.set_demo(True, capture=False)
            engine, bridge = desktop.create_window(model, demo_capture=False)
            self.addCleanup(bridge.close)
            roots = engine.rootObjects()
            self.assertEqual(len(roots), 1, 'standalone ApplicationWindow must load')
            window = roots[0]
            self.assertGreaterEqual(window.property('width'), 900)
            self.assertTrue(hasattr(window, 'grabWindow'), 'load the actual Qt Quick window wrapper')
            switch = window.findChild(QObject, 'powerSwitch')
            self.assertIsNotNone(switch)
            self.assertTrue(switch.property('checked'))
            QMetaObject.invokeMethod(switch, 'click')
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and model.demo.on:
                self.app.processEvents()
                time.sleep(.01)
            self.assertFalse(model.demo.on)
            self.assertFalse((Path(folder) / 'settings.json').exists())
            window.close()

    def test_style_preset_and_calm_scene_keep_demo_isolation_and_off(self):
        import control,desktop,desktop_bridge
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(control,'CONFIG',Path(folder)), \
             patch.object(control,'RUNTIME',Path(folder)/'runtime'), \
             patch.object(desktop_bridge.DeviceBackend,'command',side_effect=AssertionError('device command')):
            model=desktop_bridge.DesktopModel();model.set_demo(True,capture=False)
            engine,bridge=desktop.create_window(model,demo_capture=False)
            self.addCleanup(bridge.close)
            window=engine.rootObjects()[0]
            style=window.findChild(QObject,'musicStyleCombo');style.setProperty('currentIndex',1)
            QMetaObject.invokeMethod(style,'activated',Q_ARG(int,1))
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and model.demo.prefs['music_style']!='pulse':
                self.app.processEvents();time.sleep(.01)
            self.assertEqual(model.demo.prefs['music_style'],'pulse')
            preset=window.findChild(QObject,'musicPresetCombo');preset.setProperty('currentIndex',1)
            QMetaObject.invokeMethod(preset,'activated',Q_ARG(int,1))
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and model.demo.prefs['music_preset']!='soft':
                self.app.processEvents();time.sleep(.01)
            self.assertEqual(model.demo.prefs['music_preset'],'soft')
            model.demo.configure('on',False)
            QMetaObject.invokeMethod(window.findChild(QObject,'calmSceneButton'),'click')
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and model.demo.prefs['equalizer']:
                self.app.processEvents();time.sleep(.01)
            self.assertFalse(model.demo.prefs['equalizer'])
            self.assertFalse(model.demo.on)
            self.assertEqual(model.poll()['frame']['pixels'],[[0,0,0]]*20)
            self.assertFalse((Path(folder)/'settings.json').exists())
            window.close()

    def test_polling_keeps_unsaved_receiver_fields_and_configure_clears_password(self):
        import desktop
        import desktop_bridge
        class Model:
            demo = None
            def poll(self):
                return dict(target='device',configured=True,online=True,
                    settings={'controller':{'mac':'aabbccddeeff'}}, state={'on':False,'bri':100},
                    sections=[],ports=[],firmware={},receiver=dict(mac='aabbccddeeff',
                    outputs=[dict(gpio=2,count=10,order='GRB')],max_milliamps=500))
            def close(self):
                pass
        model = Model()
        engine, bridge = desktop.create_window(model)
        self.addCleanup(bridge.close)
        bridge.timer.stop()
        window = engine.rootObjects()[0]
        bridge.receive(dict(action='poll',ok=True,data=model.poll()))
        self.app.processEvents()
        field = window.findChild(QObject,'wifiPassword')
        field.setProperty('text','fixture-password')
        window.setProperty('wifiDirty',True)
        window.setProperty('currentBudget',900)
        window.setProperty('outputsDirty',True)
        bridge.receive(dict(action='poll',ok=True,data=model.poll()))
        bridge.completed.emit('setup-status',True)
        self.app.processEvents()
        self.assertEqual(field.property('text'),'fixture-password')
        self.assertEqual(window.property('currentBudget'),900)
        bridge.completed.emit('setup-configure',True)
        self.app.processEvents()
        self.assertEqual(field.property('text'),'')
        window.close()

    def test_second_launch_activates_the_existing_window(self):
        import control
        import desktop
        with tempfile.TemporaryDirectory(prefix='wesp-win-') as folder, \
             patch.object(control,'RUNTIME',Path(folder)):
            first=desktop.SingleWindow()
            self.assertTrue(first.acquire())
            from PySide6.QtQuick import QQuickWindow
            window=QQuickWindow()
            first.activate(window)
            second=desktop.SingleWindow()
            self.assertFalse(second.acquire())
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and not window.isVisible():
                self.app.processEvents()
                time.sleep(.01)
            self.assertTrue(window.isVisible())
            window.close()
            first.server.close()
            first.lock.unlock()

    def test_demo_brightness_gesture_cannot_be_delivered_after_leaving_demo(self):
        import control
        import desktop
        import desktop_bridge
        class Backend:
            def __init__(self): self.mutations=[]
            def command(self,args):
                if args[0]=='status': return dict(ok=True,state={'on':True,'bri':100})
                if args[0]=='firmware-status': return dict(ok=True,firmware={})
                self.mutations.append(args)
                return {'ok':True}
        prefs={'controller':{'mac':'aabbccddeeff','count':20},'sections':[]}
        with patch.object(control,'settings',return_value=prefs):
            backend=Backend();model=desktop_bridge.DesktopModel(backend)
            model.set_demo(True,capture=False)
            engine,bridge=desktop.create_window(model,demo_capture=False)
            self.addCleanup(bridge.close)
            window=engine.rootObjects()[0]
            slider=window.findChild(QObject,'brightnessSlider')
            slider.setProperty('value',200)
            QMetaObject.invokeMethod(slider,'moved')
            bridge.setDemo(False)
            # Also cover a command queued while the old demo is still displayed.
            bridge.action('brightness',['190'])
            deadline=time.monotonic()+.5
            while time.monotonic()<deadline:
                self.app.processEvents();time.sleep(.01)
            self.assertEqual(backend.mutations,[],'a demo gesture must never become a physical command')
            window.close()


if __name__ == '__main__':
    unittest.main()
