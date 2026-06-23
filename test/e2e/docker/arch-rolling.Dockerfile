FROM archlinux:base-devel

ARG ZIG_VERSION=0.15.2

RUN printf '\nDisableSandbox\n' >>/etc/pacman.conf \
 && pacman -Sy --noconfirm --needed bash ca-certificates curl fish git libgit2 tar xz zsh \
 && for f in /usr/lib/crt1.o /usr/lib/Scrt1.o /usr/lib/rcrt1.o /usr/lib/crti.o /usr/lib/crtn.o /usr/lib/libc_nonshared.a; do \
      [ -e "$f" ] && objcopy --remove-section .sframe "$f"; \
    done \
 && pacman -Scc --noconfirm

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
