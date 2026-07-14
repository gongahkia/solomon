# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

ARG RUST_IMAGE=rust:1.89.0-bookworm@sha256:948f9b08a66e7fe01b03a98ef1c7568292e07ec2e4fe90d88c07bb14563c84ff
ARG RUNTIME_IMAGE=debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818
ARG BUSYBOX_IMAGE=busybox:1.37.0-musl@sha256:222ad6d973c0d198014546a65cd02c5fdedcc172123c5b4c2bf0af636550bd94

FROM ${RUST_IMAGE} AS builder

WORKDIR /src
COPY . .
RUN --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,target=/src/target,sharing=locked \
    cargo build --locked --release --package shibahama-cli && \
    install -D -m 0755 target/release/shibahama /out/usr/local/bin/shibahama && \
    install -D -m 0644 /etc/ssl/certs/ca-certificates.crt /out/etc/ssl/certs/ca-certificates.crt

FROM ${BUSYBOX_IMAGE} AS busybox

FROM ${RUNTIME_IMAGE} AS runtime

LABEL org.opencontainers.image.title="Shibahama" \
      org.opencontainers.image.description="Auditable, non-destructive memory for long-running LLM agents" \
      org.opencontainers.image.source="https://github.com/gongahkia/shibahama" \
      org.opencontainers.image.licenses="MIT"

COPY --from=builder /out/ /
COPY --from=busybox /bin/busybox /usr/local/bin/busybox
COPY docker/entrypoint.sh /usr/local/bin/shibahama-entrypoint

RUN groupadd --gid 65532 shibahama && \
    useradd --uid 65532 --gid 65532 --system --no-create-home shibahama && \
    install -d --owner=65532 --group=65532 --mode=0750 /var/lib/shibahama && \
    chmod 0755 /usr/local/bin/shibahama-entrypoint

USER 65532:65532
WORKDIR /var/lib/shibahama
VOLUME ["/var/lib/shibahama"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD ["/usr/local/bin/busybox", "wget", "-q", "-T", "3", "-O", "/dev/null", "http://127.0.0.1:8765/healthz"]
ENTRYPOINT ["/usr/local/bin/shibahama-entrypoint"]
