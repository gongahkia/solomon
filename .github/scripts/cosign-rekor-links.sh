#!/usr/bin/env bash
set -eu

bundle_dir="${1:-dist}"
out="${2:-$bundle_dir/rekor-links.txt}"

count="$(find "$bundle_dir" -maxdepth 1 -type f -name '*.sigstore.json' | wc -l | tr -d ' ')"
if [ "$count" -eq 0 ]; then
  echo "rekor links: no cosign bundles found in $bundle_dir"
  exit 1
fi

: > "$out"

for bundle in "$bundle_dir"/*.sigstore.json; do
  artifact="${bundle%.sigstore.json}"
  jq -r --arg artifact "${artifact##*/}" '
    [
      .verificationMaterial.tlogEntries[]?.logIndex,
      .rekorBundle.Payload.logIndex?
    ]
    | map(select(. != null))
    | unique[]
    | "\($artifact)\thttps://rekor.sigstore.dev/api/v1/log/entries?logIndex=\(.)"
  ' "$bundle" >> "$out"
done

if [ ! -s "$out" ]; then
  echo "rekor links: no transparency log indexes found in bundles"
  exit 1
fi

echo "rekor links: wrote $out"
