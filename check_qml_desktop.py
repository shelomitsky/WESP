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


class DesktopWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

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
