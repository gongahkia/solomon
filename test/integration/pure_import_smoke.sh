#!/usr/bin/env bash
set -euo pipefail

if ! command -v zsh >/dev/null 2>&1; then
  printf 'skip pure import smoke: zsh not found\n' >&2
  exit 0
fi

if ! command -v fish >/dev/null 2>&1; then
  printf 'skip pure import smoke: fish not found\n' >&2
  exit 0
fi

if ! command -v git >/dev/null 2>&1; then
  printf 'skip pure import smoke: git not found\n' >&2
  exit 0
fi

if [[ -z "${SHISA_PURE_ZSH_DIR:-}" || -z "${SHISA_PURE_FISH_DIR:-}" ]]; then
  printf 'skip pure import smoke: set SHISA_PURE_ZSH_DIR and SHISA_PURE_FISH_DIR\n' >&2
  exit 0
fi

if [[ ! -f "$SHISA_PURE_ZSH_DIR/pure.zsh" || ! -f "$SHISA_PURE_ZSH_DIR/async.zsh" ]]; then
  printf 'invalid SHISA_PURE_ZSH_DIR: %s\n' "$SHISA_PURE_ZSH_DIR" >&2
  exit 1
fi

if [[ ! -f "$SHISA_PURE_FISH_DIR/conf.d/pure.fish" || ! -d "$SHISA_PURE_FISH_DIR/functions" ]]; then
  printf 'invalid SHISA_PURE_FISH_DIR: %s\n' "$SHISA_PURE_FISH_DIR" >&2
  exit 1
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d /tmp/shisa-pure-smoke.XXXXXX)"

cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

out="$tmpdir/shisa.toml"
"$root/zig-out/bin/shisa" import-pure --dry-run >"$out"
grep -F 'theme = "pure"' "$out" >/dev/null
grep -F 'modules = ["cwd", "git_branch", "exit_status", "cmd_duration", "jobs", "user_host"]' "$out" >/dev/null
grep -F 'threshold_ms = 5000' "$out" >/dev/null
grep -F 'mode = "ssh"' "$out" >/dev/null

zsh_repo="$tmpdir/repo-zsh"
mkdir -p "$zsh_repo"
git -C "$zsh_repo" init --quiet
git -C "$zsh_repo" checkout -b smoke --quiet
printf 'x\n' >"$zsh_repo/file.txt"
git -C "$zsh_repo" add file.txt

PURE_ZSH_DIR="$SHISA_PURE_ZSH_DIR" REPO="$zsh_repo" zsh -f <<'ZSH' >"$tmpdir/zsh.out"
zstyle ':prompt:pure:title' show no
fpath=("$PURE_ZSH_DIR" $fpath)
autoload -U promptinit
promptinit || exit 1
prompt pure
cd "$REPO" || exit 1
contains() {
  [[ $1 == *"$2"* ]] || {
    print -u2 -- "missing zsh Pure marker: $2"
    return 1
  }
}
for fn in prompt_pure_setup prompt_pure_precmd prompt_pure_preprompt_render; do
  whence -w "$fn" >/dev/null || {
    print -u2 -- "missing zsh Pure function: $fn"
    exit 1
  }
done
contains "$PROMPT" 'prompt_pure_path_segment'
contains "$PROMPT" '%14v'
contains "$PROMPT" '%19v'
contains "$PROMPT" '%12v'
contains "$PROMPT" '%(13V.'
contains "$PROMPT" 'prompt:error'
[[ -z $RPROMPT ]] || {
  print -u2 -- "zsh Pure RPROMPT should be empty"
  exit 1
}
print -- zsh-pure-ok
ZSH
grep -F 'zsh-pure-ok' "$tmpdir/zsh.out" >/dev/null

fish_repo="$tmpdir/repo-fish"
mkdir -p "$fish_repo"
git -C "$fish_repo" init --quiet
git -C "$fish_repo" checkout -b smoke --quiet
printf 'x\n' >"$fish_repo/file.txt"
git -C "$fish_repo" add file.txt

PURE_FISH_DIR="$SHISA_PURE_FISH_DIR" REPO="$fish_repo" fish --private -C 'set fish_function_path $PURE_FISH_DIR/functions $fish_function_path; source $PURE_FISH_DIR/conf.d/_pure_init.fish; source $PURE_FISH_DIR/conf.d/pure.fish; cd $REPO' -c '
for fn in fish_prompt _pure_prompt_git _pure_prompt_git_dirty _pure_prompt_command_duration _pure_prompt_jobs _pure_prompt_ssh _pure_prompt_exit_status
    functions -q $fn; or begin
        echo "missing fish Pure function: $fn" >&2
        exit 1
    end
end
fish_prompt
' >"$tmpdir/fish.out"
grep -F 'repo-fish' "$tmpdir/fish.out" >/dev/null
grep -F 'smoke' "$tmpdir/fish.out" >/dev/null
