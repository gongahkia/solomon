#!/usr/bin/env bash
set -eu

label="${RFC_COMMENT_LABEL:-rfc-comment-window}"
days="${RFC_COMMENT_DAYS:-14}"

timestamp_utc() {
  date -u -d "$1" +%s 2>/dev/null || date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$1" +%s
}

iso_utc() {
  date -u -d "@$1" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -r "$1" +"%Y-%m-%dT%H:%M:%SZ"
}

if [ -n "${RFC_COMMENT_LABEL_PRESENT:-}" ]; then
  label_present="$RFC_COMMENT_LABEL_PRESENT"
else
  repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
  pr="${PR_NUMBER:?PR_NUMBER is required}"
  labels="$(gh api "repos/$repo/issues/$pr/labels" --jq '.[].name')"
  if printf '%s\n' "$labels" | grep -Fxq "$label"; then
    label_present=1
  else
    label_present=0
  fi
fi

if [ "$label_present" != "1" ]; then
  echo "rfc comment window: label not present; ok"
  exit 0
fi

if [ -n "${RFC_COMMENT_LABEL_CREATED_AT:-}" ]; then
  created_at="$RFC_COMMENT_LABEL_CREATED_AT"
else
  repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
  pr="${PR_NUMBER:?PR_NUMBER is required}"
  created_at="$(
    gh api --paginate "repos/$repo/issues/$pr/events" \
      --jq '.[] | select(.event == "labeled") | [.label.name, .created_at] | @tsv' |
      awk -v label="$label" -F '\t' '$1 == label { value = $2 } END { print value }'
  )"
fi

if [ -z "$created_at" ]; then
  echo "rfc comment window: label is present but no label timestamp was found"
  exit 1
fi

start="$(timestamp_utc "$created_at")"
deadline=$((start + days * 86400))
now="${RFC_COMMENT_NOW:-$(date -u +%s)}"

if [ "$now" -lt "$deadline" ]; then
  echo "rfc comment window: open until $(iso_utc "$deadline")"
  exit 1
fi

echo "rfc comment window: ok"
