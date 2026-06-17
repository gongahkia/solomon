# Container Provenance

`container_provenance` detects local container/runtime context.

Docker detection checks for `/.dockerenv`.

Podman detection inspects cgroup text for `libpod` or `podman` markers.
