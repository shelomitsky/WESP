# Credits and component boundaries

WESP — Chapman, 2026. See LICENSE (MIT).
Please credit Chapman when sharing derived builds, articles or screenshots.

The desktop code began as a local KDE/WLED integration and was prepared as an
independent source candidate. The Git source archive does not contain WLED firmware, Espressif SDK binaries,
a copied desktop theme or third-party graphics. An optional release bundle adds
compiled native WESP receiver images built with the pinned Espressif Arduino
framework; those images include upstream framework/SDK components under their
own licenses. The manifest identifies their toolchain and hashes. The firmware
build recipe and application sources are included in receiver/. See the
[Arduino-ESP32 source and licenses](https://github.com/espressif/arduino-esp32/tree/2.0.14)
and [ESP-IDF source and licenses](https://github.com/espressif/esp-idf/tree/v4.4.6).

WLED is a separate upstream project by Christian Schwinne and contributors.
Its v0.15.3 source declares EUPL v1.2 or later; that firmware is not relicensed
as MIT by this repository. [Upstream license for that tag](https://raw.githubusercontent.com/wled/WLED/v0.15.3/LICENSE).

NumPy, pyserial, Pillow, Python, Qt/KDE and the system DBus/GI/audio components are
external dependencies governed by their respective licenses. Installation uses
the user's system components; their code is not copied into this source archive.

Binary release bundles include upstream license copies in receiver-firmware/licenses/
and the pinned Arduino library sources with retained notices in
receiver-firmware/arduino-core-sources.tar.gz. Rebuild instructions are in
receiver-firmware/REBUILD.md; application source and the pinned build recipe are
included in the same release. The installer retains the license copies as well.
