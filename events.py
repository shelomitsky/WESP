#!/usr/bin/python3
"""Desktop DBus events; notification IDs come from Notify's actual reply."""
from i18n import tr
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

CONTROL = str(Path(__file__).with_name('control.py'))


def command(*args):
    try:
        result = subprocess.run(['/usr/bin/python3', CONTROL, *args], timeout=10,
                                stdout=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        print('WLED event timeout: ' + args[0], file=sys.stderr, flush=True)
        return False
    if result.returncode:
        print('WLED event failed: ' + args[0], file=sys.stderr, flush=True)
    return result.returncode == 0


def notifications():
    bus = dbus.SessionBus(private=True)
    pending = {}
    worker = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def added(ident):
        command('notify-add', ident)

    def message(_bus, msg):
        kind = msg.get_type()
        if kind == dbus.lowlevel.MESSAGE_TYPE_METHOD_CALL and msg.get_member() == 'Notify':
            pending[(msg.get_sender(), msg.get_serial())] = True
            if len(pending) > 512:
                pending.clear()
        elif kind in (dbus.lowlevel.MESSAGE_TYPE_METHOD_RETURN, dbus.lowlevel.MESSAGE_TYPE_ERROR):
            key = (msg.get_destination(), msg.get_reply_serial())
            if pending.pop(key, False) and kind == dbus.lowlevel.MESSAGE_TYPE_METHOD_RETURN:
                args = msg.get_args_list()
                if args:
                    worker.submit(added, str(int(args[0])))
        elif kind == dbus.lowlevel.MESSAGE_TYPE_SIGNAL and msg.get_member() == 'NotificationClosed':
            args = msg.get_args_list()
            if args:
                worker.submit(command, 'notify-close', str(int(args[0])))

    bus.add_message_filter(message)
    bus.call_blocking('org.freedesktop.DBus', '/org/freedesktop/DBus',
                     'org.freedesktop.DBus.Monitoring', 'BecomeMonitor', 'asu',
                     (["type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
                       "type='method_return'", "type='error'",
                       "type='signal',interface='org.freedesktop.Notifications',member='NotificationClosed'"], 0))
    GLib.MainLoop().run()


def lifecycle():
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object('org.freedesktop.login1', '/org/freedesktop/login1'),
                             'org.freedesktop.login1.Manager')
    inhibitor = [None]
    wake_retry = [None]

    def retry_wake():
        if command('wake'):
            wake_retry[0] = None
            return False
        return True

    def cancel_retry():
        if wake_retry[0] is not None:
            GLib.source_remove(wake_retry[0])
            wake_retry[0] = None

    def restore():
        cancel_retry()
        if not command('wake'):
            wake_retry[0] = GLib.timeout_add_seconds(5, retry_wake)

    def acquire():
        try:
            inhibitor[0] = manager.Inhibit('sleep:shutdown', 'WESP',
                                           tr("Turning off lighting before sleep"), 'delay').take()
        except dbus.DBusException as e:
            print('WLED: sleep delay inhibitor unavailable: ' + str(e), file=sys.stderr, flush=True)

    def release():
        if inhibitor[0] is not None:
            os.close(inhibitor[0])
            inhibitor[0] = None

    def sleep_event(sleeping):
        if sleeping:
            cancel_retry()
            try:
                command('sleep')
            finally:
                release()
        else:
            try:
                restore()
            finally:
                acquire()

    def shutdown_event(shutting_down):
        if shutting_down:
            cancel_retry()
            try:
                command('shutdown')
            finally:
                release()
        else:
            restore()
            acquire()

    manager.connect_to_signal('PrepareForSleep', sleep_event)
    manager.connect_to_signal('PrepareForShutdown', shutdown_event)
    command('session-start')
    acquire()
    GLib.MainLoop().run()


if __name__ == '__main__':
    DBusGMainLoop(set_as_default=True)
    if sys.argv[1:] == ['notifications']:
        notifications()
    elif sys.argv[1:] == ['lifecycle']:
        lifecycle()
    else:
        sys.exit('Expected notifications or lifecycle')
