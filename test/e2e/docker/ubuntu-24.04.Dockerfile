FROM ubuntu:24.04

ARG ZIG_VERSION=0.15.2

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      bash ca-certificates curl fish git libgit2-1.7 tar xz-utils zsh \
 && rm -rf /var/lib/apt/lists/*

RUN arch="$(uname -m)" \
 && case "$arch" in \
      aarch64|arm64) zig_arch=aarch64 ;; \
      x86_64|amd64) zig_arch=x86_64 ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac \
 && curl -fsSL "https://ziglang.org/download/${ZIG_VERSION}/zig-${zig_arch}-linux-${ZIG_VERSION}.tar.xz" -o /tmp/zig.tar.xz \
 && mkdir -p /opt/zig \
 && tar -xJf /tmp/zig.tar.xz -C /opt/zig --strip-components=1 \
 && ln -s /opt/zig/zig /usr/local/bin/zig \
 && rm -f /tmp/zig.tar.xz

WORKDIR /src
