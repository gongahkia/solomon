#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

out_dir="${SHISA_THEME_PREVIEW_DIR:-zig-out/theme-previews}"
mkdir -p "$out_dir"

if [ ! -x ./zig-out/bin/shisa ]; then
  zig build debug --summary none
fi

ansi_hex() {
  local index="$1"
  local base=(000000 800000 008000 808000 000080 800080 008080 c0c0c0 808080 ff0000 00ff00 ffff00 0000ff ff00ff 00ffff ffffff)
  if [ "$index" -lt 16 ]; then
    printf '#%s' "${base[$index]}"
  elif [ "$index" -le 231 ]; then
    local cube=$((index - 16))
    local steps=(0 95 135 175 215 255)
    printf '#%02x%02x%02x' "${steps[$((cube / 36))]}" "${steps[$(((cube / 6) % 6))]}" "${steps[$((cube % 6))]}"
  else
    local gray=$((8 + (index - 232) * 10))
    printf '#%02x%02x%02x' "$gray" "$gray" "$gray"
  fi
}

palette_value() {
  local theme="$1"
  local key="$2"
  awk -v key="$key" '
    /^\[palette\]$/ { in_palette = 1; next }
    /^\[/ { in_palette = 0 }
    in_palette && $1 == key {
      value = $0
      sub(/^[^=]+=[[:space:]]*/, "", value)
      gsub(/"/, "", value)
      print value
      exit
    }
  ' "$theme"
}

color_hex() {
  local theme="$1"
  local key="$2"
  local value
  value="$(palette_value "$theme" "$key")"
  case "$value" in
    \#??????) printf '%s' "$value" ;;
    ''|@*) printf '#d6d6d6' ;;
    *[!0-9]*) printf '#d6d6d6' ;;
    *) ansi_hex "$value" ;;
  esac
}

xml_escape() {
  sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'
}

found=0
index_file="$out_dir/index.html"
{
  printf '%s\n' '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
  printf '%s\n' '<title>Shisa Theme Previews</title><style>body{font:16px system-ui,sans-serif;margin:24px;background:#111;color:#eee}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}img{width:100%;height:auto;border:1px solid #333}</style></head><body><h1>Shisa Theme Previews</h1><div class="grid">'
} > "$index_file"

for theme in themes/*.toml; do
  [ -e "$theme" ] || continue
  found=1
  ./zig-out/bin/shisa theme validate "$theme" >/dev/null
  name="$(basename "$theme" .toml)"
  safe_name="$(printf '%s' "$name" | xml_escape)"
  fg="$(color_hex "$theme" fg)"
  muted="$(color_hex "$theme" muted)"
  accent="$(color_hex "$theme" accent)"
  success="$(color_hex "$theme" success)"
  warning="$(color_hex "$theme" warning)"
  danger="$(color_hex "$theme" danger)"
  svg="$out_dir/$name.svg"
  cat > "$svg" <<SVG
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="220" viewBox="0 0 960 220" role="img" aria-label="Shisa $safe_name theme preview">
  <rect width="960" height="220" fill="#0d1117"/>
  <rect x="32" y="28" width="896" height="164" rx="8" fill="#05070a" stroke="#30363d"/>
  <text x="56" y="78" fill="$muted" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="22">theme: <tspan fill="$fg">$safe_name</tspan></text>
  <text x="56" y="124" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="26">
    <tspan fill="$accent">~/src/shisa</tspan>
    <tspan fill="$success"> git:main</tspan>
    <tspan fill="$danger"> exit:2</tspan>
    <tspan fill="$warning"> jobs:1</tspan>
    <tspan fill="$muted"> took:1.2s</tspan>
    <tspan fill="$fg"> &gt;</tspan>
  </text>
  <rect x="56" y="152" width="130" height="16" rx="3" fill="$accent"/>
  <rect x="198" y="152" width="130" height="16" rx="3" fill="$success"/>
  <rect x="340" y="152" width="130" height="16" rx="3" fill="$warning"/>
  <rect x="482" y="152" width="130" height="16" rx="3" fill="$danger"/>
</svg>
SVG
  printf '<a href="%s.svg"><img src="%s.svg" alt="%s theme preview"></a>\n' "$name" "$name" "$safe_name" >> "$index_file"
done

printf '%s\n' '</div></body></html>' >> "$index_file"

[ "$found" -eq 1 ] || {
  echo "theme preview screenshots: no themes found" >&2
  exit 1
}

printf 'wrote %s\n' "$out_dir"
