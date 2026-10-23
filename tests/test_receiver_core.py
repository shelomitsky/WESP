"""Compile and execute the same safety core used by the ESP32 firmware."""
import pathlib
import os
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReceiverCoreTest(unittest.TestCase):
    def test_builder_finds_boot_app_in_actual_core_with_clean_home(self):
        spec = importlib.util.spec_from_file_location("receiver_build", ROOT / "build_native_receiver.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory(prefix="wesp-build-test-") as directory:
            directory = pathlib.Path(directory)
            home = directory / "empty-home"
            home.mkdir()
            output = directory / "output"

            def fake_pio(command, env, **kwargs):
                self.assertEqual(command[0], "test-pio")
                compiled = pathlib.Path(env["PLATFORMIO_BUILD_DIR"]) / "esp32"
                compiled.mkdir(parents=True)
                for name in ("bootloader.bin", "partitions.bin", "firmware.bin"):
                    (compiled / name).write_bytes(name.encode())
                boot = pathlib.Path(env["PLATFORMIO_CORE_DIR"]) / "packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin"
                boot.parent.mkdir(parents=True)
                boot.write_bytes(b"newly-installed-boot-app")
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(builder.Path, "home", return_value=home), mock.patch.object(builder.subprocess, "run", side_effect=fake_pio):
                manifest_path = builder.build(output, "test-pio")
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual([image["offset"] for image in manifest["images"]],
                             [0x1000, 0x8000, 0xE000, 0x10000])
            for image in manifest["images"]:
                data = (manifest_path.parent / image["file"]).read_bytes()
                self.assertEqual(image["size"], len(data))
                self.assertEqual(image["sha256"], hashlib.sha256(data).hexdigest())

    def test_native_safety_contract(self):
        with tempfile.TemporaryDirectory(prefix="wesp-core-") as directory:
            executable = pathlib.Path(directory) / "core-test"
            result = subprocess.run([
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                "-I", str(ROOT / "receiver/include"),
                str(ROOT / "receiver/tests/core_test.cpp"), "-o", str(executable),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
