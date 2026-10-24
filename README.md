# WESP

[GitHub repository](https://github.com/shelomitsky/WESP) ·
[CI runs](https://github.com/shelomitsky/WESP/actions)

Desktop ambient lighting for music, wallpapers and system events.
The first alpha supports Linux/KDE Plasma 6, existing WLED controllers and an experimental WESP USB/Wi-Fi receiver.
Support for other desktop environments is planned after the KDE alpha.

Author: **Chapman**. Licensed under MIT. Please credit Chapman when sharing
screenshots, builds or articles about this project; retain the copyright and
license notices when distributing its code.

**0.2.0-alpha.16 — cleanup candidate.** Try the music demo without hardware,
then connect one ESP for desktop music, accent lighting and temporary signals.
Native WESP0.2.1 runs the effects locally over USB or Wi-Fi, supports paired
configuration/presets and OTA, and rejects stale music instead of replaying it.
The standalone window renders a smooth calculated music preview locally;
opening it does not add audio capture or ESP frame requests for that preview.

The tested desktop is Ubuntu26.04.1/KDE Plasma6.6 with a classic ESP32 and two
RGB strips. This is an experimental alpha with a narrow support matrix, not a
claim of compatibility with every board or desktop. See [first-alpha notes](FIRST_ALPHA.md)
for verified paths and known limitations. Install and firmware replacement are
explicit user actions; an existing controller is never flashed automatically.

[Русский быстрый старт](QUICKSTART.ru.md) · [Changes](CHANGELOG.md) ·
[Verification and remaining acceptance](RELEASE_CHECKLIST.md)

Experimental native0.2.1 adds a separate fast music data path: fixed40-byte
HMAC-authenticated UDP messages with fixed-point RMS/bass and sample time. Changes
are sent up to100Hz; identical levels/silence refresh every400ms. Old/reordered
samples are discarded instead of replayed. The desktop capture continuously drains
into one2048-sample window; short-window RMS observes the latest10ms. Paired TCP
still handles settings, events, power and OTA. Old native firmware and USB keep
the existing feature/frame fallback. Physical latency results belong in the
release checklist; software timer values alone are not an acoustic measurement.

## Standalone application

Open **WESP** from the application menu, or run `wesp` after installation.
The window contains the live strip preview, music tuning, signals, section
editor and the existing firmware/receiver setup. The Plasma widget remains an
optional quick remote; **Open WESP** activates the same single application window.
Closing the window leaves the desktop services running.

**Try without an ESP** listens to the computer's audio output and uses the same
desktop music analysis and section renderer. Native ESP rendering is checked
with the C++ software bench; the device window uses a calculated local music
preview, with actual ESP frames as a slower fallback outside that path.
Its power, brightness and tuning are
temporary and isolated from a real controller, including one already running.
It never opens a device or changes the saved controller, network or pairing.
The demo ends when the window closes. There is no microphone or screen capture.

During native Wi-Fi music, device preview reuses the demo renderer with the
same RMS/bass already captured for the ESP. Only the open window renders it;
there is no second capture, FFT or extra ESP traffic. Other modes use the latest
host frame or an on-demand ESP frame, separately from connection state. It is not an optical/current measurement. Initial standalone
support is still Linux/KDE Plasma 6; moving the UI out of Plasma does not make
the KDE integrations available on other desktops automatically.

The GUI requires PySide6/Qt Quick in addition to the service dependencies below.
Use your distribution's PySide6 QtCore/QtGui/QtQml/QtQuick/QtQuickControls2/QtNetwork
packages, or a private user environment:

```sh
python3 -m venv --system-site-packages "${XDG_DATA_HOME:-$HOME/.local/share}/wled-control-tools/desktop-qt6"
"${XDG_DATA_HOME:-$HOME/.local/share}/wled-control-tools/desktop-qt6/bin/python" -m pip install -r requirements-gui.txt
python3 manage.py doctor
python3 manage.py install
```

The launcher automatically uses that private GUI interpreter when system Python
does not provide PySide6. The service interpreter remains `/usr/bin/python3`.
PySide6 is a separate upstream dependency; WESP's MIT license covers its own code.
No package manager or elevated privileges are invoked by the application itself.
The Strips page offers bounded direction and RGB checks.

### Music scenes

Choose **Music** or **Calm light** as the base scene; choosing a scene never
turns on an off device. Music offers the original **Level meter** and **Pulse**:
a shorter steady bar with a shared smooth accent on low-frequency attacks.
It does not estimate BPM, strobe or scatter random pixels. Both demo and device
use the same analyzer/renderer, including section direction and unassigned gaps.

**Soft** and **Vivid** tune sensitivity/gate/attack/decay together. **My tuning**
restores the manual set saved before a preset; editing a tuning slider creates
a new manual set. Palette, master brightness, hardware and networking are not
part of these presets. The original meter remains the default.

The overview names the active base or temporary signal. Selecting Calm light
during the volume indicator returns to the current desktop accent after the
indicator expires, without replaying an old pre-music snapshot. Calm currently
uses the KDE accent; spatial wallpapers and automatic idle scenes are separate work.
Pulse and meter remain experimental. The owner accepted beat alignment on
Another One Bites the Dust; this is not an instrumented latency measurement.

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

**Not implemented here:** spatial wallpaper-to-section mapping and WLED DDP transport.
The experimental WESP receiver already supports its own USB/Wi-Fi transport.
KDE accent color is a
separate existing mode. No screen recording or microphone capture is used.

## WESP receiver: USB setup, separate power and Wi-Fi

The experimental receiver firmware is separate from WLED. Keep an accepted WLED
board unchanged; select a separate classic 4 MB ESP32 for receiver testing.
Build it with `python3 build_native_receiver.py --output-dir /path/outside/source`.
The pinned PlatformIO build never opens a serial port. A desktop bundle can be
built by `build_release.build(output, receiver=assets_directory)`; compiled images
are checksum-verified optional release assets, never committed source binaries.

In the standalone application's **Connection** page choose **Set up a new ESP**,
then **Prepare WESP firmware**. Wait for a complete backup and confirm replacement
on the identified test board. **Finish installation** reads settings from that
exact board; a failed read has a separate retry. Choose GPIO, LED count, RGB order
and current budget, enter the network/password, then save. GPIOs are never guessed.
Network credentials travel over the private local bridge and USB, never shell
arguments or logs. Save turns the outputs off; it does not start a light test.

On **Strips**, turn lighting on when ready and check each saved section's direction
or RGB colors. Checks are dim and finite (at most five seconds); other sections
are black. Stop and Off cancel the test, and Off never gets undone by restoration.
The same controls work virtually in demo mode without contacting any board.

**Check Wi-Fi**, then **Use Wi-Fi** verify the same MAC and pairing key over TCP.
After verification, move the ESP to a suitable separate supply and check connection
again. Pairing credentials stay in a separate private desktop file. Stable
`wesp-<MAC suffix>.local` discovery has the paired IP as fallback.

For a paired native receiver with firmware **0.1.2**, **Read ESP settings** works
over Wi-Fi without a selected USB port. Change GPIOs, counts, color order or current
budget, then **Save LED outputs over Wi-Fi**. A separate read confirms exactly
what the ESP saved before the desktop commits its state. Changing the Wi-Fi network
and first pairing still require USB. Existing 0.1.1 boards need a one-time firmware
update over USB; the app explains this instead of enabling an unsupported save.

The receiver has one firmware for USB and Wi-Fi: RGB frames and static colors are
computed on the PC. Firmware 0.1.1 adds one dim amber runner on configured outputs
at startup and a green runner when a new WESP session is accepted. Each pass is
700 ms; status polling does not repeat it. After these bounded signals, outputs
stay black without valid PC frames. Off immediately cancels both the current
signal and any queued signal.
The internal 1.2-second watchdog reserves time for physical output within the
1.5-second acceptance target. Physical timing still needs measurement. WLED
effects/segments are not implemented by this receiver; the desktop adapter
provides a single static RGB segment for its own compositor.

This candidate requires real board, Wi-Fi and separate-power acceptance before
public release. Passing compilation or protocol tests is not that acceptance.

## Existing WLED controllers

WESP connects to already configured WLED controllers over USB. WLED firmware
installation is not part of WESP; use the [official WLED installer](https://install.wled.me/)
if a board needs WLED. The built-in backed-up installer is only for WESP firmware.
Existing WLED identity/count checks, enrollment and USB frame transport are retained.

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

## Native music, presets and OTA (receiver0.2.0)

On a native receiver0.2.0, WESP transmits unsmoothed RMS/bass instead of computing
individual music pixels. The ESP handles adaptive gain, gate, attack/decay,
meter/Pulse, repeated impulses on steady sound, and finite signal animations.
Audio continues during notification/volume overlays; completion reveals current
music. Off cancels all animation. A music/frame lease still expires at1200ms.

Music controls and named presets are transferred over the selected paired USB or
Wi-Fi route and confirmed by a separate read-back. There are three built-in
configuration slots and five custom presets in this candidate. Presets contain
tuning, palette and effect parameters; no controller identity or network secrets.
The independent NVS effect key does not change the hardware/network config blob.

For static desktop/wallpaper lighting, a changed color is sent once. Confirmations
use7/8 of the configured connection timeout, measured from send time:8s means7s.
The separate fade duration begins after expiry. Status and preview reads, effect
configuration and event animation do not renew the base lease. Closing WESP's
window stops preview requests while desktop services continue.

In Connection, switch the paired receiver to Wi-Fi and use **Update firmware over
Wi-Fi**. The update stops strip calibration, leaves output off, verifies the image
and writes the inactive app slot. After reboot, WESP requires the exact build,
preserved output/effect configuration and a trial boot before confirming it.
An unconfirmed candidate rolls back after60s. Transfer interruption does not select
an incomplete image. Physical rollover/recovery acceptance is recorded separately
in RELEASE_CHECKLIST.md; builds and tests alone do not establish that acceptance.
The native local-network transport uses the existing pairing token and is not
encrypted; no OTA endpoint is exposed to the internet by WESP.

### Software bench (development)

The bench needs g++ with C++11 and Python. It compiles the same receiver_core.h
and effects_engine.h used on the board into a private temporary library; it never
opens USB, Wi-Fi or audio. Production WESP does not require a C++ compiler.

```
python3 -m unittest discover -s tests -p test_native_bench.py -v
python3 native_sim.py --count 20 < timeline.jsonl
```

JSON-line operations are configure(effects), power(on), audio(rms,bass),
event(kind,ref,value), solid(color), heartbeat and frame. at is a monotonic uint32
millisecond timestamp supplied by the timeline. Replies contain the result or a
fixed input error. This makes deterministic sound/event/timeout tests possible
before hardware testing.
