# 0.2.0-alpha.12 (candidate)

- Keep desktop-output capture alive while the output is unchanged. Follow actual
  default-output changes instead of recreating a recording every fifteen seconds.
- Receiver/network errors retry delivery without destroying the capture stream.
- Replace the stale WLED Equalizer audio-client label with WESP Audio. Capture
  uses the output monitor; desktop privacy indicators may still call it recording.
- Apply stable capture to the window-scoped demo as well.

# 0.2.0-alpha.11 (candidate)

- Native receiver0.2.0 runs music envelopes, meter/Pulse, steady-tone repeats,
  finite notification animations and volume overlays locally. Desktop sends raw
  RMS/bass at up to20Hz, with the legacy frame path retained for WLED/old firmware.
- Transfer versioned settings and presets over the paired connection with exact
  read-back; add five named user presets alongside three built-in tuning slots.
- Wallpaper colors change on demand; confirmations run at7/8 of the configured
  timeout, followed by a separate fade duration when the lease expires.
- Add a software bench compiling the exact firmware core for local timelines.
- Fetch actual ESP-rendered preview pixels only while the standalone window is
  open; no duplicate real-time renderer is required on the desktop.
- Add paired Wi-Fi OTA to the inactive app slot, ordered chunks and SHA256,
  explicit post-boot build/configuration checks and unconfirmed-boot rollback.
  Existing native firmware needs one USB update to acquire OTA support.

# 0.2.0-alpha.10

- Add dim, bounded direction/RGB checks for individual saved strips, with
  owner-driven expiry, Stop/Off and an isolated virtual demo.
- Guide receiver setup through output configuration, strip checks and verified
  Wi-Fi handoff; retain draft text during polling and explain invalid GPIOs.
- Configure an already paired native receiver's GPIOs, LED counts, color order
  and current budget over Wi-Fi. Confirm saves with independent read-back;
  retain transport, pairing and scene preferences.
- Native firmware 0.1.2 advertises Wi-Fi configuration support. First pairing
  and changing the Wi-Fi network still require USB; upgrading an existing
  0.1.1 board is a separate, one-time USB firmware update.

# 0.2.0-alpha.9

- Add coherent Pulse accents and retain the original meter, with one renderer
  shared by demo and device and no new audio dependencies.
- Add Soft/Vivid tuning presets and restoration of the user's manual tuning;
  preserve palette, master brightness and controller/network configuration.
- Select Music/Calm base scenes atomically and invalidate stale scene snapshots;
  Off remains independent, and temporary overlays return to the current scene.
- Show the active scene/temporary source in the standalone overview.

# 0.2.0-alpha.8 (candidate)

- Add a standalone PySide6/Qt Quick application, application-menu entry and
  single-window activation from the optional Plasma remote.
- Add a transport-free desktop-audio demo with isolated temporary tuning.
- Preview real host RGB frames exported by the existing device owner, including
  explicit Off; retain the single USB/Wi-Fi owner and firmware protocol.
- Include GUI assets in transactional installation, rollback and source archives;
  add actual standalone Qt controls and demo-isolation checks.
- Preserve existing music, section, notification and receiver setup behavior.
  New scenes/Pulse and guided calibration remain separate future milestones.

# 0.2.0-alpha.7 (candidate)

- Add a separate WESP receiver firmware with USB setup, Wi-Fi control, configured
  RGB outputs, current limits and fail-dark behavior when PC frames stop.
- Preserve the existing WLED backend and flashing choice for existing boards.
- Add widget setup of physical GPIO/count/color order and Wi-Fi without exposing
  passwords in shell arguments, logs or ordinary status responses.
- Add pinned ESP32 compilation and optional checksum-verified firmware bundles.

# 0.2.0-alpha.6 (candidate)

- Add a widget wizard for first installation of WLED on an unencrypted classic 4MB ESP32: private tooling, checksum-pinned images, full flash backup, explicit replacement confirmation and guarded normal enrollment.
- Keep USB identity verification and writing in one exclusive ROM connection; recover WESP service state after failed/interrupted jobs.
- Real visible first-run acceptance remains pending until exercised on the selected test board.

# Changes

## 0.2.0-alpha.5 — local candidate

- Installer aborts on failed service stops, cancels activating units, activates
  staged installations and recovers from partial uninstall/explicit rollback.
- Controller enrollment tolerates an unavailable prior board, commits both
  saved documents before handoff and serializes direct protocol selection
  against in-flight snapshot restoration. Identity/count guards remain enforced.
- Independent installer/controller re-review and regression coverage added.

- Public name WESP, independent of the desktop environment. The first alpha
  still targets KDE Plasma 6. Existing applet/CLI/service/config identities are
  preserved for upgrades; source archives now use the wesp name and folder.

- Mandatory real socket/service/client subprocess integration with a fake serial
  peer; enrollment, frame/power, invalid request, owner lock and shutdown checks.

- Custom two-strip W icon in the panel, popup and KDE widget picker.
- Light icon variant selected automatically with the widget's KDE color theme.
- English source/fallback UI and Russian translation for controls, tooltips,
  accessibility labels, audio/wallpaper status and helper error messages.
- Shared KDE/gettext domain, compiled catalogs in per-user managed installation,
  language/placeholder/catalog checks and guidance for adding more languages.
- Existing user section names remain unchanged.

## 0.2.0-alpha.4 — local candidate

- Standard KDE slideshow support reads the current image from running Plasma,
  avoiding a missing or stale Image entry in the saved desktop configuration.
- Owner confirmed slideshow palette changes on 2026-10-22.
- Added a complete source-release check, real shell argument tests and a Russian
  first-run guide. The Python 3.10/3.12/3.14 CI matrix is prepared, not yet run.

## 0.2.0-alpha.3

- Automatic equalizer palette from local wallpaper images and Picture of the Day.
- Palette preview and source/fallback status; sampling outside the audio worker.

## 0.2.0-alpha.2

- Separate Music / Signals / Strips settings, sensitivity, silence gate,
  independent attack and decay, and five fixed equalizer palettes.
- Notification styles: two flashes, pulse, tint or one pixel, configurable color
  and strength, with a preview that does not create a notification ID.

## 0.2.0-alpha.1

- Generalized USB device enrollment, named/reversed unequal sections, shared
  rendering, isolated settings and a per-user installer with backup/rollback.

No public release or publication is recorded yet. Local source checks and owner
reports do not replace the remaining checks in RELEASE_CHECKLIST.md.
