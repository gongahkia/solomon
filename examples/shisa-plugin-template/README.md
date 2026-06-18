# shisa-plugin-template

Starter repository for a Shisa Lua plugin.

## Files

- `plugin.lua`: strict manifest plus lifecycle hooks.
- `LICENSE`: MIT placeholder license.
- `.gitignore`: excludes packed `.shisa-plugin` bundles.

## Local Checks

From this directory:

```sh
shisa plugin lint .
shisa plugin pack .
shisa plugin install . --plugin-sandbox-strict
```

Current Shisa validates the manifest and lifecycle hook names. Daemon hook invocation is tracked separately from manifest validation.
