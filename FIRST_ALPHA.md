# First alpha — 0.2.0-alpha.15

WESP turns desktop audio, wallpaper/accent colours and system events into
workplace lighting. Start with **Try without an ESP**; it does not configure or
send commands to a real controller. The standalone window is the main interface,
with an optional Plasma quick-control widget.

## What to try

- Level meter or Pulse, Soft/Vivid/manual tuning, colour palettes and five named
  user presets. Audio is the computer's output, never the microphone.
- A classic ESP32 running WESP0.2.1: configure it over USB once, then send music,
  settings and finite signals over Wi-Fi while powering it from a separate supply.
- Guided short direction/RGB checks for each strip, explicit Off and fail-dark
  on lost input. Firmware replacement always requires a selected board and consent.
- OTA into an inactive app slot, verified build, confirmation and rollback;
  output settings and presets are retained.
- Existing WLED over USB keeps its separate frame-based transport.

Native music uses40-byte authenticated datagrams, up to100Hz for changing input
and400ms refresh for unchanged levels. The ESP renders locally and discards late
or reordered input. The window's music preview uses the existing local renderer
and the same captured levels without a second capture, FFT or extra ESP queries.
Calculated preview is not proof of packet delivery, optical colour or power draw.

## Verified scope

- Automated: Python3.10/3.12/3.14 on Ubuntu24.04 CI, actual Qt setup/desktop,
  native C++ policy/renderer tests, real local IPC with fake UART, reproducible
  archives and isolated-HOME install/upgrade/rollback/uninstall.
- Desktop used for hardware acceptance: Ubuntu26.04.1 LTS, Plasma6.6.6,
  Python3.14.4, PySide6/Qt6.10.2, PipeWire desktop-output monitor.
- Hardware: classic ESP32/CP2102 with4MiB flash, two10-pixel5V RGB/GRB outputs
  on GPIO2/4. The current device configuration is read and retained on updates.
- Actual native USB/Wi-Fi setup, full-strip blue/off/music, finite signals,
  source expiry, authenticated configuration, OTA confirmation and rollback.
- With native0.2.1 the owner accepted beat alignment on Queen's
  Another One Bites the Dust. This was a visual/listening check, not an
  instrumented acoustic-to-light latency measurement.

The final candidate's installation/window/preview checks are recorded in
[the release checklist](RELEASE_CHECKLIST.md). A clean HOME on the tested host
is distinct from a new operating-system installation or a fresh Plasma login.

## Known limits

- Linux/KDE Plasma6 is the first target. Other desktops/OSes, USB driver models,
  MCU families and distributions have not been accepted. No RGBW, matrices,
  multiple simultaneously active ESPs or general WLED administration.
- First native installation and pairing, or changing the Wi-Fi network, require
  USB. Output/effect configuration and subsequent OTA work over paired Wi-Fi.
- Wi-Fi peers must be reachable on the same network; client-isolated guest
  networks and automatic recovery across arbitrary DHCP/DNS changes are untested.
- Wallpaper colour is global. Spatial wallpaper regions and per-application
  signal rules are later work. Native signals/calibration use the slower actual
  ESP preview fallback; smooth local preview currently covers Wi-Fi music.
- Fresh real Plasma login/logout, real sleep/wake combinations, power-cut OTA,
  arbitrary strip lengths/wiring and the extended hardware matrix remain untested.
  Do not treat synthetic tests as those physical results.
- The alpha may have rough edges. Keep the installer backup path and your
  controller's firmware backup. Settings are retained on uninstall; manually
  edited managed files stop automatic replacement.

## Install or report a problem

Use [the Russian quick start](QUICKSTART.ru.md) or the [README](README.md).
Choose the WESP release archive with native firmware for the built-in installer;
GitHub's automatic source archives do not contain compiled firmware. Native
sources and the pinned build recipe are in [receiver/README.md](receiver/README.md).

For a report include WESP/native version, distribution/Plasma version, USB or
Wi-Fi, board/LED type, expected behaviour and steps. Do not post Wi-Fi passwords,
pair tokens, full flash backups, private settings or notification contents.
