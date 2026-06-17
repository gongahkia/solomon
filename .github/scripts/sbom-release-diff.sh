#!/usr/bin/env bash
set -eu

current_dir="${1:-dist}"
out_dir="${SHISA_SBOM_DIFF_DIR:-$current_dir/sbom-diff}"
current_tag="${GITHUB_REF_NAME:-current}"
previous_dir="${SHISA_PREVIOUS_SBOM_DIR:-}"
previous_tag="${SHISA_PREVIOUS_TAG:-}"

mkdir -p "$out_dir"

current_count="$(find "$current_dir" -maxdepth 1 -type f -name '*.spdx.json' | wc -l | tr -d ' ')"
if [ "$current_count" -eq 0 ]; then
  echo "sbom diff: no current SPDX SBOMs found in $current_dir"
  exit 1
fi

if [ -z "$previous_dir" ]; then
  repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
  previous_tag="$(
    gh release list --repo "$repo" --limit 20 --json tagName --jq '.[].tagName' |
      grep -Fxv "$current_tag" |
      head -n 1 || true
  )"
  if [ -z "$previous_tag" ]; then
    printf 'No previous release found for %s.\n' "$current_tag" > "$out_dir/README.txt"
    echo "sbom diff: no previous release; wrote review note"
    exit 0
  fi
  previous_dir="$(mktemp -d)"
  if ! gh release download "$previous_tag" --repo "$repo" --pattern '*.spdx.json' --dir "$previous_dir"; then
    printf 'Previous release %s has no downloadable SPDX SBOM assets.\n' "$previous_tag" > "$out_dir/README.txt"
    echo "sbom diff: previous release has no SPDX SBOM assets; wrote review note"
    exit 0
  fi
fi

previous_count="$(find "$previous_dir" -maxdepth 1 -type f -name '*.spdx.json' | wc -l | tr -d ' ')"
if [ "$previous_count" -eq 0 ]; then
  printf 'Previous release %s has no SPDX SBOM assets.\n' "${previous_tag:-unknown}" > "$out_dir/README.txt"
  echo "sbom diff: previous SBOM directory is empty; wrote review note"
  exit 0
fi

for current in "$current_dir"/*.spdx.json; do
  base="${current##*/}"
  suffix="${base#shisa-"$current_tag"-}"
  if [ "$suffix" != "$base" ] && [ -n "$previous_tag" ]; then
    previous_base="shisa-$previous_tag-$suffix"
  else
    previous_base="$base"
  fi
  previous="$previous_dir/$previous_base"
  stem="${base%.spdx.json}"
  diff_path="$out_dir/$stem.diff"

  if [ ! -f "$previous" ]; then
    printf 'No previous SBOM asset matched %s.\n' "$base" > "$diff_path"
    continue
  fi

  current_norm="$(mktemp)"
  previous_norm="$(mktemp)"
  jq -S . "$current" > "$current_norm"
  jq -S . "$previous" > "$previous_norm"
  if diff -u "$previous_norm" "$current_norm" > "$diff_path"; then
    printf 'No SBOM diff for %s.\n' "$base" > "$diff_path"
  fi
  rm -f "$current_norm" "$previous_norm"
done

echo "sbom diff: wrote review files to $out_dir"
