#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$root/bench-results}"
changes="${SHISA_JJ_BENCH_CHANGES:-10000}"
runs="${SHISA_JJ_BENCH_RUNS:-30}"
repo="${SHISA_JJ_BENCH_REPO:-}"
keep_repo="${SHISA_JJ_BENCH_KEEP_REPO:-0}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'missing required command: %s\n' "$1" >&2
    exit 127
  }
}

now_ns() {
  perl -MTime::HiRes=time -e 'printf "%.0f\n", time() * 1000000000'
}

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

cleanup() {
  if [[ "$keep_repo" != "1" && -n "${created_repo:-}" ]]; then
    rm -rf "$created_repo"
  fi
}

generate_git_history() {
  local dir="$1"
  git -C "$dir" init -q
  {
    for i in $(seq 1 "$changes"); do
      msg="change $i"
      data="change $i"
      printf 'commit refs/heads/main\n'
      printf 'committer Bench <bench@example.test> %d +0000\n' "$((1700000000 + i))"
      printf 'data %d\n%s\n' "${#msg}" "$msg"
      printf 'M 100644 inline file.txt\n'
      printf 'data %d\n%s\n' "${#data}" "$data"
    done
  } | git -C "$dir" fast-import --quiet
}

setup_repo() {
  if [[ -n "$repo" ]]; then
    printf '%s\n' "$repo"
    return
  fi

  created_repo="$(mktemp -d /tmp/shisa-jj-10k.XXXXXX)"
  generate_git_history "$created_repo"
  jj git init --git-repo "$created_repo/.git" "$created_repo" >/dev/null
  jj -R "$created_repo" --config user.name=Bench --config user.email=bench@example.test new main >/dev/null
  printf '%s\n' "$created_repo"
}

run_case() {
  local name="$1"
  shift
  local total=0
  local min=0
  local max=0
  local elapsed=0

  for i in $(seq 1 "$runs"); do
    local start end
    start="$(now_ns)"
    "$@" >/dev/null
    end="$(now_ns)"
    elapsed=$((end - start))
    total=$((total + elapsed))
    if [[ "$min" -eq 0 || "$elapsed" -lt "$min" ]]; then min="$elapsed"; fi
    if [[ "$elapsed" -gt "$max" ]]; then max="$elapsed"; fi
  done

  local avg=$((total / runs))
  printf '{"name":"%s","avg_ns":%d,"min_ns":%d,"max_ns":%d}' "$(json_escape "$name")" "$avg" "$min" "$max"
}

need git
need jj
need perl
mkdir -p "$out_dir"
trap cleanup EXIT

bench_repo="$(setup_repo)"
commit_count="$(git -C "$bench_repo" rev-list --count main)"
if [[ "$commit_count" != "$changes" ]]; then
  printf 'expected %s commits, got %s\n' "$changes" "$commit_count" >&2
  exit 1
fi

change_template='change_id.short(8) ++ "\n" ++ commit_id.short(8) ++ "\n" ++ coalesce(description.first_line(), "(no description set)") ++ "\n" ++ if(divergent, "divergent", "") ++ "\n"'
conflict_template='if(conflict, "conflict", "") ++ "\n" ++ self.conflicted_files().map(|f| f.path().display()).join("\n") ++ "\n"'
wc_template='commit_id.short(8) ++ "\n" ++ parents.map(|c| c.commit_id().short(8)).join(",") ++ "\n"'

op_log="$(run_case op_log jj -R "$bench_repo" op log --no-graph)"
current_change="$(run_case current_change jj -R "$bench_repo" log --no-graph -r @ --color never -T "$change_template")"
conflict_state="$(run_case conflict_state jj -R "$bench_repo" log --no-graph -r @ --color never -T "$conflict_template")"
working_copy="$(run_case working_copy jj -R "$bench_repo" log --no-graph -r @ --color never -T "$wc_template")"

json_path="$out_dir/jj-10k.json"
md_path="$out_dir/jj-10k.md"
cat >"$json_path" <<EOF_JSON
{"changes":$changes,"runs":$runs,"repo":"$(json_escape "$bench_repo")","results":[$op_log,$current_change,$conflict_state,$working_copy]}
EOF_JSON

{
  printf '# jj 10k-change benchmark\n\n'
  printf -- '- changes: %s\n' "$changes"
  printf -- '- runs: %s\n' "$runs"
  printf -- '- repo: `%s`\n\n' "$bench_repo"
  printf '| case | avg ns | min ns | max ns |\n'
  printf '| --- | ---: | ---: | ---: |\n'
  for row in "$op_log" "$current_change" "$conflict_state" "$working_copy"; do
    name="$(printf '%s' "$row" | sed -n 's/.*"name":"\([^"]*\)".*/\1/p')"
    avg="$(printf '%s' "$row" | sed -n 's/.*"avg_ns":\([0-9]*\).*/\1/p')"
    min="$(printf '%s' "$row" | sed -n 's/.*"min_ns":\([0-9]*\).*/\1/p')"
    max="$(printf '%s' "$row" | sed -n 's/.*"max_ns":\([0-9]*\).*/\1/p')"
    printf '| %s | %s | %s | %s |\n' "$name" "$avg" "$min" "$max"
  done
} >"$md_path"

cat "$json_path"
printf '\n'
