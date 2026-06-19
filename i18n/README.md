# I18n Catalogs

Shisa uses gettext-compatible PO catalogs:

```text
i18n/
  shisa.pot
  <locale>/LC_MESSAGES/shisa.po
```

Rules:

- `shisa.pot` is the source template.
- Locale catalogs use BCP 47-ish directory names, for example `en-US`.
- Catalog files stay UTF-8.
- Message ids are stable English source strings from `zig build i18n-extract`.
- Generated `.mo` files are build artifacts and should not be committed.

The initial locale is `en-US`, stored at `i18n/en-US/LC_MESSAGES/shisa.po`.
