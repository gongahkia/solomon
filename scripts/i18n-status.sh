#!/usr/bin/env bash
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'i18n-status: missing required command: %s\n' "$1" >&2
    exit 1
  }
}

count_msgids() {
  awk '
    /^msgid / && $0 != "msgid \"\"" { count++ }
    END { print count + 0 }
  '
}

need msgattrib
need msgfmt

printf '| Locale | Catalog | Translated | Status |\n'
printf '| --- | --- | --- | --- |\n'

found=0
for po in "$repo_root"/i18n/*/LC_MESSAGES/shisa.po; do
  [ -e "$po" ] || continue
  found=1
  locale="${po#"$repo_root"/i18n/}"
  locale="${locale%%/*}"
  rel="${po#"$repo_root"/}"
  total="$(msgattrib --no-obsolete "$po" | count_msgids)"
  translated="$(msgattrib --translated --no-obsolete "$po" | count_msgids)"
  if msgfmt --check -o /dev/null "$po" >/dev/null 2>&1; then
    status="valid"
  else
    status="invalid"
  fi
  printf '| %s%s%s | %s%s%s | %s/%s | %s |\n' '`' "$locale" '`' '`' "$rel" '`' "$translated" "$total" "$status"
done

if [ "$found" -eq 0 ]; then
  printf '| none | none | 0/0 | missing |\n'
fi
