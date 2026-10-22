# Credits and component boundaries

WESP — Chapman, 2026. See LICENSE (MIT).
Please credit Chapman when sharing derived builds, articles or screenshots.

The desktop code began as a local KDE/WLED integration and was prepared as an
independent source candidate. This release does not contain WLED firmware,
Espressif SDK binaries, a copied desktop theme or third-party graphics.

WLED is a separate upstream project by Christian Schwinne and contributors.
Its v0.15.3 source declares EUPL v1.2 or later; that firmware is not relicensed
as MIT by this repository. [Upstream license for that tag](https://raw.githubusercontent.com/wled/WLED/v0.15.3/LICENSE).

NumPy, pyserial, Pillow, Python, Qt/KDE and the system DBus/GI/audio components are
external dependencies governed by their respective licenses. Installation uses
the user's system components; their code is not copied into this source archive.
