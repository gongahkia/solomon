# Translating Shisa

Translations use gettext-compatible PO files under `i18n/`.

## Workflow

1. Update the template after source extraction tooling lands:

   ```sh
   xgettext -o i18n/shisa.pot ...
   ```

2. Merge template changes into a locale:

   ```sh
   msgmerge --update i18n/en-US/LC_MESSAGES/shisa.po i18n/shisa.pot
   ```

3. Edit `msgstr` values in the locale PO file.

4. Validate the catalog:

   ```sh
   msgfmt --check --check-header -o /dev/null i18n/en-US/LC_MESSAGES/shisa.po
   ```

5. Refresh the status table:

   ```sh
   scripts/i18n-status.sh
   ```

## Review Rules

- Keep `msgid` unchanged.
- Translate `msgstr` only.
- Preserve placeholders and shell snippets exactly.
- Keep safety terms explicit, especially for production, SSH, cloud, exit status, and destructive-command warnings.
- Do not commit generated `.mo` files.

Translation PRs should include the locale, status table output, and the validation command used.
