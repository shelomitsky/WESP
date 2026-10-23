"""Explicit, backed-up first installation of WLED on a classic 4MB ESP32.

The background worker runs in its own managed esptool environment. No UART is
opened by status polling, and identity checks and writes share one connection.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.request
import uuid

from i18n import tr

VERSION = '0.15.3'
FLASH_SIZE = 4 * 1024 * 1024
IMAGES = {
    'esp32_bootloader_v4.bin': ('v0.13.1', '694d36d82db55b39060f2e0a2ab348d665d8a0d15659b2f5864f315b8d33eeb6', 0),
    'WLED_0.15.3_ESP32.bin': ('v0.15.3', '76cdbfb8b13a818b266df937d346b7f5534b0d115be3c537ec1fb12ab0515468', 0x10000),
}
BUSY = {'starting', 'tools', 'download', 'detecting', 'backup', 'writing', 'connecting'}


def state_root():
    return Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/'wled-control-desktop/firmware'


def read_job(root=None):
    root = root or state_root()
    try:
        return json.loads((root/'job.json').read_text())
    except FileNotFoundError:
        return dict(stage='idle')


def save_job(root, data):
    import manage
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    manage.atomic_write(root/'job.json', json.dumps(data).encode(), 0o600)


def stage(root, data, name, **fields):
    data.update(stage=name, updated=time.time(), **fields)
    save_job(root, data)


def systemctl(*args):
    return subprocess.run(['systemctl', '--user', *args], check=True,
                          capture_output=True, text=True, timeout=30)


def restore_services(active):
    if active:
        systemctl('start', *active)


def finish(root, data, error=None):
    try:
        restore_services(data.get('active', []))
        data.update(active=[], recovery_pending=False)
    except Exception as recovery:
        data['recovery_pending']=True
        error = RuntimeError(str(error or '')+'; '+tr('Could not restart WESP services')+': '+str(recovery))
    stage(root, data, 'failed' if error else data['stage'], error=str(error) if error else '')


def port_identity(port):
    from serial.tools.list_ports import comports
    for item in comports():
        if item.device == port:
            return dict(port=port, vid=item.vid, pid=item.pid,
                        serial=item.serial_number, location=item.location)
    raise ValueError(tr('The selected USB device is no longer connected'))


def validate_port(port):
    if not re.fullmatch(r'/dev/tty(?:USB|ACM)[0-9]+', port):
        raise ValueError(tr('Select a USB serial port from the list'))
    return port_identity(port)


def validate_board(board, expected=None):
    if (board.get('chip') != 'ESP32' or board.get('size') != FLASH_SIZE
            or board.get('secure') or not re.fullmatch(r'[0-9a-f]{12}', board.get('mac', ''))):
        raise ValueError(tr('Only an unencrypted classic ESP32 with 4 MB flash is supported'))
    if expected and board != expected:
        raise ValueError(tr('The USB controller changed. Prepare the selected board again'))


def check_file(path, digest, size=None):
    if ((size is not None and path.stat().st_size != size)
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
        raise ValueError(tr('File verification failed. Nothing has been written'))


def merged_image(folder):
    combined = bytearray(b'\xff' * FLASH_SIZE)
    end = 0
    for name, (_, digest, offset) in IMAGES.items():
        path = folder/name
        check_file(path, digest)
        payload = path.read_bytes()
        if offset < end or offset + len(payload) > FLASH_SIZE:
            raise ValueError(tr('The firmware image does not fit this board'))
        combined[offset:offset+len(payload)] = payload
        end = offset + len(payload)
    target = folder/'combined.bin'
    target.write_bytes(combined)
    return target


def download_images(folder):
    for name, (tag, digest, _) in IMAGES.items():
        target = folder/name
        if not target.exists():
            url = 'https://github.com/wled/WLED/releases/download/'+tag+'/'+name
            with urllib.request.urlopen(url, timeout=60) as response:
                content = response.read(FLASH_SIZE + 1)
            if len(content) > FLASH_SIZE:
                raise ValueError(tr('The firmware image does not fit this board'))
            import manage
            manage.atomic_write(target, content, 0o600)
        check_file(target, digest)


def tool_python():
    base = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'wled-control-tools/esptool-4.11.0'
    python = base/'bin/python'
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(base)], check=True, timeout=120)
    probe = subprocess.run([str(python), '-c', 'import esptool; assert esptool.__version__ == "4.11.0"'],
                           capture_output=True, timeout=15)
    if probe.returncode:
        subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                        'esptool==4.11.0'], check=True, timeout=240)
    return python


def process_stamp(pid):
    try:
        return (Path('/proc')/str(pid)/'stat').read_text().rsplit(')', 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


@contextlib.contextmanager
def job_lock(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root/'job.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def status():
    root=state_root()
    with job_lock(root):
        data=read_job(root)
        if data.get('recovery_pending'):
            finish(root, data, RuntimeError(data.get('error') or tr('Could not restart WESP services')))
            data=read_job(root)
        if (data['stage'] in BUSY and
                ((data.get('pid') and process_stamp(data['pid']) != data.get('stamp'))
                 or (not data.get('pid') and time.time()-data.get('updated', 0) > 10))):
            finish(root, data, RuntimeError(tr('Installation was interrupted. The backup has been retained')))
            data=read_job(root)
    return data


def start(action, value):
    root=state_root()
    status()
    with job_lock(root):
        data=read_job(root)
        if data.get('recovery_pending'):
            raise ValueError(tr('Could not restart WESP services'))
        if data['stage'] in BUSY:
            raise ValueError(tr('A controller installation is already running'))
        if action in ('prepare','prepare-native'):
            native=action=='prepare-native'
            action='prepare'
            identity=validate_port(value)
            folder=root/uuid.uuid4().hex
            folder.mkdir(mode=0o700)
            data=dict(stage='starting', port=value, identity=identity, folder=str(folder),
                      version=VERSION, percent=0, active=[], error='')
            if native:
                import receiver_assets
                manifest=receiver_assets.stage(Path(__file__).resolve().parent/'receiver-firmware',folder)
                data.update(flavor='wesp',version=manifest['version'])
        elif action == 'install':
            if data['stage'] != 'prepared' or value != data.get('token'):
                raise ValueError(tr('Prepare the board before confirming installation'))
            data.update(stage='starting', error='', percent=0)
        elif action == 'cancel':
            if data['stage'] != 'prepared' or value != data.get('token'):
                raise ValueError(tr('Installation can only be cancelled before writing starts'))
            stage(root, data, 'cancelled')
            return data
        else:
            raise ValueError(tr('Unknown command'))
        data.update(updated=time.time(), pid=None, stamp=None)
        save_job(root, data)
        # The worker takes the same short lock before reading its initial state.
        with (Path(data['folder'])/'installer.log').open('ab', buffering=0) as log:
            proc=subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'launch', action],
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                  start_new_session=True, close_fds=True)
        data.update(pid=proc.pid, stamp=process_stamp(proc.pid))
        save_job(root, data)
    return data


def pause_services(root, data):
    """Pause only WESP's own services if its USB owner holds this exact port."""
    data['active']=[]
    save_job(root, data)
    result=systemctl('show', 'wled-control-usb.service', '--property=MainPID', '--value')
    pid=int(result.stdout.strip() or '0')
    holds=False
    if pid:
        for fd in (Path('/proc')/str(pid)/'fd').iterdir():
            try:
                holds |= os.path.realpath(fd) == os.path.realpath(data['port'])
            except OSError:
                pass
    active=[]
    if holds:
        import manage
        for unit in manage.UNITS:
            result=subprocess.run(['systemctl','--user','is-active','--quiet',unit],timeout=10)
            if result.returncode == 0:
                active.append(unit)
        data['active']=active
        save_job(root, data)  # Recovery state is durable before stopping anything.
        if active:
            systemctl('stop', *active)
    return active


def board_info(esp):
    # Security fuses are read only. Never force writes on protected hardware.
    board=dict(chip=esp.CHIP_NAME, mac=bytes(esp.read_mac()).hex(),
               size=2 ** ((esp.flash_id() >> 16) & 0xff),
               secure=bool(esp.get_secure_boot_enabled() or esp.get_flash_encryption_enabled()))
    validate_board(board)
    return board


def require_free_port(port):
    result=subprocess.run(['fuser', port], capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        raise ValueError(tr('The USB port is used by another application. Close it and try again'))
    if result.returncode != 1:
        raise ValueError(tr('Could not check who is using the USB port'))


class BackupVerificationError(ValueError):
    pass


def read_verified_backup(esp, progress, retry_errors):
    """One read-only fallback; never retry writes or swallow cancellation."""
    retryable=tuple(retry_errors)+(BackupVerificationError,)
    for attempt in range(2):
        try:
            image=esp.read_flash(0,FLASH_SIZE,progress)
            if len(image)!=FLASH_SIZE:
                raise BackupVerificationError(tr('The backup is incomplete. Nothing has been written'))
            remote=esp.flash_md5sum(0,FLASH_SIZE)
            if isinstance(remote,bytes):
                remote=remote.decode('ascii')
            if remote!=hashlib.md5(image).hexdigest():
                raise BackupVerificationError(tr('The backup does not match the controller. Nothing has been written'))
            return image
        except retryable:
            if attempt:
                raise
            # Reuse the same exclusive connection and pinned board. Clear any
            # trailing reply before the baud-change command, then start at 0.
            esp._port.reset_input_buffer()
            esp.change_baud(115200)
            print('Restarting read-only backup at 115200 baud',flush=True)
            progress(0,FLASH_SIZE)


def operate(root, data, action):
    import esptool
    if validate_port(data['port']) != data['identity']:
        raise ValueError(tr('The USB controller changed. Prepare the selected board again'))
    pause_services(root, data)
    require_free_port(data['port'])
    stage(root, data, 'detecting')
    # esptool opens the serial port with exclusive=True. Keep it open through
    # security/identity verification and all flash operations, with no stub.
    esp=esptool.detect_chip(data['port'], baud=115200)
    try:
        esp.flash_spi_attach(0)
        esp.flash_set_parameters(FLASH_SIZE)
        board=board_info(esp)
        esp.change_baud(460800)
        if action == 'prepare':
            data['board']=board
            stage(root, data, 'backup', percent=0)
            updated=[0.0]
            def progress(done, length):
                if time.monotonic()-updated[0] > 1 or done == length:
                    stage(root, data, 'backup', percent=int(done*100/length),backup_baud=esp._port.baudrate)
                    updated[0]=time.monotonic()
            image=read_verified_backup(esp,progress,(esptool.FatalError,OSError,TimeoutError))
            if len(image) != FLASH_SIZE:
                raise ValueError(tr('The backup is incomplete. Nothing has been written'))
            import manage
            backup=Path(data['folder'])/'original-flash.bin'
            manage.atomic_write(backup, image, 0o600)
            digest=hashlib.sha256(image).hexdigest()
            check_file(backup, digest, size=FLASH_SIZE)
            data.update(backup=str(backup), backup_sha256=digest, token=uuid.uuid4().hex)
            data.update(stage='prepared', percent=100)
        else:
            validate_board(board, expected=data['board'])
            check_file(Path(data['backup']), data['backup_sha256'], size=FLASH_SIZE)
            if data.get('flavor')=='wesp':
                import receiver_assets
                combined=receiver_assets.merged(Path(data['folder']))
            else:
                combined=merged_image(Path(data['folder']))
            stage(root, data, 'writing', percent=0)
            # The 4 MB merged image resets stale configuration too. esptool's
            # normal MD5 verification covers the complete image before success.
            esptool.main(['--chip','esp32','--no-stub','--after','no_reset',
                          'write_flash','--flash_size','keep','0x0',str(combined)], esp=esp)
            data.update(stage='flashed', percent=100)
    finally:
        try:
            esp.hard_reset()
        finally:
            esp._port.close()


def worker(action):
    root=state_root()
    with job_lock(root):
        data=read_job(root)
    def interrupted(signum, frame):
        raise RuntimeError(tr('Installation was interrupted. The backup has been retained'))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGALRM, interrupted)
    signal.alarm(1200)
    try:
        operate(root, data, action)
        finish(root, data)
    except Exception as error:
        finish(root, data, error=error)
        raise
    finally:
        signal.alarm(0)


def launch(action):
    root=state_root()
    with job_lock(root):
        data=read_job(root)
    try:
        stage(root, data, 'tools')
        python=tool_python()
        if action == 'prepare' and data.get('flavor')!='wesp':
            stage(root, data, 'download')
            download_images(Path(data['folder']))
        # exec keeps PID/starttime stable for crash recovery polling.
        os.execv(str(python), [str(python), str(Path(__file__).resolve()), 'worker', action])
    except Exception as error:
        finish(root, data, error=error)
        raise


if __name__ == '__main__':
    os.umask(0o077)
    if sys.argv[1] == 'launch':
        launch(sys.argv[2])
    elif sys.argv[1] == 'worker':
        worker(sys.argv[2])
