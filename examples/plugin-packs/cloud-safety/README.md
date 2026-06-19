# Cloud Safety Plugin Pack

This opt-in pack lives outside core and exports three safety modules:

- `prod_warning`: blocks commands that mention production contexts.
- `k8s_namespace_risk`: blocks destructive Kubernetes commands and explicit prod namespaces.
- `iam_principal`: blocks destructive IAM commands and role switches.

Install from a local checkout:

```sh
zig build debug
./zig-out/bin/shisa plugin lint examples/plugin-packs/cloud-safety
./zig-out/bin/shisa plugin install examples/plugin-packs/cloud-safety --plugin-sandbox-strict
```

The pack requests `pre_exec = true` and exact non-secret environment reads. It does not request filesystem, command execution, network, or secret access.
