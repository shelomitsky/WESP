#!/usr/bin/env python3
"""Check source, tests and a cold source-archive installation without hardware."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile

import build_release

ROOT=Path(__file__).resolve().parent


def run(*args,env=None):
    subprocess.run(list(args),cwd=ROOT,env=env,check=True,timeout=180)


def archive_smoke():
    with tempfile.TemporaryDirectory(prefix='wled-release-') as directory:
        temporary=Path(directory)
        archive=build_release.build(temporary/'first')
        repeat=build_release.build(temporary/'repeat')
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest!=hashlib.sha256(repeat.read_bytes()).hexdigest():
            raise ValueError('Source archives are not reproducible')
        expected=archive.with_suffix(archive.suffix+'.sha256').read_text().split()
        if expected!=[digest,archive.name]:
            raise ValueError('Archive checksum does not match')
        extracted=temporary/'extracted'
        with tarfile.open(archive) as package:
            names=set()
            for member in package.getmembers():
                path=PurePosixPath(member.name)
                if (not member.isfile() or path.is_absolute() or '..' in path.parts
                        or path.parts[0]!='wesp' or member.name in names):
                    raise ValueError('Unsafe or duplicate archive entry: '+member.name)
                names.add(member.name)
                target=extracted.joinpath(*path.parts)
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(package.extractfile(member).read())
        source=extracted/'wesp'
        hashes=json.loads((source/'SOURCE_SHA256.json').read_text())
        actual={str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()}
        if actual!=set(hashes)|{'SOURCE_SHA256.json'}:
            raise ValueError('Archive manifest file set does not match')
        for name,expected in hashes.items():
            if hashlib.sha256((source/name).read_bytes()).hexdigest()!=expected:
                raise ValueError('Source checksum mismatch: '+name)
        home=temporary/'fresh home'
        home.mkdir()
        env=dict(os.environ,HOME=str(home),XDG_DATA_HOME=str(home/'data'),
                 XDG_CONFIG_HOME=str(home/'config'),XDG_STATE_HOME=str(home/'state'),
                 XDG_CACHE_HOME=str(home/'cache'),XDG_RUNTIME_DIR=str(home/'runtime'),
                 WLED_CONFIG_DIR=str(home/'config/wled-control-desktop'),
                 WLED_RUNTIME_DIR=str(home/'runtime/wled-control-desktop'))
        # Do not carry an HTTP test override into a desktop configuration probe.
        env.pop('WLED_TRANSPORT',None)
        manager=[sys.executable,str(source/'manage.py')]
        run(*manager,'install','--no-start',env=env)
        settings=home/'config/wled-control-desktop/settings.json'
        settings.parent.mkdir(parents=True,exist_ok=True)
        preserved=b'{"equalizer_decay_ms":320,"equalizer_palette":"ocean"}\n'
        settings.write_bytes(preserved)
        install=subprocess.run([*manager,'install','--no-start'],env=env,cwd=ROOT,
                               check=True,capture_output=True,text=True,timeout=30)
        backup=install.stdout.strip().removeprefix('Backup: ')
        if Path(backup).parent!=(home/'state/wled-control-desktop/backups'):
            raise ValueError('Installer did not return a local backup path')
        run(*manager,'rollback',backup,'--no-start',env=env)
        probe=subprocess.run([sys.executable,str(home/'.local/bin/wled-control'),'config'],
                             env=env,check=True,capture_output=True,text=True,timeout=10)
        config=json.loads(probe.stdout)
        if config['settings']['equalizer_palette']!='ocean':
            raise ValueError('Installed launcher lost user settings')
        run(*manager,'uninstall','--no-start',env=env)
        if settings.read_bytes()!=preserved or (home/'.local/bin/wled-control').exists():
            raise ValueError('Uninstall did not remove owned files while retaining settings')
    print('PASS: reproducible archive, hashes, cold install/upgrade/rollback/uninstall and retained settings',flush=True)


def main():
    try:
        run(sys.executable,'check_translations.py')
        run(sys.executable,'-m','unittest','discover','-s','tests','-q')
        run('node','tests/test_queue.js')
        archive_smoke()
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('Release check failed:',error,file=sys.stderr)
        return 1
    print('Local release checks passed. Real KDE, UART and physical acceptance remain separate.',flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
