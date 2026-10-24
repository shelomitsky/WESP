#!/usr/bin/env python3
"""WESP standalone Qt application; the device remains owned by its service."""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys

try:
    from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot, QLockFile
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow  # Register the QML window's Python wrapper.
except ImportError:
    if __name__ == '__main__':
        runtime = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'wled-control-tools/desktop-qt6/bin/python'
        if runtime.is_file() and str(runtime) != sys.executable:
            os.execv(str(runtime), [str(runtime), str(Path(__file__).resolve()), *sys.argv[1:]])
        raise SystemExit('WESP needs PySide6. See README: Standalone application.')
    raise

import control
import desktop_bridge
import i18n
from i18n import tr

ROOT = Path(__file__).resolve().parent


class AppBridge(QObject):
    changed = Signal()
    busyChanged = Signal()
    completed = Signal(str, bool)
    received = Signal(object)

    def __init__(self, model, demo_capture=True):
        super().__init__(QGuiApplication.instance())
        self.model = model
        self.demo_capture = demo_capture
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='wesp-ui')
        self.queue = deque()
        self.generation = self.view_generation = 0
        self._busy, self._closed = False, False
        initial = model.poll() if model.demo is not None else dict(
            target='device', configured=False, online=False, settings={},
            state={'on': False, 'bri': 128}, sections=[], ports=[], receiver={}, firmware={}, message='')
        self._data = json.dumps(initial)
        self._error = ''
        self.received.connect(self.receive)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    @Property(str, notify=changed)
    def dataJson(self):
        return self._data

    @Property(str, notify=changed)
    def error(self):
        return self._error

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy and bool(self.queue or self.current_action not in ('poll','preview'))

    @Slot(str, result=str)
    def text(self, message):
        # Literal app QML keys are collected by check_translations.py.
        return i18n.tr(message)

    @Slot(str, 'QVariantList')
    def action(self, action, args):
        if self._closed:
            return
        if self.view_generation != self.generation:
            return  # The displayed controls still belong to the previous target.
        target = self.view_target()
        self.enqueue(action, args, target)

    def view_target(self):
        data = json.loads(self._data)
        return ('demo' if data.get('target') == 'demo' else
                'device:' + str(((data.get('settings') or {}).get('controller') or {}).get('mac', '')))

    @Property(str, notify=changed)
    def commandTarget(self):
        return str(self.view_generation) + ':' + self.view_target()

    @Slot(str, str, 'QVariantList')
    def actionFor(self, target, action, args):
        if target == self.commandTarget:
            self.action(action, args)

    def enqueue(self, action, args, target):
        if len(self.queue) >= 32:
            self._error = tr('Wait for the current operation to finish')
            self.changed.emit()
            return
        item = (action, list(args), target, self.generation)
        if action == 'brightness' and self.queue and self.queue[-1][0] == action:
            self.queue[-1] = item
        else:
            self.queue.append(item)
        self.busyChanged.emit()
        self.refresh()

    @Slot(bool)
    def setDemo(self, enabled):
        self.generation += 1
        self.queue.clear()
        self.enqueue('demo', [enabled], None)

    @Slot()
    def refresh(self):
        if self._busy or self._closed:
            return
        native_preview=False
        if not self.queue and self.model.demo is None:
            # Device status is deliberately slower than the local frame preview.
            if getattr(self, 'device_ticks', 0) < 14:
                self.device_ticks = getattr(self, 'device_ticks', 0) + 1
                import preview
                current = json.loads(self._data)
                if current.get('native_effects'):
                    native_preview=True
                selected = (current.get('settings') or {}).get('controller') or {}
                frame = preview.read(control.RUNTIME / 'frame-preview.json', selected.get('mac'))
                if not native_preview and frame != current.get('frame'):
                    current['frame'] = frame
                    self._data = json.dumps(current)
                    self.changed.emit()
                if not native_preview:return
            else:
                self.device_ticks = 0
        action, args, target, generation = self.queue.popleft() if self.queue else ('preview' if native_preview else 'poll', [], None, self.generation)
        self.current_action, self._busy = action, True
        self.busyChanged.emit()
        def work():
            try:
                if action=='preview':
                    current=json.loads(self._data)
                    current['frame']=self.model.preview_frame()
                    return dict(action='poll',ok=True,data=current,generation=generation)
                if action == 'demo':
                    self.model.set_demo(bool(args[0]), capture=self.demo_capture)
                elif action != 'poll':
                    if generation != self.generation or target != self.model.identity():
                        return dict(action='poll', ok=True, data=self.model.poll(), generation=self.generation)
                    self.model.command(action, args)
                name = 'setup-' + args[0] if action == 'setup' else action
                return dict(action=name, ok=True, data=self.model.poll(), generation=generation)
            except Exception as error:
                return dict(action=action, ok=False, error=str(error))
        def ready(future):
            if not self._closed:
                self.received.emit(future.result())
        self.executor.submit(work).add_done_callback(ready)

    @Slot(object)
    def receive(self, result):
        self._busy = False
        if result['ok']:
            self._data = json.dumps(result['data'])
            self.view_generation = result.get('generation', self.generation)
            if result['action'] != 'poll':
                self._error = ''
        else:
            self._error = result['error']
        self.changed.emit()
        self.busyChanged.emit()
        if result['action'] != 'poll':
            self.completed.emit(result['action'], result['ok'])
        if self.queue:
            self.refresh()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self.queue.clear()
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.model.close()


def create_window(model=None, demo_capture=True):
    model = model or desktop_bridge.DesktopModel()
    bridge = AppBridge(model, demo_capture)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('bridge', bridge)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'app/Main.qml')))
    return engine, bridge


class SingleWindow:
    def __init__(self):
        control.RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = str(control.RUNTIME / 'desktop.sock')
        self.lock = QLockFile(str(control.RUNTIME / 'desktop.lock'))
        self.server = QLocalServer()

    def acquire(self):
        if not self.lock.tryLock(0):
            peer = QLocalSocket()
            peer.connectToServer(self.path)
            if not peer.waitForConnected(1500):
                raise RuntimeError(tr('The WESP window is starting. Try again shortly.'))
            peer.write(b'activate')
            peer.waitForBytesWritten(1000)
            peer.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.path)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        if not self.server.listen(self.path):
            raise RuntimeError(self.server.errorString())
        return True

    def activate(self, window):
        def connected():
            peer = self.server.nextPendingConnection()
            if peer:
                peer.disconnectFromServer()
                peer.deleteLater()
            window.showNormal()
            window.raise_()
            window.requestActivate()
        self.server.newConnection.connect(connected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='Preview desktop audio without a device')
    parser.add_argument('--screenshot', help=argparse.SUPPRESS)
    parser.add_argument('--quit-after', type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName('WESP')
    app.setDesktopFileName('wesp')
    app.setWindowIcon(QIcon(str(ROOT / 'plasma/org.wledcontrol.desktop/contents/images/wled-control.svg')))
    single = SingleWindow()
    if not single.acquire():
        return 0
    model = desktop_bridge.DesktopModel()
    if args.demo:
        model.set_demo(True)
    engine, bridge = create_window(model)
    if not engine.rootObjects():
        bridge.close()
        return 1
    window = engine.rootObjects()[0]
    single.activate(window)
    app.aboutToQuit.connect(bridge.close)
    if args.screenshot:
        def capture():
            if not window.grabWindow().save(args.screenshot):
                app.exit(1)
        QTimer.singleShot(2500, capture)
    if args.quit_after:
        QTimer.singleShot(args.quit_after * 1000, app.quit)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
