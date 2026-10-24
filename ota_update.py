"""Owner-only paired Wi-Fi application updates. Never flashes bootloader or NVS."""
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time

import control
import manage
import receiver_assets

ACTIVE={'queued','uploading','restarting'}


def path():return control.RUNTIME/'ota-status.json'


def status():
    result=control.read_json(path(),{'stage':'idle'})
    if result.get('stage') in ACTIVE and time.time()-result.get('updated',0)>120:
        result.update(stage='failed',error='OTA worker stopped; check receiver connection')
    return result


def save(data,stage,**fields):
    data.update(stage=stage,updated=time.time(),**fields)
    manage.atomic_write(path(),json.dumps(data).encode(),0o600)


def start():
    with control.locked('ota'):
        if status().get('stage') in ACTIVE:raise ValueError('An ESP update is already running')
        selected=control.settings().get('controller') or {}
        if selected.get('backend')!='wesp' or selected.get('connection')!='wifi':raise ValueError('Connect the paired WESP receiver over Wi-Fi first')
        receiver_assets.validated(Path(__file__).with_name('receiver-firmware'))
        data=dict(id=secrets.token_hex(8),mac=selected['mac'],percent=0)
        save(data,'queued')
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',data['id']],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        return data


def perform(device,job_id):
    data=status()
    if data.get('id')!=job_id or data.get('mac')!=device.expected_mac or data.get('stage')!='queued':
        raise ValueError('The OTA target changed')
    if device.connection!='wifi':raise ValueError('OTA requires the paired Wi-Fi connection')
    assets=Path(__file__).with_name('receiver-firmware');manifest=receiver_assets.validated(assets)
    if not isinstance(manifest.get('elf_sha256'),str) or len(manifest['elf_sha256'])!=64:raise ValueError('Missing application build identity')
    previous=device.setup_status()
    if not previous.get('capabilities',{}).get('ota'):raise ValueError('Update ESP firmware over USB once to enable OTA')
    try:
        save(data,'uploading',percent=0)
        device.ota_upload((assets/'firmware.bin').read_bytes(),lambda p:save(data,'uploading',percent=p))
        save(data,'restarting',percent=100)
        deadline=time.monotonic()+35;info=None
        while time.monotonic()<deadline:
            time.sleep(.5)
            try:
                info=device.setup_status()
                if (info.get('build_sha256')==manifest['elf_sha256'] and info.get('version')==manifest['version']
                        and info.get('ota_trial') is True):break
                device._disconnect()
                info=None
            except (OSError,ValueError,TimeoutError):pass
        if not info or info.get('build_sha256')!=manifest['elf_sha256'] or info.get('version')!=manifest['version']:
            raise ValueError('The expected firmware did not reconnect')
        if info.get('outputs')!=previous.get('outputs') or info.get('count')!=previous.get('count'):
            raise ValueError('Output settings changed after OTA')
        if previous.get('effects') is not None and info.get('effects')!=previous['effects']:
            raise ValueError('Saved effects changed after OTA')
        device._run('ota_confirm')
        info=device.setup_status()
        if info.get('ota_trial') is not False:raise ValueError('OTA confirmation was not acknowledged')
        save(data,'complete',version=info['version'],build_sha256=info['build_sha256'])
        return True
    except Exception:
        save(data,'failed',error='Firmware update could not be confirmed. Check connection; lighting remains off.')
        raise


def worker(job_id):
    data=status()
    if data.get('id')!=job_id:return
    try:
        import usb_transport
        with control.locked():
            prefs,memory=control.settings(),control.runtime()
            if memory.get('firstLight'):
                control.end_first_light(prefs,memory,resume=False)
                control.write_json(control.RUNTIME/'state.json',memory)
            result=usb_transport.client(native={'action':'ota','id':job_id})
            if result is not True:raise ValueError('OTA owner refused the update')
    except Exception:
        current=status()
        if current.get('id')==job_id:
            save(current,'failed',error='Firmware update could not be confirmed. Check connection; lighting remains off.')


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--worker':worker(sys.argv[2])
    else:raise SystemExit('Use the WESP application to start an OTA update')
