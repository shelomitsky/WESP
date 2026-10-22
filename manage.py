#!/usr/bin/python3
"""Per-user installation with an owned-file manifest and local rollback."""
import argparse
import base64
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

SOURCE=Path(__file__).resolve().parent
MODES=dict(usb='usb',equalizer='equalizer',volume='volume',notify='notifications',
           accent='accent',session='lifecycle')
UNITS=['wled-control-'+name+'.service' for name in MODES]


def paths():
    home=Path.home()
    return dict(home=home,data=Path(os.environ.get('XDG_DATA_HOME',home/'.local/share')),
                state=Path(os.environ.get('XDG_STATE_HOME',home/'.local/state'))/'wled-control-desktop',
                config=Path(os.environ.get('XDG_CONFIG_HOME',home/'.config')))


def atomic_write(path,data,mode=0o644):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.wled-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp,mode)
        os.replace(tmp,path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def systemctl(*args,check=True):
    return subprocess.run(['systemctl','--user',*args],check=check,
                          capture_output=True,text=True,timeout=15)


def doctor():
    missing=[name for name in ('numpy','serial','dbus','gi','PIL') if importlib.util.find_spec(name) is None]
    missing += [name for name in ('parec','wpctl','systemctl','plasmashell') if not shutil.which(name)]
    if not missing:
        try:
            from gi.repository import GLib
        except ImportError:
            missing.append('GLib introspection')
    return missing


def payloads():
    p=paths()
    app=p['data']/'wled-control'
    result={}
    for name in ('control.py','equalizer.py','usb_transport.py','usb_probe.py','events.py',
                 'layout.py','notification_fx.py','wallpaper.py','i18n.py','services.py','manage.py','LICENSE','README.md'):
        result[app/name]=((SOURCE/name).read_bytes(),0o644)
    for catalog in (SOURCE/'locale').glob('*/LC_MESSAGES/plasma_applet_org.wledcontrol.desktop.mo'):
        relative=catalog.relative_to(SOURCE/'locale')
        data=catalog.read_bytes()
        result[p['data']/'locale'/relative]=(data,0o644)
        result[app/'locale'/relative]=(data,0o644)
    widget='org.wledcontrol.desktop'
    icon=SOURCE/'plasma'/widget/'contents/images/wled-control.svg'
    result[p['data']/'icons/hicolor/scalable/apps/wled-control.svg']=(icon.read_bytes(),0o644)
    for file in (SOURCE/'plasma'/widget).rglob('*'):
        if file.is_file():
            relative=file.relative_to(SOURCE/'plasma'/widget)
            result[p['data']/'plasma/plasmoids'/widget/relative]=(file.read_bytes(),0o644)
            result[app/'plasma'/widget/relative]=(file.read_bytes(),0o644)
    for launcher,module in (('wled-control','control.py'),('wled-control-service','services.py')):
        text='#!/usr/bin/python3\nimport os,sys\nos.execv(sys.executable,[sys.executable,'+repr(str(app/module))+',*sys.argv[1:]])\n'
        result[p['home']/'.local/bin'/launcher]=(text.encode(),0o755)
    for name,mode in MODES.items():
        text='[Unit]\nDescription=WESP '+name+'\nAfter=graphical-session.target\nPartOf=graphical-session.target\n'
        if name != 'usb':
            text+='After=wled-control-usb.service\nWants=wled-control-usb.service\n'
        text+='\n[Service]\nExecStart=%h/.local/bin/wled-control-service '+mode+'\nRestart=on-failure\nRestartSec=3\nTimeoutStopSec=12\nUMask=0077\n\n[Install]\nWantedBy=graphical-session.target\n'
        result[p['config']/'systemd/user'/('wled-control-'+name+'.service')]=(text.encode(),0o644)
    return result


def read_manifest():
    file=paths()['state']/'install.json'
    return json.loads(file.read_text()) if file.exists() else {}


def check_owned(manifest,targets):
    for name,expected in manifest.items():
        file=Path(name)
        if file not in targets or file.is_symlink() or not file.is_file():
            raise ValueError('Managed file missing or unsafe: '+str(file))
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError('File edited after installation: '+str(file))


@contextlib.contextmanager
def transaction_lock():
    directory=paths()['state']
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (directory/'install.lock').open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        yield


def save_backup(targets,previous,start):
    directory=paths()['state']/'backups'/uuid.uuid4().hex
    directory.mkdir(parents=True,mode=0o700)
    files={str(p):dict(data=base64.b64encode(p.read_bytes()).decode(),mode=p.stat().st_mode & 0o777)
           if p.exists() else None for p in targets}
    states={u:dict(active=systemctl('is-active',u,check=False).returncode==0,
                   enabled=systemctl('is-enabled',u,check=False).returncode==0)
            for u in UNITS} if start else {}
    record=dict(files=files,previous=previous,services=states)
    atomic_write(directory/'transaction.json',json.dumps(record).encode(),0o600)
    return directory,record


def stop_services():
    systemctl('stop',*UNITS,check=False)


def prepare_service_restore(record):
    stop_services()
    # Remove new enablement links while their unit files still exist.
    for unit,old in record['services'].items():
        if not old['enabled']:
            systemctl('disable',unit,check=False)


def restore(record,start):
    allowed=set(payloads())
    for name,snapshot in record['files'].items():
        target=Path(name)
        if target not in allowed or target.is_symlink():
            raise ValueError('Unsafe backup target')
        if snapshot is None:
            target.unlink(missing_ok=True)
        else:
            atomic_write(target,base64.b64decode(snapshot['data']),snapshot['mode'])
    state=paths()['state']/'install.json'
    if record['previous']:
        atomic_write(state,json.dumps(record['previous']).encode(),0o600)
    else:
        state.unlink(missing_ok=True)
    if start:
        systemctl('daemon-reload')
        for unit,old in record['services'].items():
            systemctl('enable' if old['enabled'] else 'disable',unit,check=False)
            if old['active']:
                systemctl('start',unit)


def install(start=True):
    if start:
        missing=doctor()
        if missing:
            raise ValueError('Missing dependencies: '+', '.join(missing))
        systemctl('show-environment')
    with transaction_lock():
        targets=payloads()
        previous=read_manifest()
        check_owned(previous,targets)
        for file in targets:
            if file.is_symlink() or (file.exists() and str(file) not in previous):
                raise ValueError('Refusing to replace an unmanaged file: '+str(file))
        backup,record=save_backup(targets,previous,start)
        try:
            if start:
                stop_services()
            installed={}
            for file,(data,mode) in targets.items():
                atomic_write(file,data,mode)
                installed[str(file)]=hashlib.sha256(data).hexdigest()
            atomic_write(paths()['state']/'install.json',json.dumps(installed).encode(),0o600)
            if start:
                systemctl('daemon-reload')
                if not previous:
                    systemctl('enable','--now',*UNITS)
                else:
                    for unit,old in record['services'].items():
                        if old['active']:
                            systemctl('start',unit)
        except Exception:
            if start:
                prepare_service_restore(record)
            restore(record,start)
            raise
        return backup


def rollback(directory,start=True):
    if start:
        systemctl('show-environment')
    directory=Path(directory).resolve()
    if directory.parent != (paths()['state']/'backups').resolve():
        raise ValueError('Choose a backup from the application state directory')
    with transaction_lock():
        targets=payloads()
        current=read_manifest()
        check_owned(current,targets)
        record=json.loads((directory/'transaction.json').read_text())
        for name in record['files']:
            if Path(name).exists() and name not in current:
                raise ValueError('Refusing to replace an unmanaged file')
        if start:
            prepare_service_restore(record)
        restore(record,start)


def remove(start=True):
    if start:
        systemctl('show-environment')
    with transaction_lock():
        manifest=read_manifest()
        check_owned(manifest,payloads())
        if start and manifest:
            stop_services()
            systemctl('disable',*UNITS,check=False)
        for file in manifest:
            Path(file).unlink()
        (paths()['state']/'install.json').unlink(missing_ok=True)
        if start:
            systemctl('daemon-reload')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','uninstall','rollback','doctor'])
    parser.add_argument('backup',nargs='?')
    parser.add_argument('--no-start',action='store_true',help='Stage files without accessing services or hardware')
    args=parser.parse_args()
    try:
        if args.action == 'doctor':
            missing=doctor()
            print('Missing: '+', '.join(missing) if missing else 'Dependencies available; desktop/device acceptance still required')
            return bool(missing)
        if args.action == 'install':
            print('Backup:',install(start=not args.no_start))
        elif args.action == 'uninstall':
            remove(start=not args.no_start)
            print('Removed owned files; user settings retained')
        else:
            if not args.backup:
                raise ValueError('Choose a backup directory')
            rollback(args.backup,start=not args.no_start)
        return 0
    except Exception as error:
        parser.exit(1,'Install error: '+str(error)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
