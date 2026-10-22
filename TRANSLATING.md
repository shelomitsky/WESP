# Adding a language

English is the source language. Russian is included as `locale/ru.po`. The
widget uses `i18nd("plasma_applet_org.wledcontrol.desktop", message, ...)`;
Python services use `i18n.tr(message, ...)` with the same gettext catalog.
This uses existing Plasma translation context and does not require a new QML
translation module or an additional runtime dependency.

1. Copy `locale/ru.po` to `locale/xx.po`, using the target language code.
2. Set the language/header/plural metadata and translate every `msgstr`.
   Keep `msgid` in English. Preserve numbered placeholders such as `%1`,
   `%2` and literal trailing percent signs. Translate complete sentences,
   not fragments joined to runtime values.
3. Compile with the GNU gettext developer tools:

```sh
mkdir -p locale/xx/LC_MESSAGES
msgfmt --check --check-format -o locale/xx/LC_MESSAGES/plasma_applet_org.wledcontrol.desktop.mo locale/xx.po
python3 check_translations.py
python3 check_release.py
```

Both `.po` and generated `.mo` are included in the source release. Installation
copies catalogs to the user XDG locale directory for KDE and the app's locale
directory for helpers; rollback/uninstall manage both copies. The installer
does not need msgfmt. The checker rejects missing translations, lost/added
placeholders and a compiled catalog that differs from its source.

Test in a real desktop session using the new language. Check narrow layouts,
tooltips, accessibility names, dynamic counters and error messages as well as
labels. Unknown languages fall back to English. User-defined strip names and
device names are not translation keys and must stay unchanged.

For a local helper-only check, set both message locale and language, for example
`LC_ALL=ru_RU.UTF-8 LANGUAGE=ru python3 -c 'import i18n; print(i18n.tr("Music"))'`.
Changing an environment variable on a CLI command does not change the running
Plasma session's language. Log out/in after changing KDE language settings.
