# Contributing

Author: Chapman. Preserve the copyright/license notice when sharing the code.
Please credit Chapman when sharing derived builds, screenshots and articles.

The initial target is Linux/KDE Plasma 6. Follow the existing JSON command
boundary and single-controller ownership. Device selection must be explicit.
Never disable identity checks to support another controller.

```sh
python3 check_release.py
```

Use isolated HOME/XDG/runtime and fake serial boundaries. CI must not touch real
devices, user buses, desktop audio or services. Keep hardware acceptance separate
and record the tested model, version and method. In latency work distinguish
host timings from physical audio-to-light measurements.
The full check requires Node.js and GNU gettext as well as requirements.txt. It builds and
installs in temporary directories; no desktop dependency preflight is invoked.
Do not skip a failing shell/protocol check to make a restricted runner green.
Use literal English translation keys and numbered `%1`, `%2` placeholders.
See TRANSLATING.md; preserve existing user names and stored protocol keys.

Never submit device credentials, private paths or real device identity fixtures.
Use synthetic locally administered MAC addresses for tests. Exclude installation
backups and reports. Large behavior changes require independent review, especially
controller switching, power/sleep and installer rollback.

Use `control.dispatch()` for CLI/service commands. Enrollment takes the shared
command lock in the USB owner; do not hold a client-side command lock while
calling enrollment. Other commands keep their existing lock. The owner takes
command lock before device lock and revalidates ordinary requests under device
lock. Ordinary RPC must remain available while enrollment waits/restores an
old snapshot; shutdown joins request threads before closing their Device.
