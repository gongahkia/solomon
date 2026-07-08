FROM fedora:40

ARG ZIG_VERSION=0.15.2

RUN dnf install -y bash ca-certificates curl fish git libgit2 sway tar xz zsh \
 && dnf clean all

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
