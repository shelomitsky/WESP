# Release candidate acceptance

Product: WESP. Version: 0.2.0-alpha.5. Author: Chapman. License: MIT.
The first alpha targets KDE Plasma 6; the product name is desktop-independent.

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
  the unrestricted local host; the same tests are mandatory in remote CI.
- [x] Light/dark SVG rendering and live QML theme selection checked offscreen.
  This is not a real Plasma theme/session lifecycle check.

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
- [ ] Dependency installation on a named supported distribution; the prepared
  Python 3.10/3.12/3.14 CI matrix still needs a real remote runner result.
- [ ] Independent review of the device switch and installer transaction boundaries.

The owner has updated the candidate on their existing setup. The original USB
acceptance remains historical transport evidence. Do not infer new acceptance
for arbitrary controllers or a fresh desktop from it or from automated tests.

## Later milestones

Explicit main-mode selection, manual RGB and a standalone wallpaper mode; spatial wallpaper-to-section mapping; measured latency and Wi-Fi DDP; optional
firmware workflow. These remain future work. Global wallpaper palette extraction
and standard slideshow following are already implemented.
