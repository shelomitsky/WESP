# WESP

[GitHub repository](https://github.com/shelomitsky/WESP) ·
[CI runs](https://github.com/shelomitsky/WESP/actions)

Desktop ambient lighting for music, wallpapers and system events.
The first alpha supports Linux/KDE Plasma 6, existing WLED controllers and an experimental WESP USB/Wi-Fi receiver.
Support for other desktop environments is planned after the KDE alpha.

Author: **Chapman**. Licensed under MIT. Please credit Chapman when sharing
screenshots, builds or articles about this project; retain the copyright and
license notices when distributing its code.

**0.2.0-alpha.7: local release candidate.** Generalized device/layout support and
the new installer have automated checks. A fresh KDE session and physical LEDs
still need acceptance before a public release. This candidate does not replace
an existing installation automatically and has not been published.

[Русский быстрый старт](QUICKSTART.ru.md) · [Changes](CHANGELOG.md) ·
[Verification and remaining acceptance](RELEASE_CHECKLIST.md)

## Features

- Plasma controls for power, brightness, KDE accent sync and a music level meter.
- Select one USB WLED controller; identity is saved locally, never embedded.
- Add unequal sections with names, physical ranges, positions and directions.
- Adjustable decay (80–600 ms), fast audio capture request and adaptive gain.
- Adjustable attack, sensitivity and silence gate without resetting adaptive gain.
- Five fixed equalizer palettes and automatic colors from local KDE wallpapers.
- Notification choice: two whole-strip flashes, gentle pulse, constant tint or one pixel;
  five color presets, intensity and a temporary preview without fake notification IDs.
- Volume and notification indicators use the same physical layout.
- A compact main remote with separate Music / Signals / Strips settings pages.
- English and Russian UI/helper messages, selected from the desktop session language.
- Custom two-strip W icon with light/dark variants following the widget theme.
- Per-user install/upgrade, transaction backups, rollback and uninstall.

RGB only, 1–1024 pixels and up to 128 sections in the current implementation. Sections must not overlap;
unused pixels are black in desktop-driven frames. 60 FPS is a target for small
setups, not a guarantee for arbitrary lengths. The existing local installation
was physically checked on WLED 0.15.3; the generalized candidate needs its own
hardware acceptance. Positions are saved for future wallpaper mapping.

**Not implemented here:** spatial wallpaper-to-section mapping, Wi-Fi pixel transport,
custom receiver firmware. KDE accent color is a
separate existing mode. No screen recording or microphone capture is used.

## WESP receiver: USB setup, separate power and Wi-Fi

The experimental receiver firmware is separate from WLED. Keep an accepted WLED
board unchanged; select a separate classic 4 MB ESP32 for receiver testing.
Build it with `python3 build_native_receiver.py --output-dir /path/outside/source`.
The pinned PlatformIO build never opens a serial port. A desktop bundle can be
built by `build_release.build(output, receiver=assets_directory)`; compiled images
are checksum-verified optional release assets, never committed source binaries.

In **Device and strips**, choose **Install WESP firmware (USB + Wi-Fi)**,
wait for a complete backup and confirm replacement on the identified test board.
After installation choose **Read WESP receiver**, add physical outputs and set
GPIO, LED count, RGB color order and LED current limit. There are no default pins.
Enter the Wi-Fi network/password in the widget and save. Passwords are sent over
a private authenticated loopback bridge and USB, never shell arguments or logs.
Then **Check Wi-Fi** and **Use Wi-Fi** verify the same MAC and pairing key over
TCP. Only after that disconnect USB and power the board from a suitable separate
supply. Pairing credentials stay in a separate private desktop file. Stable
`wesp-<MAC suffix>.local` discovery has the paired IP as fallback.

The receiver has one firmware for USB and Wi-Fi: RGB frames and static colors are
computed on the PC. On boot, Off or loss of valid PC frames, outputs are black.
The internal 1.2-second watchdog reserves time for physical output within the
1.5-second acceptance target. Physical timing still needs measurement. WLED
effects/segments are not implemented by this receiver; the desktop adapter
provides a single static RGB segment for its own compositor.

This candidate requires real board, Wi-Fi and separate-power acceptance before
public release. Passing compilation or protocol tests is not that acceptance.

## First installation of WLED on a new ESP

In **Device and strips**, select the USB port and choose **Install WLED on a new ESP**.
The wizard creates a private esptool 4.11.0 environment, downloads checksum-pinned
official WLED 0.15.3 images, identifies the board and saves its complete flash.
Review the MAC and backup path, then confirm replacement of the firmware and all
settings on that ESP. Keep USB connected until writing and verification finish.
The widget then connects the flashed controller through normal enrollment.

Supported here: unencrypted classic ESP32 with exactly 4 MB flash. Other chips,
protected boards, incomplete backups, changed identities and a busy serial port
are rejected before writing. Existing GPIO/count settings are erased; configure
real LED outputs in WLED before connecting a strip. A board with no strip can
verify firmware/USB setup, but cannot verify physical lighting.

Internet access, Python venv/ensurepip and the `fuser` utility (psmisc) are needed
for this optional workflow. Tools and private firmware/backups are kept under
XDG_DATA_HOME and XDG_STATE_HOME; they are excluded from source archives.
Errors retain the backup and do not trigger automatic erase/retry. Interrupted
jobs are recovered when the widget next polls their state.

## Dependencies

Linux, KDE Plasma 6 / Qt6 / Kirigami / Plasma5Support, Python3.10+, NumPy,
pyserial, Pillow (distribution package usually `python3-pil`), dbus-python,
PyGObject/GLib, user systemd, parec and wpctl.
Python dependencies listed in requirements.txt do not install the desktop or
system GI/DBus libraries. No distribution package command is claimed tested yet.

```sh
/usr/bin/python3 manage.py doctor
/usr/bin/python3 manage.py install
```

The installer checks dependencies before changing files. `--no-start` stages
files without starting services, dependency preflight or hardware access.
A subsequent normal install activates a staged installation. Upgrades of an
already activated installation preserve intentionally inactive/disabled services.
Staging is intended for packaging/tests, not desktop acceptance.
Use the system interpreter above: installed launchers use `/usr/bin/python3`.
A virtual environment with the Python packages alone is not a desktop install.

Application files follow XDG_DATA_HOME, units XDG_CONFIG_HOME, backups
XDG_STATE_HOME. Configuration and runtime use the separate `wled-control-desktop`
namespace, so the legacy installation's settings, snapshots and socket are not
reused automatically. Launchers are in `~/.local/bin`. Add **WESP** from
Plasma's widget picker after installation. Existing legacy widget/service names
are separate; do not run two transports against the same UART. For migration,
stop the old installation's USB/equalizer services explicitly before enrollment.
Do not replace a physically accepted setup until its profile is recorded.

In the widget: click «Найти», explicitly select a USB port and connect it.
Enrollment sends WLED identity queries and may negotiate a temporary baud rate;
it does not flash firmware or change GPIO/LED count. A selected board can reset
briefly when its USB-UART opens. Serial permissions are managed by your OS;
do not grant global write access to all devices.

Create sections using the actual WLED global pixel count. The UI uses 1-based
start positions. Edit the whole scheme, then save it; validation is atomic.
Enable the equalizer and tune «Затухание». Higher values soften the falling edge
without slowing attack. Changing the controller disables the equalizer and
does not transfer saved effects to another board. It refuses while a previous
equalizer snapshot cannot be restored or a volume indicator is still active.

The generalization preserves the old DSP, but it is a new application namespace.
For a previous 10+10 setup create two sections and copy its chosen directions;
no personal device profile is shipped in this repository.
`examples/two-sides.json` is a geometry-only 10+10 example with opposite wiring
directions; it contains no controller identity. Adjust directions and placement
for the actual wiring, then use the widget or `layout` command after enrollment.

Enrollment is committed by the USB owner under the shared command lock.
An unavailable previous board does not by itself block an explicit selection;
the equalizer/volume restoration guards above still apply. If saving the new
selection fails, the previous selection and its saved documents are restored.

## Uninstall and rollback

Run from the retained source checkout:

```sh
python3 manage.py uninstall
python3 manage.py rollback /path/printed/by/installer
```

Caught file failures during removal or explicit rollback restore the previous
files, ownership manifest and service state from a transaction backup. Failed
service shutdown aborts before modifying application files.
Settings are retained. Owned files edited after installation block automatic
replacement/removal. Unrelated files are not removed. Keep this source checkout
until testing/rollback is finished. Service shutdown exits realtime; the
controller's ordinary WLED behavior may continue after uninstall.

## Development

```sh
python3 check_release.py
```

Requires the packages in requirements.txt, Node.js and GNU gettext (`msgfmt`).
Gettext tools are needed for development checks, not for installation or use.
This runs the unit suite, real socket client/service subprocess integration,
actual shell argument checks, source checks, two reproducible builds and a
cold-archive install/upgrade/rollback/uninstall in temporary HOME/XDG paths.
The IPC tests require permission to bind local AF_UNIX sockets; a restricted
sandbox that denies this must run the gate on an unrestricted host/runner.
There is no skip fallback. It does not contact a controller, the user bus or the audio server. It leaves
the normal artifact directory untouched. Build a distributable with
`python3 build_release.py` (writes `wesp-<version>.tar.gz` to the sibling
artifacts directory; extract it and open its `wesp/` folder).
Translation source/compiled catalog consistency and numbered placeholders are
checked too; see [adding a language](TRANSLATING.md).

## Language

The widget uses KDE's native gettext domain; helpers use the same catalog.
English is the source/fallback language and Russian is included. The language
follows the KDE session settings (`LANGUAGE` and message locale). A C/POSIX
locale uses English. After changing desktop language, log out and back in so
Plasma and user services receive the same language environment. Existing section
names are user data and are never translated or renamed. External driver/system
error details keep their original wording. Technical installer output is English.

Qt6 check: `qmllint plasma/org.wledcontrol.desktop/contents/ui/main.qml`
(your distribution may install qmllint outside PATH). Tests use isolated
HOME/XDG dirs and fake UART; the IPC service/client boundary is real. Hardware latency and Plasma
behavior are separate acceptance checks; see RELEASE_CHECKLIST.md.

The separate Qt CI job runs `python3 check_qml_setup.py -v` with PyQt6 6.10.2
and Qt 6.10.2. It exercises the shipped setup handler, input controls and Save
button in a headless Qt component against the real private HTTP bridge. It
checks form scope, deferred endpoint discovery, password clearing after success,
retry after failure and saving outputs without replacing saved Wi-Fi credentials.
These Python Qt bindings are development dependencies only.

## WLED

This is an independent desktop client. WLED firmware is not included or
relicensed by this project. [WLED](https://github.com/wled/WLED),
[official installer](https://install.wled.me/),
[serial protocol](https://kno.wled.ge/interfaces/serial/).

## Music tuning and notifications

The main remote keeps power, brightness, equalizer, sensitivity and decay.
«Настроить подсветку…» opens three pages: «Музыка», «Сигналы», «Ленты».
Attack («Зажигание») adds a gradual rise (0 = the existing fast attack,
20–300 ms in the UI); decay controls only the fall. Sensitivity is 50–200%
relative to the normalized level, so adaptive gain does not cancel it.
The silence gate is 0–3% of audio amplitude; raise it to reject weak noise.
The music page offers Classic (the existing colors), Fire, Ocean, Violet and
Rainbow palettes with a color preview. Changes apply to the next music frame
without restarting capture; section directions and the volume indicator keep
their existing behavior.

«Из обоев» extracts up to three dominant colors from the first screen (lowest
screen index) of the current KDE activity. Supported sources are `org.kde.image`
and `org.kde.potd` (Picture of the Day), using local image files/cache only.
Standard `org.kde.slideshow` reads the current slide from the running Plasma
shell's read-only DBus `wallpaper(uint)` method every two seconds, because the
saved Image entry can be absent or stale. It follows the shown slide rather
than picking a file from SlidePaths. A missing API/session/current slide is
reported with a Classic fallback; stale saved slides are never substituted.
When the activity service is unavailable the first configured desktop is used.
It checks for changes every two seconds and decodes a 64×64 sample only when
the image changes. Sampling runs in the accent service; music reads only the
prepared palette, without restarting capture. The widget previews the colors
and reports unsupported/missing images with a Classic fallback. Video/custom
wallpaper plugins and independent palettes per monitor are not
supported yet. Uniform gray/black wallpapers keep neutral colors; very dark
tones are lifted enough to remain visible. Existing master brightness applies.

Signals can use two smooth flashes (the default), an ongoing gentle pulse,
a constant tint, or a single marker pixel. Color and strength are configurable.
The full-strip effects affect configured sections only and respect the master
brightness, off/sleep and volume priority. Music frames keep rendering under
notification color; native WLED effects are restored after a temporary idle overlay.
Closely spaced arrivals share the current animation instead of holding it at zero.

Notification IDs are active DBus notifications, not KDE's unread-history database.
Closing the last active notification or «Сбросить» removes its persistent effect.
«Проверить эффект» previews the selected style for at most three seconds without
creating a fake counter or waking an off device. Two flashes finish in 1.6 seconds;
the persistent styles run while an active notification remains.

After upgrading an existing installation, reload the Plasma widget (for example
`systemctl --user restart plasma-plasmashell.service`). Desktop services are
managed by the installer; keep its printed backup path for rollback.
