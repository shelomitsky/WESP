"""Validate an optional compiled receiver bundle without changing a device."""
import hashlib
import json
from pathlib import Path
import shutil

FLASH_SIZE=4194304
OFFSETS={'bootloader.bin':0x1000,'partitions.bin':0x8000,
         'boot_app0.bin':0xe000,'firmware.bin':0x10000}


def validated(folder):
    folder=Path(folder)
    manifest=json.loads((folder/'manifest.json').read_text())
    if (manifest.get('firmware')!='WESP' or manifest.get('chip')!='esp32'
            or manifest.get('flash_size')!=FLASH_SIZE):
        raise ValueError('Unsupported WESP receiver bundle')
    entries=manifest.get('images',[])
    if not isinstance(entries,list) or len(entries)!=4:
        raise ValueError('Incomplete WESP receiver bundle')
    seen=set()
    end=0
    for item in sorted(entries,key=lambda x:x['offset']):
        name=item['file']
        if name not in OFFSETS or name in seen or item['offset']!=OFFSETS[name]:
            raise ValueError('Invalid WESP image offset')
        seen.add(name)
        path=folder/name
        if path.is_symlink():
            raise ValueError('Unsafe WESP firmware file')
        data=path.read_bytes()
        if (len(data)!=item['size'] or hashlib.sha256(data).hexdigest()!=item['sha256']
                or item['offset']<end or item['offset']+len(data)>FLASH_SIZE):
            raise ValueError('WESP image verification failed')
        end=item['offset']+len(data)
    return manifest


def stage(source,target):
    manifest=validated(source)
    target=Path(target)
    for name in ['manifest.json',*OFFSETS]:
        shutil.copyfile(Path(source)/name,target/name)
    validated(target)
    return manifest


def merged(folder):
    manifest=validated(folder)
    image=bytearray(b'\xff'*FLASH_SIZE)
    for item in manifest['images']:
        blob=(Path(folder)/item['file']).read_bytes()
        image[item['offset']:item['offset']+len(blob)]=blob
    path=Path(folder)/'combined-receiver.bin'
    path.write_bytes(image)
    return path
