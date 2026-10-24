"""Deterministic license and Arduino library-source materials for binary releases."""
import gzip
import io
import json
from pathlib import Path
import tarfile

LICENSES=('Arduino-ESP32-LGPL-2.1.txt','ESP-IDF-Apache-2.0.txt','cJSON-MIT.txt')
FILES=tuple('licenses/'+name for name in LICENSES)+('arduino-core-sources.tar.gz','REBUILD.md')

REBUILD='''# Native receiver library sources and rebuild

The application source is in ../receiver/ with build_native_receiver.py in the
release root. Arduino-ESP32 2.0.14 library sources, examples, variants and package
metadata from framework-arduinoespressif32@3.20014.231204 are provided in
arduino-core-sources.tar.gz. Its included source headers and component license
files retain their original notices. Copies of LGPL2.1, Apache2.0 and the cJSON
MIT notice are in licenses/. WESP's own MIT license does not replace these.

Install PlatformIO6.1.18, then run from the release's wesp directory:

    python3 build_native_receiver.py --output-dir ../receiver-build

This uses the exact platform/framework versions pinned in receiver/platformio.ini.
To rebuild with a modified Arduino library, first perform the build above.
Extract arduino-core-sources.tar.gz and replace the matching cores/libraries/
variants files in the framework package referenced by receiver-build/platformio/
core/packages/ (it may be a link to the shared installed package). Edit that
actual package, not an unrelated global copy. Remove only the generated
receiver-build/platformio/build object directory, then repeat the SAME command
with the SAME output directory. A different output may download an unmodified
framework instead. The application and Arduino libraries are recompiled from
source; no proprietary application object is required. Keep the
unchanged SDK/tools supplied with the pinned framework package. Its Apache-licensed
ESP-IDF source is available at https://github.com/espressif/esp-idf/tree/v4.4.6;
Arduino upstream source is https://github.com/espressif/arduino-esp32/tree/2.0.14.

Do not flash during a rebuild check. An actual update is a separate explicit
operation and must preserve the selected board, output configuration and rollback.
'''


def bundle(framework,assets):
    framework,assets=Path(framework),Path(assets)
    if json.loads((framework/'package.json').read_text()).get('version')!='3.20014.231204':
        raise ValueError('Unexpected Arduino library source version')
    entries={}
    for directory in ('cores','libraries','variants'):
        found=sorted(p for p in (framework/directory).rglob('*') if p.is_file())
        if not found:raise ValueError('Incomplete Arduino library sources')
        for path in found:
            if path.is_symlink():raise ValueError('Symlink in Arduino source materials')
            entries[str(path.relative_to(framework))]=path.read_bytes()
    for name in ('package.json','boards.txt','platform.txt','programmers.txt'):
        if (framework/name).is_file():entries[name]=(framework/name).read_bytes()
    licenses=Path(__file__).resolve().parent/'receiver/licenses'
    for name in LICENSES:entries['licenses/'+name]=(licenses/name).read_bytes()
    output=io.BytesIO()
    with gzip.GzipFile(filename='',mode='wb',fileobj=output,mtime=0) as compressed:
        with tarfile.open(fileobj=compressed,mode='w') as archive:
            for name,data in sorted(entries.items()):
                item=tarfile.TarInfo('arduino-esp32-2.0.14/'+name);item.size=len(data);item.mode=0o644;item.mtime=0
                archive.addfile(item,io.BytesIO(data))
    assets.mkdir(parents=True,exist_ok=True)
    (assets/'arduino-core-sources.tar.gz').write_bytes(output.getvalue())
    (assets/'REBUILD.md').write_text(REBUILD)
    (assets/'licenses').mkdir(exist_ok=True)
    for name in LICENSES:(assets/'licenses'/name).write_bytes((licenses/name).read_bytes())


def release_files(assets):
    assets=Path(assets)
    for name in FILES:
        path=assets/name
        if not path.is_file() or path.is_symlink():raise ValueError('Missing receiver source/license/rebuild material: '+name)
    return FILES
