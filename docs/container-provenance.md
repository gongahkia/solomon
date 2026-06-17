# Container Provenance

`container_provenance` detects local container/runtime context.

Docker detection checks for `/.dockerenv`.

Podman detection inspects cgroup text for `libpod` or `podman` markers.

Devcontainer detection checks for a non-empty `$REMOTE_CONTAINERS`.

Nix shell detection checks for a non-empty `$IN_NIX_SHELL`.

Distrobox detection checks for a non-empty `$CONTAINER_ID`.

Toolbx detection checks for `/run/.toolbxenv` and `/run/.toolboxenv`.

Kubernetes detection checks `$KUBERNETES_SERVICE_HOST` and `/var/run/secrets/kubernetes.io/serviceaccount/namespace`.

Rendered output uses `[{provider}:{name}]`, for example `[docker:web]`.
