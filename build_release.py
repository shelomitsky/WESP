#!/usr/bin/env python3
"""Build a source-only candidate archive from a bounded file set."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import verify_release


def build(directory=None,receiver=None):
    root=Path(__file__).resolve().parent
    if verify_release.main():
        raise ValueError('Source checks failed')
    files=list(root.glob('*.py'))+list(root.glob('*.md'))
    files += [root/'LICENSE',root/'requirements.txt',root/'requirements-gui.txt',root/'.gitignore']
    files += list((root/'app').glob('*.qml'))
    files += list((root/'tests').glob('*.py'))+list((root/'tests').glob('*.js'))
    files += [p for p in (root/'plasma').rglob('*') if p.is_file()]
    files += list((root/'.github/workflows').glob('*.yml'))
    files += list((root/'examples').glob('*.json'))
    files += [p for p in (root/'locale').rglob('*') if p.is_file()]
    files += [p for p in (root/'receiver').rglob('*') if p.is_file()]
    entries={}
    for file in sorted(set(files)):
        if file.is_symlink():
            raise ValueError('Symlink in source package: '+str(file.relative_to(root)))
        entries[str(file.relative_to(root))]=file.read_bytes()
    if receiver is not None:
        import receiver_assets
        receiver=Path(receiver)
        receiver_assets.validated(receiver)
        for name in ['manifest.json',*receiver_assets.OFFSETS]:
            entries['receiver-firmware/'+name]=(receiver/name).read_bytes()
    hashes={name:hashlib.sha256(data).hexdigest() for name,data in entries.items()}
    entries['SOURCE_SHA256.json']=json.dumps(hashes,sort_keys=True,indent=2).encode()+b'\n'
    directory=Path(directory) if directory is not None else root.parent/'artifacts'
    directory.mkdir(parents=True,exist_ok=True)
    version=json.loads((root/'plasma/org.wledcontrol.desktop/metadata.json').read_text())['KPlugin']['Version']
    target=directory/f'wesp-{version}.tar.gz'
    with target.open('wb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as compressed:
            with tarfile.open(fileobj=compressed,mode='w') as archive:
                for name,data in sorted(entries.items()):
                    item=tarfile.TarInfo('wesp/'+name)
                    item.size=len(data)
                    item.mode=0o644
                    item.mtime=0
                    archive.addfile(item,io.BytesIO(data))
    target.with_suffix(target.suffix+'.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+target.name+'\n')
    print(target)
    return target


if __name__=='__main__':
    build()
