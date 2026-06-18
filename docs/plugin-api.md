# Plugin API Reference

Generated from `/// plugin-api:` annotations in `src/plugin/*.zig` with `zig build plugin-api-docs`.

## Manifest Fields

| Name | Type | Default | Notes |
| --- | --- | --- | --- |
| `name` | string | required | lowercase plugin id matching `[a-z0-9][a-z0-9._-]*`. |
| `version` | semver string | required | semantic version; prerelease and build metadata are accepted. |
| `api_version` | integer | required | must equal Shisa supported plugin API major `1`. |
| `license` | string | required | SPDX-like token using letters, digits, `.`, `-`, and `+`. |
| `capabilities` | table | deny all | omitted capability fields deny access. |
| `modules` | string array | required | non-empty exported module id list; module ids are lowercase with digits and `_`. |
| `description` | string | optional | human-readable summary. |
| `author` | string | optional | plugin author or maintainer. |
| `homepage` | string | optional | public project homepage. |
| `repository` | string | optional | public source repository URL. |

## Capabilities

| Name | Type | Default | Notes |
| --- | --- | --- | --- |
| `fs_read` | string array | empty | readable paths or scopes; gate supports exact paths, `~/`, relative plugin paths, and recursive `/**`. |
| `fs_watch` | string array | empty | watchable paths or scopes; same path rules as `fs_read`. |
| `exec` | false or string array | false | exact allow-list of command names. |
| `net` | false or string array | false | exact allow-list of provider or domain ids. |
| `secrets` | bool | false | enables host secret APIs when those APIs exist. |
| `env_read` | string array | empty | exact allow-list of environment variable names. |
| `pre_exec` | bool | false | allows pre-exec hook integration. |

## Entry Points

| Name | Type | Default | Notes |
| --- | --- | --- | --- |
| `render` | Lua identifier | `render` | synchronous render function name. |
| `update` | Lua identifier | optional | async/cache refresh function name. |

## Capability Gate

| Name | Type | Default | Notes |
| --- | --- | --- | --- |
| `fs_read` | path | denied by default | `checkFsRead` accepts exact matches, recursive scopes ending in `/**`, `~/`, and relative plugin-dir scopes. |
| `fs_watch` | path | denied by default | `checkFsWatch` uses the same path matching rules as `fs_read`. |
| `exec` | command name | denied by default | `checkExec` requires an exact command allow-list match. |
| `net` | provider or domain id | denied by default | `checkNet` requires an exact allow-list match. |
| `env_read` | env var name | denied by default | `checkEnvRead` requires an exact environment variable allow-list match. |
| `secrets` | host secret API | denied by default | `checkSecrets` requires `secrets = true`. |
| `pre_exec` | pre-exec hook | denied by default | `checkPreExec` requires `pre_exec = true`. |

## Lua Sandbox

| Name | Type | Default | Notes |
| --- | --- | --- | --- |
| `removed_globals` | `os`, `io`, `package`, `debug`, `require`, `dofile`, `loadfile` | always | sandbox startup removes direct shell, filesystem, loader, debug, and package APIs from Lua globals. |
