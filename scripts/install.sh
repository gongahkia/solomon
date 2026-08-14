#!/bin/sh
set -eu

repository=${CLOSE_ENOUGH_REPOSITORY:-gongahkia/close-enough}
version=${CLOSE_ENOUGH_VERSION:-}
release_base=${CLOSE_ENOUGH_RELEASE_BASE_URL:-}
install_dir=${CLOSE_ENOUGH_INSTALL_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}
selected_shell=${CLOSE_ENOUGH_SHELL:-}
shell_rc=${CLOSE_ENOUGH_SHELL_RC:-}
start_marker='# >>> close-enough initialize >>>'
end_marker='# <<< close-enough initialize <<<'

fail() {
  printf '%s\n' "close-enough installer: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "requires $1"
}

validate_repository() {
  case "$repository" in
    ""|/*|*/*/*|*..*|*[!A-Za-z0-9._/-]*) fail "invalid repository" ;;
  esac
}

validate_version() {
  case "$version" in
    v[0-9A-Za-z.+-]*) ;;
    *) fail "invalid release version" ;;
  esac
  case "$version" in
    *[!0-9A-Za-z.+-]*) fail "invalid release version" ;;
  esac
}

detect_target() {
  case "$(uname -s)" in
    Linux) goos=linux ;;
    Darwin) goos=darwin ;;
    *) fail "unsupported operating system" ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64) goarch=amd64 ;;
    arm64|aarch64) goarch=arm64 ;;
    *) fail "unsupported architecture" ;;
  esac
}

resolve_version() {
  if [ -n "$version" ]; then
    validate_version
    return
  fi
  require_command curl
  api_base=${CLOSE_ENOUGH_API_URL:-https://api.github.com}
  metadata=$(mktemp)
  trap 'rm -f "$metadata"' EXIT HUP INT TERM
  curl --fail --location --silent --show-error "$api_base/repos/$repository/releases/latest" -o "$metadata" || fail "could not resolve the latest release"
  version=$(sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$metadata")
  rm -f "$metadata"
  trap - EXIT HUP INT TERM
  validate_version
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
    return
  fi
  fail "requires sha256sum or shasum"
}

verify_checksum() {
  artifact=$1
  manifest=$2
  expected_name=$3
  expected=
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *[!\ -~]*) fail "checksum manifest contains invalid characters" ;;
    esac
    digest=${line%%'  '*}
    name=${line#*'  '}
    [ "$digest  $name" = "$line" ] || fail "checksum manifest has an invalid entry"
    [ "${#digest}" -eq 64 ] || fail "checksum manifest has an invalid digest"
    case "$digest" in
      *[!0123456789abcdef]*|'') fail "checksum manifest has an invalid digest" ;;
    esac
    case "$name" in
      ""|*/*|*\\*|*' '*) fail "checksum manifest has an invalid artifact name" ;;
    esac
    if [ "$name" = "$expected_name" ]; then
      [ -z "$expected" ] || fail "checksum manifest has duplicate artifacts"
      expected=$digest
    fi
  done < "$manifest"
  [ -n "$expected" ] || fail "checksum manifest does not contain $expected_name"
  actual=$(sha256_file "$artifact")
  [ "$actual" = "$expected" ] || fail "checksum mismatch for $expected_name"
}

verify_signature() {
  artifact=$1
  bundle=$2
  require_command cosign
  identity="https://github.com/$repository/.github/workflows/release.yml@refs/tags/$version"
  if ! cosign verify-blob "$artifact" --bundle "$bundle" --certificate-identity "$identity" --certificate-oidc-issuer https://token.actions.githubusercontent.com >/dev/null; then
    fail "Sigstore verification failed"
  fi
}

shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

detect_shell_init() {
  if [ -z "$selected_shell" ]; then
    selected_shell=$(basename "${SHELL:-}")
  fi
  case "$selected_shell" in
    bash)
      selected_shell=none
      printf '%s\n' 'close-enough: Bash integration is unavailable; installed the CLI without shell initialization' >&2
      ;;
    zsh|fish|none) ;;
    *) selected_shell=none ;;
  esac
  if [ "$selected_shell" = none ]; then
    return
  fi
  if [ -n "$shell_rc" ]; then
    return
  fi
  case "$selected_shell" in
    bash) shell_rc=$HOME/.bashrc ;;
    zsh) shell_rc=$HOME/.zshrc ;;
    fish) shell_rc=${XDG_CONFIG_HOME:-$HOME/.config}/fish/config.fish ;;
  esac
  case "$shell_rc" in
    /*) ;;
    *) fail "shell initialization path must be absolute" ;;
  esac
}

remove_shell_init_at() {
  target=$1
  [ -f "$target" ] || return 0
  grep -Fqx "$start_marker" "$target" || return 0
  grep -Fqx "$end_marker" "$target" || fail "managed shell initialization is incomplete in $target"
  temporary=$(mktemp "${target}.close-enough.XXXXXX")
  awk -v start="$start_marker" -v end="$end_marker" '
    $0 == start { skipping = 1; next }
    skipping && $0 == end { skipping = 0; next }
    !skipping { print }
  ' "$target" > "$temporary"
  mv "$temporary" "$target"
}

remove_shell_init() {
  detect_shell_init
  remove_shell_init_at "$HOME/.bashrc"
  [ "$selected_shell" != none ] || return
  remove_shell_init_at "$shell_rc"
}

add_shell_init() {
  detect_shell_init
  [ "$selected_shell" != none ] || return
  case "$shell_rc" in
    /*) ;;
    *) fail "shell initialization path must be absolute" ;;
  esac
  if [ -e "$shell_rc" ] && [ ! -f "$shell_rc" ]; then
    fail "shell initialization path is not a regular file"
  fi
  mkdir -p "$(dirname "$shell_rc")"
  touch "$shell_rc"
  if grep -Fqx "$start_marker" "$shell_rc"; then
    grep -Fqx "$end_marker" "$shell_rc" || fail "managed shell initialization is incomplete in $shell_rc"
    return
  fi
  binary=$(shell_quote "$install_dir/close-enough")
  printf '\n' >> "$shell_rc"
  {
    printf '%s\n' "$start_marker"
    case "$selected_shell" in
      zsh)
        printf 'if [ -x %s ]; then\n' "$binary"
        printf '  eval "$(%s init --shell %s)"\n' "$binary" "$selected_shell"
        printf 'fi\n'
        ;;
      fish)
        printf 'if test -x %s\n' "$binary"
        printf '  %s init --shell fish | source\n' "$binary"
        printf 'end\n'
        ;;
    esac
    printf '%s\n' "$end_marker"
  } >> "$shell_rc"
}

uninstall() {
  case "$install_dir" in
    /*) ;;
    *) fail "installation directory must be absolute" ;;
  esac
  target=$install_dir/close-enough
  if [ -L "$target" ]; then
    fail "refusing to remove symbolic link $target"
  fi
  if [ -e "$target" ]; then
    [ -f "$target" ] || fail "installation target is not a regular file"
    rm "$target"
  fi
  remove_shell_init
}

case "${1:-}" in
  --uninstall)
    [ "$#" -eq 1 ] || fail "usage: install.sh [--uninstall]"
    uninstall
    exit 0
    ;;
  "") ;;
  *) fail "usage: install.sh [--uninstall]" ;;
esac

validate_repository
resolve_version
detect_target
case "$install_dir" in
  /*) ;;
  *) fail "installation directory must be absolute" ;;
esac
require_command curl
require_command tar

archive="close-enough_${version}_${goos}_${goarch}.tar.gz"
root=${archive%.tar.gz}
if [ -z "$release_base" ]; then
  release_base="https://github.com/$repository/releases/download/$version"
fi
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
artifact=$temporary/$archive
manifest=$temporary/checksums.txt
bundle=$temporary/$archive.sigstore.json
curl --fail --location --silent --show-error "$release_base/$archive" -o "$artifact"
curl --fail --location --silent --show-error "$release_base/checksums.txt" -o "$manifest"
curl --fail --location --silent --show-error "$release_base/$archive.sigstore.json" -o "$bundle"
verify_checksum "$artifact" "$manifest" "$archive"
verify_signature "$artifact" "$bundle"
members=$(tar -tzf "$artifact") || fail "invalid release archive"
[ "$members" = "$root/
$root/close-enough" ] || fail "release archive has unexpected contents"
mkdir -p "$install_dir"
temporary_binary=$(mktemp "${install_dir}/.close-enough.XXXXXX")
tar -xOzf "$artifact" "$root/close-enough" > "$temporary_binary" || fail "could not extract release binary"
[ -s "$temporary_binary" ] || fail "release binary is empty"
chmod 755 "$temporary_binary"
mv -f "$temporary_binary" "$install_dir/close-enough"
add_shell_init
printf 'installed close-enough %s to %s\n' "$version" "$install_dir/close-enough"
