# Release candidate acceptance

Product: WESP. Version: 0.2.0-alpha.11. Author: Chapman. License: MIT.
The first alpha targets KDE Plasma 6; the product name is desktop-independent.

## Standalone application — alpha.8

- [x] Actual Qt Quick window loads; demo power control edits the isolated demo,
  with physical RPCs rejected by the test boundary.
- [x] Demo analysis and tuning reuse existing DSP/rendering without writing saved
  settings, selecting a controller or opening USB/TCP.
- [x] Real multi-process owner exports the transmitted host frame; Off exports
  black. Preview is bounded/private and never a delivery/current measurement.
- [x] App QML, modules, launcher and desktop entry participate in cold install/
  uninstall; source archives include the GUI and pinned dependency file.
- [ ] Real application-menu activation and repeated launch on the owner's session.
- [ ] Real setup edits/save and Wi-Fi switching from the new window.
- [ ] Hardware and demo toggling while a real music session continues unchanged.
- [ ] Visible language/theme/layout acceptance of all application pages.

Guided first-light and spatial wallpapers remain future milestones.

## First light and Wi-Fi configuration — alpha.10

- [x] Owner-driven dim chase/RGB checks expire without a GUI producer; Off stops
  the test and cannot be undone by restoring a scene. Demo checks are isolated.
- [x] Actual Qt tests cover paired Wi-Fi read/save without a USB port, uncommitted
  text surviving polling, actionable GPIO validation and demo test cancellation.
- [x] Local TCP tests cover authenticated CFG, new counts, independent read-back,
  old firmware rejection, USB-only network changes and explicit count recovery.
- [x] Native firmware 0.1.2 compiles with the pinned ESP32 toolchain; C++ core
  policy/watchdog/status tests pass under sanitizers.
- [ ] Independent code review and CI on the final commit.
- [ ] Firmware update on the identified test ESP, preserving NVS/pairing, followed
  by physical Wi-Fi output configuration, read-back and power-cycle persistence.
- [ ] Physical direction/RGB checks, cancellation, Off/sleep and current-scene
  resumption from the standalone window. Demo is not physical acceptance.

## Music scenes — alpha.9

- [x] Shared demo/device Renderer: original meter or coherent onset Pulse;
  continuous bass does not become repeated beats, silence/noise stays bounded.
- [x] Soft/Vivid/custom tuning preserves the palette/controller and restores
  the previous manual set; invalid saved tuning cannot import hardware fields.
- [x] Scene changes respect Off and volume priority. Volume expiry restores the
  newly selected Calm scene without replaying the previous music snapshot.
- [x] Actual Qt style/preset/scene controls preserve demo isolation and Off.
- [ ] Owner A/B demo acceptance of Pulse and preset character.
- [ ] Physical Pulse/music/speech/silence test on both configured sections.
- [ ] Physical scene/overlay/Off/sleep lifecycle from the standalone window.

## Implemented and automated

- Explicit enrollment; no personal serial port, MAC or HTTP address in defaults.
- Selected MAC/count validation before mutations; single UART owner and stale-state rejection.
- Arbitrary nonoverlapping named sections, direction/position and common physical rendering.
- Fast attack/capture with persisted live decay control.
- All six desktop services and XDG-aware application/config/state paths.
- Empty-HOME install/upgrade/rollback/uninstall, edited-file guard and partial-write recovery.
- No transfer of saved effect state between controller identities.
- No firmware binaries, backups, operating logs or private configuration in source.
- Configurable attack/decay/sensitivity/gate, fixed and wallpaper palettes,
  notification styles/color/strength and a temporary preview.
- A single `python3 check_release.py` gate: tests, real shell quoting, source
  hygiene, reproducible archive/checksums and cold archive installation lifecycle.
- English source/Russian gettext catalog shared by QML/helpers; checked coverage
  and placeholders; managed install/rollback/removal of both locale copies.

## Completed local release checks — 2026-10-22

- [x] Full release gate: 101 tests, shell quoting, translations, source hygiene,
  reproducible archives and cold install/upgrade/rollback/uninstall.
- [x] Actual AF_UNIX client/service integration in separate processes with only
  UART replaced: enrollment, state/RGB/off, selected identity/count guards,
  malformed requests, competing owner and graceful socket cleanup. Passed on
  the unrestricted local host; the same tests also passed in all three remote CI jobs on 2026-10-23.
- [x] Light/dark SVG rendering and live QML theme selection checked offscreen.
  This is not a real Plasma theme/session lifecycle check.

## Confirmed external CI — 2026-10-23

- [x] GitHub Actions on Ubuntu 24.04: Python 3.10/3.12/3.14, 101 tests in each
  job; translations, real IPC, shell quoting, reproducible builds and cold
  install/upgrade/rollback/uninstall all passed.
- Evidence: [run 39858410742](https://github.com/shelomitsky/WESP/actions/runs/39858410742),
  commit `fb1a147225b93647a4196fc25ae2d97493d3e576`.
- Repository: [shelomitsky/WESP](https://github.com/shelomitsky/WESP), private
  while the remaining desktop/hardware/review gates are open.

## Confirmed on the owner's current setup

Owner report, 2026-10-21: the updated remote and new controls work and fit better.
Owner report, 2026-10-22: «Цвета слайдшоу» appears and the palette changes when
the wallpaper changes. This accepts standard KDE slideshow following on that
setup. It is not a fresh-install, different-distribution or latency measurement.

On 2026-10-22 the owner accepted the custom icon appearance. Managed updates
were applied with backups; after the latest update, all 34 managed hashes
matched and Plasma/USB/equalizer services were active. Existing-session upgrade
is verified; fresh install, rollback and logout/login acceptance remain open.

## Required before public release (not passed here)

- [ ] Fresh real KDE Plasma 6 session: QML modules, widget picker, scrolling many sections,
  text entry and layout save/cancel behavior. qmllint alone is insufficient.
- [ ] Real English-language Plasma session and locale changes across login: offscreen
  native KDE translation/layout checks do not replace session lifecycle acceptance.
- [ ] Explicitly selected real WLED board: enrollment, disconnect/reconnect, unrelated board,
  changes to WLED count, fallback baud and concurrent legacy serial owner.
- [ ] Physical unequal/reversed sections, notification/volume expiry, off/sleep/wake,
  manual-effect restoration and device-change rejection during active overlays.
- [ ] User systemd install/upgrade/rollback with real active/enabled states and logout behavior.
- [ ] Desktop dependency installation on a named supported Plasma 6 distribution.
  Ubuntu 24.04 source CI is verified; it does not install/accept a KDE session.
- [x] Independent AI review of the device switch and installer transaction boundaries:
  two separate reviewers re-reviewed the fixes on 2026-10-23; no remaining
  reproduced P1/P2 findings in their scope. Local release gate: 112 tests.
  Real systemd/KDE/hardware lifecycle acceptance remains in the open items above.

The owner has updated the candidate on their existing setup. The original USB
acceptance remains historical transport evidence. Do not infer new acceptance
for arbitrary controllers or a fresh desktop from it or from automated tests.

## Later milestones

Explicit main-mode selection, manual RGB and a standalone wallpaper mode; spatial wallpaper-to-section mapping; measured latency and Wi-Fi DDP; optional
firmware workflow. These remain future work. Global wallpaper palette extraction
and standard slideshow following are already implemented.

## Experimental native receiver acceptance (partially verified, 2026-10-24)

- [x] Install native firmware from the widget on the explicitly selected test ESP.
- [x] Configure GPIO/count/order/current limit and Wi-Fi through USB widget setup.
- [x] Join Wi-Fi and verify the selected MAC/token over TCP; use the widget to
  switch the desktop owner from USB to Wi-Fi.
- [x] Move the receiver to a separate USB supply: the computer USB port disappears,
  the receiver rejoins Wi-Fi and the existing desktop owner receives repeated
  verified status replies. Settings survive the power cycle.
- [x] Verify real lighting from the separate USB supply: the owner confirmed
  both strips fully illuminated during a 20-second dim blue test.
- [x] React to desktop music on both strips over Wi-Fi, confirmed by the owner.
- [x] With the TCP socket still open, stop PC frames for three seconds: both
  strips darken automatically and recover when frames resume, confirmed by the owner.
- [ ] Exercise hostname/IP fallback recovery after DHCP or DNS changes.
- [ ] Measure physical darkness timing against the 1.5-second target.
- [ ] Test reboot, USB/network interruptions, wrong identity and configuration recovery.
- [x] Firmware 0.1.1: the owner confirmed amber startup and green new-session
  runners on both strips, followed by darkness. App-only USB update retained
  byte-identical boot/NVS/OTA regions; authenticated Wi-Fi reconnected.
- [ ] Firmware 0.1.1: physically retest Off during a cue and frame-loss behavior.

The owner confirmed the widget installation/configuration and separate USB supply
steps. Status checks verified identity and retained settings after that power
cycle. The owner then connected the strips and accepted the dim blue output
test, music reaction and functional frame-loss/recovery test on firmware 0.1.0.
Physical darkness timing remains unmeasured. The owner separately accepted
the firmware 0.1.1 welcome sequence; deterministic native tests cover repeated
hello, Off and frame-expiry cancellation, but physical timing remains open.

ESP32 compile and native host/safety tests do not close these physical gates.
The previously accepted WLED board must remain unchanged.

## Native execution and OTA — alpha.11

- [x] Local C++ effects/lease/OTA-policy tests and actual-core software bench.
- [x] TCP fixtures: raw feature-only audio, one-shot event,7/8 heartbeat, CFG
  read-back, image chunk ordering/hash and on-demand ESP preview.
- [x] Actual Qt controls: named preset save while Off, preview does not starve
  status or disable controls; legacy Qt setup remains a separate regression gate.
- [x] Independent final review; two P2 findings fixed with failing regressions:
  heartbeat send timestamp and refused OTA worker remaining queued.
- [x] Final full release/Qt/native build and GitHub CI on final commit.
- [x] Physical app-only0.1.1→0.2.0 update with full backup and retained pairing.
- [x] Two-strip music, finite signal/volume overlays and current-music resumption.
- [x] Wallpaper heartbeat/fade, Off, silence and source-loss checks using camera.
- [x] CFG/presets persist across reboot; OTA trial→valid and unconfirmed rollback
  demonstrated on the identified board. No power-cut test has been performed.


Physical evidence on the test ESP32/CP2102, two ten-pixel GRB outputs (GPIO2/4),
500mA cap: app-only update retained the boot/NVS area byte-for-byte and pairing.
Wi-Fi configuration read-back, local rendering, source expiry, explicit Off,
constant non-bass tone repeats and continuously transmitted silence passed.
Cropped camera stills showed blue on both strips and darkness after expiry.
A native desktop-output test sent198 audio packets and zero RGB frames over10s;
142 audio packets continued after a notification, with42 distinct ESP previews.
The7/8 wallpaper heartbeat was sent at7.111s for an8s timeout; loss then darkened
both strips. Named preset/outputs survived OTA; trial app0 automatically returned
to the previously confirmed app1 when confirmation was withheld. Test lighting
finished Off. Exact physical latency/fade timing, DHCP changes, power-cut OTA and
the full desktop/hardware matrix remain untested. The original WLED board was
not accessed. These results do not imply support for every ESP or LED type.

## Economical real-time audio — alpha.14

- [x] Fixed40-byte authenticated wire format and24-byte local format.
- [x] Constant/silent input budget26 packets/10s, integer delta suppression.
- [x] Native core bench drops late/auth/reorder data, collapses queued peak/silence
  to the latest input, and preserves Off/config lease guards.
- [x] Real-pipe capture keeps the newest immutable window while consumer stalls.
- [x] TCP lock stall does not block UDP send; local socket backpressure drops.
- [x] Short RMS/clocked repeat/history and sparse same-target GUI preview tests.
- [ ] Final full release/Qt/native build, independent review and GitHub CI.
- [ ] OTA to identified ESP; real raw-level traffic, stale/replay/fail-dark tests.
- [ ] Physical beat-latency comparison and user acceptance.
