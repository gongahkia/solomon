#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ -x "$root/zig-out/bin/shisa" ]] || {
  printf 'shisa not built; run zig build debug first\n' >&2
  exit 1
}

tmp="/tmp/shisa-init-wizard-$$"
rm -rf "$tmp"
mkdir -p "$tmp/home/.config"
trap 'rm -rf "$tmp"' EXIT

export HOME="$tmp/home"
export XDG_CONFIG_HOME="$tmp/home/.config"
export PWD="$tmp/home/project"
export SHELL=/bin/zsh
export TERM_PROGRAM=Apple_Terminal
mkdir -p "$PWD"

out="$tmp/wizard.out"
printf '3\n\nY\n' | "$root/zig-out/bin/shisa" init >"$out"

config="$XDG_CONFIG_HOME/shisa/shisa.toml"
prefs="$XDG_CONFIG_HOME/shisa/shell.env"
rc="$HOME/.zshrc"

[[ -f "$config" ]] || { printf 'wizard smoke: missing config\n' >&2; exit 1; }
[[ -f "$prefs" ]] || { printf 'wizard smoke: missing shell prefs\n' >&2; exit 1; }
[[ -f "$rc" ]] || { printf 'wizard smoke: missing zshrc\n' >&2; exit 1; }
grep -q 'theme = "nord-dark"' "$config" || { printf 'wizard smoke: theme not written\n' >&2; exit 1; }
grep -q "SHISA_ASYNC_FILL='1'" "$prefs" || { printf 'wizard smoke: async pref not written\n' >&2; exit 1; }
grep -q '# >>> shisa >>>' "$rc" || { printf 'wizard smoke: start marker missing\n' >&2; exit 1; }
grep -q '# <<< shisa <<<' "$rc" || { printf 'wizard smoke: end marker missing\n' >&2; exit 1; }
grep -q 'SHISA_ASYNC_FILL=1' "$rc" || { printf 'wizard smoke: async hook env missing\n' >&2; exit 1; }
grep -q "$PWD" "$out" || { printf 'wizard smoke: cwd preview missing\n' >&2; exit 1; }
grep -q 'warning: Nerd Font glyphs may not render' "$out" || { printf 'wizard smoke: terminal warning missing\n' >&2; exit 1; }

tmp2="$tmp/noninteractive"
mkdir -p "$tmp2/home/.config"
HOME="$tmp2/home" XDG_CONFIG_HOME="$tmp2/home/.config" SHELL=/bin/bash \
  "$root/zig-out/bin/shisa" init --defaults --shell zsh --theme nord-dark --async on --write-hook >"$tmp/noninteractive.out"
grep -q 'theme = "nord-dark"' "$tmp2/home/.config/shisa/shisa.toml" || { printf 'wizard smoke: noninteractive theme missing\n' >&2; exit 1; }
grep -q '# >>> shisa >>>' "$tmp2/home/.zshrc" || { printf 'wizard smoke: noninteractive hook missing\n' >&2; exit 1; }
grep -q 'SHISA_ASYNC_FILL=1' "$tmp2/home/.zshrc" || { printf 'wizard smoke: noninteractive async hook missing\n' >&2; exit 1; }

printf 'init wizard smoke: ok\n'
