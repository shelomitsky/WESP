#!/usr/bin/env python3
"""Build the ESP32 receiver without opening a serial port or flashing hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def build(output: Path, pio: str) -> Path:
    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Build output must be outside the source worktree")
    output.mkdir(parents=True, exist_ok=True)
    work = output / "platformio"
    # All generated files (including dependency metadata) remain outside Git.
    project = work / "project"
    project.mkdir(parents=True, exist_ok=True)
    for name in ("src", "include"):
        shutil.copytree(ROOT / "receiver" / name, project / name, dirs_exist_ok=True)
    shutil.copyfile(ROOT / "receiver/platformio.ini", project / "platformio.ini")
    log = output / "build.log"
    core_dir = work / "core"
    cache = Path.home() / ".platformio"
    # Cached tools stay read-only; manager locks/cache live under output-dir.
    for kind in ("platforms", "packages"):
        destination = core_dir / kind
        destination.mkdir(parents=True, exist_ok=True)
        if (cache / kind).is_dir():
            for source in (cache / kind).iterdir():
                link = destination / source.name
                if source.is_dir() and not link.exists():
                    link.symlink_to(source, target_is_directory=True)
    environment = {**os.environ, "PLATFORMIO_BUILD_DIR": str(work / "build"),
                   "PLATFORMIO_LIBDEPS_DIR": str(work / "libdeps"),
                   "PLATFORMIO_CORE_DIR": str(core_dir), "PLATFORMIO_SETTING_ENABLE_TELEMETRY": "no"}
    with log.open("w") as handle:
        result = subprocess.run([pio, "run", "--project-dir", str(project)],
                                env=environment, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"PlatformIO failed; see {log}")
    assets = output / "receiver-firmware"
    assets.mkdir(exist_ok=True)
    compiled = work / "build/esp32"
    framework = core_dir / "packages/framework-arduinoespressif32@3.20014.231204"
    boot_app = framework / "tools/partitions/boot_app0.bin"
    if not boot_app.exists():
        framework = core_dir / "packages/framework-arduinoespressif32"
        boot_app = framework / "tools/partitions/boot_app0.bin"
    sources = [("bootloader.bin", 0x1000, compiled / "bootloader.bin"),
               ("partitions.bin", 0x8000, compiled / "partitions.bin"),
               ("boot_app0.bin", 0xE000, boot_app),
               ("firmware.bin", 0x10000, compiled / "firmware.bin")]
    files = []
    for name, offset, source in sources:
        destination = assets / name
        shutil.copyfile(source, destination)
        data = destination.read_bytes()
        files.append({"file": name, "offset": offset, "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"firmware": "WESP", "version": "0.2.1", "proto": 1,
                "chip": "esp32", "flash_size": 4194304, "flash_mode": "dio",
                "flash_freq": "40m", "platform": "espressif32@6.5.0",
                "framework": "arduinoespressif32@3.20014.231204", "images": files}
    manifest['elf_sha256']=hashlib.sha256((compiled/'firmware.elf').read_bytes()).hexdigest()
    import receiver_sources
    receiver_sources.bundle(framework,assets)
    path = assets / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--pio", default=shutil.which("pio") or str(Path.home()/".local/bin/pio"))
    args = parser.parse_args()
    try:
        print(build(args.output_dir, args.pio))
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
