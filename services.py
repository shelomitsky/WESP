#!/usr/bin/python3
"""Portable service entry points. No private shell wrappers or home paths."""
import logging
import json
import subprocess
import sys
import time
import control
import wallpaper

LOG=logging.getLogger('wled-control')


def command(*args):
    return control.dispatch(list(args))


def monitor(kind):
    previous=None
    palette_watcher=wallpaper.desktop_watcher(control.RUNTIME) if kind=='accent' else None
    while True:
        try:
            prefs=control.settings()
            if not prefs.get('controller'):
                time.sleep(1)
                continue
            if kind == 'accent':
                if prefs.get('equalizer_palette')=='wallpaper':
                    palette_watcher.refresh()
                command('ambient-tick')
                color=control.kde_color()
                heartbeat=int(time.monotonic()) if prefs['kde'] and not prefs['equalizer'] else None
                key=(prefs['controller']['mac'],tuple(color),json.dumps(prefs['sections'],sort_keys=True),heartbeat)
                if key != previous:
                    command('apply')
                    previous=key
            else:
                result=subprocess.run(['wpctl','get-volume','@DEFAULT_AUDIO_SINK@'],
                                      capture_output=True,text=True,timeout=2,check=True)
                text=result.stdout
                percent=0 if 'MUTED' in text else round(float(text.split()[1])*100)
                if percent != previous:
                    command('volume',str(percent))
                    previous=percent
                else:
                    command('volume-end')
            time.sleep(.05 if kind == 'accent' else .1)
        except Exception:
            LOG.exception('%s monitor failed; retrying',kind)
            time.sleep(2)


def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    kind=sys.argv[1] if len(sys.argv)>1 else ''
    if kind == 'usb':
        import usb_transport
        usb_transport.serve()
    elif kind == 'equalizer':
        import equalizer
        equalizer.run()
    elif kind in ('volume','accent'):
        monitor(kind)
    elif kind in ('notifications','lifecycle'):
        import events
        from dbus.mainloop.glib import DBusGMainLoop
        DBusGMainLoop(set_as_default=True)
        (events.notifications if kind == 'notifications' else events.lifecycle)()
    else:
        raise SystemExit('Expected usb/equalizer/volume/accent/notifications/lifecycle')


if __name__ == '__main__':
    main()
