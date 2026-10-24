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
    if importlib.util.find_spec('PySide6') is None:
        runtime=paths()['data']/'wled-control-tools/desktop-qt6/bin/python'
        try:
            subprocess.run([str(runtime),'-c','from PySide6.QtQuick import QQuickWindow'],
                           check=True,capture_output=True,timeout=8)
        except (OSError,subprocess.SubprocessError):
            missing.append('PySide6 (standalone GUI)')
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
                 'layout.py','notification_fx.py','wallpaper.py','i18n.py','services.py','firmware.py',
                 'wesp_transport.py','receiver_setup.py','receiver_assets.py','manage.py','LICENSE','README.md',
                 'desktop.py','desktop_bridge.py','preview.py'):
        result[app/name]=((SOURCE/name).read_bytes(),0o644)
    for file in (SOURCE/'app').glob('*.qml'):
        result[app/'app'/file.name]=(file.read_bytes(),0o644)
    if (SOURCE/'receiver-firmware/manifest.json').exists():
        import receiver_assets
        receiver_assets.validated(SOURCE/'receiver-firmware')
        for name in ['manifest.json',*receiver_assets.OFFSETS]:
            result[app/'receiver-firmware'/name]=((SOURCE/'receiver-firmware'/name).read_bytes(),0o600)
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
    for launcher,module in (('wled-control','control.py'),('wled-control-service','services.py'),('wesp','desktop.py')):
        text='#!/usr/bin/python3\nimport os,sys\nos.execv(sys.executable,[sys.executable,'+repr(str(app/module))+',*sys.argv[1:]])\n'
        result[p['home']/'.local/bin'/launcher]=(text.encode(),0o755)
    executable=str(app/'desktop.py').replace('%','%%')
    executable=executable.replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')
    executable=executable.replace('\\','\\\\')
    entry='[Desktop Entry]\nType=Application\nName=WESP\nComment=Desktop ambient lighting\nExec=/usr/bin/python3 "'+executable+'"\nIcon=wled-control\nTerminal=false\nCategories=Utility;Settings;\n'
    result[p['data']/'applications/wesp.desktop']=(entry.encode(),0o644)
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
    states=service_states() if start else {}
    activation=paths()['state']/'activation.json'
    record=dict(files=files,previous=previous,services=states,
                activation=activation.read_text() if activation.exists() else None)
    atomic_write(directory/'transaction.json',json.dumps(record).encode(),0o600)
    return directory,record


def service_running(unit):
    result=systemctl('is-active',unit,check=False)
    return result.returncode==0 or getattr(result,'stdout','').strip() in (
        'activating','reloading','deactivating','refreshing')


def service_states():
    return {unit:dict(active=service_running(unit),
                      enabled=systemctl('is-enabled',unit,check=False).returncode==0)
            for unit in UNITS}


def stop_services():
    # Existing units may be activating or waiting for an automatic restart;
    # a binary is-active check is insufficient to cancel those jobs.
    directory=paths()['config']/'systemd/user'
    units=[unit for unit in UNITS if (directory/unit).exists() or service_running(unit)]
    if units:
        systemctl('stop',*units)


def stop_for_transaction(record):
    try:
        stop_services()
    except Exception:
        # A failed multi-unit stop can already have stopped some units.
        failed=[]
        for unit,old in record['services'].items():
            if old['active']:
                if systemctl('start',unit,check=False).returncode:
                    failed.append(unit)
        if failed:
            raise RuntimeError('Service stop failed; could not restart: '+', '.join(failed))
        raise


def prepare_service_restore(record,stop=True):
    if stop:
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
    activation=paths()['state']/'activation.json'
    if record.get('activation') is None:
        activation.unlink(missing_ok=True)
    else:
        atomic_write(activation,record['activation'].encode(),0o600)
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
        activation=paths()['state']/'activation.json'
        # Missing metadata belongs to a legacy managed installation: preserve
        # its intentional inactive/disabled states on upgrade.
        activated=json.loads(activation.read_text())['activated'] if activation.exists() else bool(previous)
        if start:
            stop_for_transaction(record)
        try:
            installed={}
            for file,(data,mode) in targets.items():
                atomic_write(file,data,mode)
                installed[str(file)]=hashlib.sha256(data).hexdigest()
            atomic_write(paths()['state']/'install.json',json.dumps(installed).encode(),0o600)
            if start:
                systemctl('daemon-reload')
                if not activated:
                    systemctl('enable','--now',*UNITS)
                else:
                    for unit,old in record['services'].items():
                        if old['active']:
                            systemctl('start',unit)
            atomic_write(activation,json.dumps(dict(activated=activated or start)).encode(),0o600)
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
        recovery_backup,recovery=save_backup([Path(name) for name in record['files']],current,start)
        if start:
            stop_for_transaction(recovery)
        try:
            if start:
                prepare_service_restore(record,stop=False)
            restore(record,start)
        except Exception:
            try:
                if start:
                    prepare_service_restore(recovery)
                restore(recovery,start)
            except Exception as error:
                raise RuntimeError('Rollback recovery failed; backup: '+str(recovery_backup)) from error
            raise


def remove(start=True):
    if start:
        systemctl('show-environment')
    with transaction_lock():
        manifest=read_manifest()
        check_owned(manifest,payloads())
        if not manifest:
            return
        backup,record=save_backup([Path(name) for name in manifest],manifest,start)
        if start:
            stop_for_transaction(record)
        try:
            if start:
                systemctl('disable',*UNITS)
            for file in manifest:
                Path(file).unlink()
            (paths()['state']/'install.json').unlink(missing_ok=True)
            (paths()['state']/'activation.json').unlink(missing_ok=True)
            if start:
                systemctl('daemon-reload')
        except Exception:
            if start:
                prepare_service_restore(record)
            restore(record,start)
            raise


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
