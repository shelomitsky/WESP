# Verification record

## Independent review fixes — 2026-10-23

Two independent AI review contexts reviewed installer and controller handoff
against baseline `5b5110ce89107422b9c4a93fea3523055dd2b095`, then independently
re-reviewed the fixes. Both approved their scoped changes with no remaining
reproduced P1/P2 findings. This is code review, not desktop/hardware acceptance.

The local complete release gate passed **112 tests** and **166 translated
messages**, real shell quoting, reproducible archives and cold installation
lifecycle. Targeted verification includes:

- 11 installer tests: failed stops (including activating services), staged
  activation, preserving intentional disabled states, partial uninstall,
  partial explicit rollback with changed v1/v2 payloads and successful retry.
- 13 configuration tests: persistence failure restores both documents or their
  prior absence, cleans temporary files and allows retry.
- 19 transport tests and 7 actual multi-process IPC tests: disconnected/different
  prior boards, changed counts, real read-only config failure, old snapshot vs
  direct enrollment serialization, identity rejection and graceful shutdown.
- The controller reviewer separately exercised owner-side EQ restoration and
  dispatch enrollment; ordinary RPC completed without deadlock.

All tests used temporary HOME/XDG/runtime and fake UART. No real systemd, user
session, physical controller or installed application was changed by this work.
External CI status for each source revision is available in the repository's
[Actions](https://github.com/shelomitsky/WESP/actions).

## Baseline verification — 2026-10-22

Executed locally, before publication:

The public product name is now WESP, independent of the desktop environment.
The first alpha still targets KDE Plasma 6. The complete 101-test release gate
also passes with `wesp-0.2.0-alpha.5.tar.gz` and its `wesp/` source folder;
existing applet/CLI/service/config identities remain compatible with upgrades.

- `python3 -m unittest discover -s tests -q`: **101 tests, OK**. Real PCM pipes,
  DSP scenarios, selected-identity/count guards, layouts, namespaced configuration,
  persisted/live decay, fake UART transactions and disposable-HOME installation.
  Palette checks cover offline persistence, invalid choices, unchanged classic
  colors, meter fill, section reversal, gaps and explicit solid-color overrides.
  Wallpaper tests cover active-plugin/activity selection, local-file URLs,
  Picture of the Day cache replacement, fallback, transparency, neutral colors,
  a real Pillow decode and live cached-color updates in the running audio worker.
  Slideshow checks cover live-over-saved slide selection, a bounded read-only
  DBus call with unsigned screen index, red-to-blue slide changes through real
  image decoding, and missing-session/image/plugin-change fallback.
  The installed plasmashell binary exposes `wallpaper(uint) -> a{sv}`; its real
  session call remains untested here because the sandbox blocks the user bus.
- Four real IPC integration scenarios start the production USB service and
  independent clients in subprocesses with a real AF_UNIX socket and file lock.
  Only `serial.Serial` is replaced by a test WLED peer. They cover enrollment,
  selected MAC/count rejection, literal Adalight bytes, power-off suppression,
  malformed-request recovery, socket mode 0600, competing owners and SIGTERM
  cleanup/exit-realtime/return-to-baseline commands. HOME/XDG/runtime are temporary;
  no real serial port, desktop bus or live service is used. These passed on an
  unrestricted local execution host and subsequently on all three remote CI jobs.
  In the restricted sandbox, socket bind fails with `PermissionError: [Errno 1]
  Operation not permitted`; that is a failing environment, never a skipped test.
- Translation checks cover English/Russian/unknown-language fallback, C locale,
  safe numbered substitutions, translated backend validation and generated names,
  installed catalog loading and rollback/removal without touching another app's
  translation file. `check_translations.py` validates 165 source messages against
  the Russian catalog, placeholder counts and the compiled .mo source match.
- The actual popup markup was loaded with native KDE KI18nContext and installed
  catalogs in temporary XDG data. Main/Music/Signals/Strips at 320 logical pixels
  render in both English and Russian with no visible control outside the viewport.
  This uses a real KDE translator; it is not a full Plasma/session lifecycle test.
- Read-only local wallpaper probe found and decoded the configured Bing image
  from KDE's cache. Real activity DBus access is blocked in this sandbox; the
  first configured desktop fallback was used. No real LEDs were changed.
- Qt6 `qmllint plasma/org.wledcontrol.desktop/contents/ui/main.qml`: exit 0.
  It reports unqualified `i18nd` accesses: this is the global context supplied
  by Plasma. That translation context is exercised in the native offscreen check.
- Popup-width regression: the production ScrollView was loaded in an offscreen
  Qt Quick harness with fixture controller/section data. At 320 logical pixels
  the original SpinBox and Delete button exceeded the viewport; after the fix,
  visible control bounds fit at 300, 320 and 440 pixels. This exercises the actual
  popup markup, but is not a full Plasma shell/theme acceptance check.
- `python3 verify_release.py`: exit 0, bounded source-hygiene checks and Python
  3.10 syntax parsing. This is not a Python 3.10 runtime acceptance result.
- `python3 manage.py doctor`: required local dependency imports/tools found.
  It does not validate a real Plasma session or device.
- `node tests/test_queue.js`: exit 0, latest brightness and power ordering.
  Real shell argument checks now run from `test_commands.py`: Node evaluates
  the production Commands.js and Python runs `/bin/sh` with its quoted values.
  Empty/Unicode/multiline/quoted inputs round-trip; command substitutions and
  embedded commands do not create the temporary marker. This preserves the
  real shell boundary while avoiding Node's sandbox-specific spawn EPERM.
- `python3 check_release.py`: exit 0. Two source archives have identical bytes;
  archive SHA-256 and every bundled file match the manifests. An extracted copy
  completes install, upgrade, rollback, installed-launcher configuration read,
  and uninstall in a fresh HOME with a space, retaining settings byte for byte.
  No service manager, user bus or hardware is invoked.
- GitHub Actions ran this same gate on Ubuntu 24.04 for Python 3.10, 3.12
  and 3.14 on 2026-10-23 (Europe/Minsk). All three jobs passed 101 tests plus
  source/catalog/shell checks, reproducible builds and cold archive lifecycle.
  First verified commit: `fb1a147225b93647a4196fc25ae2d97493d3e576`.
  [First successful external CI run](https://github.com/shelomitsky/WESP/actions/runs/39858410742).
  The initial run reported a checkout@v4 Node.js 20 deprecation warning;
  checkout was subsequently updated to v6 (Node.js 24).

Environment for local Python tests: Python 3.14.4, NumPy 2.3.5, pyserial 3.5,
Pillow 12.1.1 and Node.js 22.22.2.
The core source gate is now verified on Ubuntu 24.04 with Python 3.10/3.12/3.14.
This does not accept Qt/Plasma/DBus packages or a fresh desktop installation.

The tests belong to the separate generalized candidate. They are not presented
as equivalent to the original installation's 94-scenario in-memory suite:
the original suite remains with that source, while the candidate reuses its
DSP/worker/UART checks and adds configuration/layout/installation checks.

The release checks run here use temporary HOME/XDG directories; IPC uses real temporary AF_UNIX sockets. They do not change
active lighting services or open a real UART. No firmware was flashed and no
public release was made by these checks. A private GitHub repository was
created and pushed on 2026-10-23 as recorded above. The owner has separately updated the candidate and
confirmed the new remote, controls and slideshow palette following. Physical
latency, fresh KDE installation and other pending checks remain in
RELEASE_CHECKLIST.md.

## Alpha.2 controls and notification effects

Additional tests cover attack separate from decay, sensitivity after adaptive
gain settles, adjustable noise gate, offline persistence and invalid settings,
two timed flashes, pulse/tint/pixel choices, configured-section-only overlays,
preview without notification IDs, manual-effect restoration, off/sleep/volume
priority and coalescing arrivals without resetting the animation to zero.

The main remote and all three settings pages were instantiated from the actual
popup markup in an offscreen Qt Quick harness at 320 logical pixels, with no
visible controls outside the viewport. This is layout evidence, not hardware
notification visibility or a full Plasma session test.

The local update_controls.py helper has isolated tests for adding the renderer
module, preserving settings, guarded rollback and recovery from a shell restart
failure. The 16 root-level migration/widget/update helper tests passed separately
on 2026-10-22; they are local maintenance tools, not part of the public package.
Live managed updates were separately applied with backups on the owner's setup;
after the light/dark icon update, all 34 installed hashes matched and Plasma,
USB and equalizer services were active. This does not accept fresh-user login
or real installer rollback scenarios.

## First-run wizard candidate (2026-10-24)

`tests/test_firmware.py` covers unsupported/protected/swapped boards, exact backup
size/digest, pinned downloads, one ROM connection for identity and write, foreign
port owners, failed service recovery and automatic connection with a pinned MAC
while excluding a concurrent preparation job. Source/backend checks do not accept
physical lighting or the visible wizard. Real board/UI acceptance is pending.

## USB/Wi-Fi receiver candidate (2026-10-24)

Receiver safety core is compiled and run with address/undefined-behavior
sanitizers. Tests cover complete RGB validation, watchdog/off, ownership,
inactivity framing and current limits. Native host tests use actual loopback
TCP for sessions, credentials, identity, count and reply guards, reconnection,
static colors and explicit frame maintenance. The local setup bridge is tested
for authentication and credential redaction. ESP32 compilation is an independent
CI job without device access. Firmware assets are built outside the worktree.

Physical LEDs, actual USB/Wi-Fi handoff, standalone supply and measured PC-off
dark behavior remain separate acceptance and must be recorded explicitly.
