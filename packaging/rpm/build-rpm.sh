#!/usr/bin/env bash
set -eu

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
out_dir="${1:-$repo_root/dist}"
version="${SHISA_VERSION:-}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'build-rpm: missing required command: %s\n' "$1" >&2
    exit 1
  }
}

if [ -z "$version" ]; then
  version="$(awk -F '"' '/\.version =/ { print $2; exit }' "$repo_root/build.zig.zon")"
fi

need git
need rpmbuild

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

topdir="$work/rpmbuild"
mkdir -p "$topdir/BUILD" "$topdir/RPMS" "$topdir/SOURCES" "$topdir/SPECS" "$topdir/SRPMS" "$out_dir"

git -C "$repo_root" archive --format=tar --prefix="shisa-$version/" HEAD | gzip -n > "$topdir/SOURCES/shisa-$version.tar.gz"
cp "$repo_root/packaging/rpm/shisa.spec" "$topdir/SPECS/shisa.spec"

rpmbuild -ba \
  --define "_topdir $topdir" \
  --define "shisa_version $version" \
  "$topdir/SPECS/shisa.spec"

find "$topdir/RPMS" "$topdir/SRPMS" -type f \( -name '*.rpm' -o -name '*.src.rpm' \) -exec cp {} "$out_dir/" \;
find "$out_dir" -maxdepth 1 -type f \( -name '*.rpm' -o -name '*.src.rpm' \) -print
