#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scenario="default"
out_dir="$root/bench-results"
runs="${SHISA_BENCH_RUNS:-25}"
warmup="${SHISA_BENCH_WARMUP:-5}"
sock="/tmp/shisa-compare-$$.sock"
log="/tmp/shisa-compare-$$.log"
scenario_tmp=""

while (($#)); do
  case "$1" in
    --scenario)
      scenario="${2:-}"
      shift 2
      ;;
    --out-dir)
      out_dir="${2:-}"
      shift 2
      ;;
    *)
      out_dir="$1"
      shift
      ;;
  esac
done

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'missing required command: %s\n' "$1" >&2
    exit 127
  }
}

quote() {
  printf '%q' "$1"
}

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$sock" "$log" "$scenario_tmp"
}

add_case() {
  names+=("$1")
  commands+=("$2")
}

need hyperfine
need zig
mkdir -p "$out_dir"

(cd "$root" && zig build release)
"$root/zig-out/bin/shisad" --foreground --socket "$sock" --log "$log" >/dev/null 2>&1 &
daemon_pid=$!
trap cleanup EXIT

for _ in {1..100}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done
[[ -S "$sock" ]] || {
  printf 'shisad socket not ready\n' >&2
  exit 1
}

names=()
commands=()

case "$scenario" in
  default)
    add_case "shisa" "$(quote "$root/zig-out/bin/shisa") prompt --socket $(quote "$sock") --cwd $(quote "$root") --shell zsh --cols 80 --rows 24"

    if command -v starship >/dev/null 2>&1; then
      add_case "starship" "cd $(quote "$root") && starship prompt --status 0 --jobs 0 --cmd-duration 0"
    else
      printf 'skip starship: command not found\n' >&2
    fi

    if command -v oh-my-posh >/dev/null 2>&1; then
      omp_cmd="cd $(quote "$root") && oh-my-posh print primary --shell uni"
      if [[ -n "${OMP_CONFIG:-}" ]]; then
        omp_cmd="$omp_cmd --config $(quote "$OMP_CONFIG")"
      fi
      add_case "oh-my-posh" "$omp_cmd"
    else
      printf 'skip oh-my-posh: command not found\n' >&2
    fi

    if [[ -n "${P10K_BENCH_CMD:-}" ]]; then
      add_case "p10k" "$P10K_BENCH_CMD"
    else
      printf 'skip p10k: set P10K_BENCH_CMD to a render command\n' >&2
    fi
    ;;
  nixshell)
    scenario_tmp="$(mktemp -d /tmp/shisa-nixshell-bench-XXXXXX)"
    mkdir -p "$scenario_tmp/repo" "$scenario_tmp/off/shisa" "$scenario_tmp/on/shisa"
    printf '[project]\nname = "bench"\n' >"$scenario_tmp/repo/pyproject.toml"
    cat >"$scenario_tmp/off/shisa/shisa.toml" <<'EOF'
version = 1
theme = "plain"

[prompt]
modules = ["cwd"]

[modules.language_versions]
path_hash_invalidate = false
EOF
    cat >"$scenario_tmp/on/shisa/shisa.toml" <<'EOF'
version = 1
theme = "plain"

[prompt]
modules = ["cwd"]

[modules.language_versions]
path_hash_invalidate = true
EOF
    add_case "shisa-path-hash-off" "XDG_CONFIG_HOME=$(quote "$scenario_tmp/off") $(quote "$root/zig-out/bin/shisa") prompt --socket $(quote "$sock") --cwd $(quote "$scenario_tmp/repo") --shell zsh --cols 80 --rows 24"
    add_case "shisa-path-hash-on" "XDG_CONFIG_HOME=$(quote "$scenario_tmp/on") $(quote "$root/zig-out/bin/shisa") prompt --socket $(quote "$sock") --cwd $(quote "$scenario_tmp/repo") --shell zsh --cols 80 --rows 24"
    ;;
  *)
    printf 'unknown scenario: %s\n' "$scenario" >&2
    exit 2
    ;;
esac

if ((${#names[@]} < 2)); then
  printf 'no comparison targets available\n' >&2
  exit 2
fi

args=(--warmup "$warmup" --runs "$runs" --export-json "$out_dir/comparison.json" --export-markdown "$out_dir/comparison.md")
for i in "${!names[@]}"; do
  args+=(--command-name "${names[$i]}" "${commands[$i]}")
done

hyperfine "${args[@]}"
