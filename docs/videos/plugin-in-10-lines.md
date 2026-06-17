# Plugin In 10 Lines

Purpose: short Lua plugin tutorial showing the smallest manifest-backed plugin shape that current Shisa validates.

Target length: 4:45 to 5:15.

## Message

A Shisa plugin is a Lua bundle with a manifest. The smallest useful tutorial plugin declares identity, API version, license, one module id, and a render entry point. Omitted capabilities deny host access.

Current runtime limit: plugin manifests install and validate; plugin render functions are not yet wired into the daemon render pipeline.

## 10-Line Plugin

```lua
function render(ctx)
  return "hello"
end
return {
  name = "hello",
  version = "0.1.0",
  api_version = 1,
  license = "MIT",
  modules = { "hello" },
}
```

This defaults all capabilities to deny. Use the longer form from [Plugin in 30 Lines of Lua](../recipes/plugin-in-30-lines.md) when teaching explicit capability fields.

## Structure

| Time | Visual | Voiceover |
| --- | --- | --- |
| 0:00-0:20 | Open `docs/plugin-manifest.md`. | "Shisa plugins are Lua bundles with a manifest. The manifest is the contract the daemon validates before installation." |
| 0:20-1:05 | Type the 10-line `plugin.lua`. | "This minimal plugin declares a render function, name, version, API version, license, and one exported module id." |
| 1:05-1:35 | Show `capabilities` docs. | "There is no host access here. Omitted capabilities deny filesystem, exec, network, environment, secrets, and pre-exec access." |
| 1:35-2:15 | Create Git repo and commit. | "`shisa plugin install` expects a plugin source tree. A Git repo gives the installer something auditable and repeatable." |
| 2:15-2:55 | Run strict install command. | "Install with `--yes --plugin-sandbox-strict` for scripts. Strict mode rejects unknown manifest and capability fields." |
| 2:55-3:25 | Run `shisa plugin list`. | "After install, list plugin state. Enable, disable, and trust are separate operations." |
| 3:25-4:10 | Show longer capability example. | "When a plugin needs host access, use exact allow-lists. Avoid broad `exec`, `net`, or filesystem scopes." |
| 4:10-4:40 | Show current runtime limit in docs. | "Today this validates plugin metadata. Plugin render functions are not yet in the daemon render pipeline." |
| 4:40-5:00 | End on plugin docs. | "Start minimal, add capabilities only when the plugin needs them, and keep the manifest easy to review." |

## Commands

```sh
mkdir hello-plugin
cd hello-plugin
$EDITOR plugin.lua
git init
git add plugin.lua
git commit -m "init plugin"
shisa plugin install . --yes --plugin-sandbox-strict
shisa plugin list
```

State commands:

```sh
shisa plugin disable hello
shisa plugin enable hello
shisa plugin trust hello
```

## Transcript

Shisa plugins are Lua bundles with a manifest.

The manifest is the contract the daemon validates before installation.

This minimal plugin is ten lines: a render function, a returned manifest table, a name, a version, an API version, a license, and one module id.

The render function returns `hello`.

The manifest exports the module id `hello`.

There is no host access in this plugin.

In Shisa, omitted capabilities deny access by default. That means this plugin cannot read files through host APIs, run commands, use network APIs, read environment variables, use secrets, or hook pre-exec behavior.

Create a plugin directory, write `plugin.lua`, initialize a Git repo, and commit it.

Then install with `shisa plugin install . --yes --plugin-sandbox-strict`.

Strict mode rejects unknown top-level manifest fields and unknown capability fields, which makes it useful for tutorials and CI.

After install, run `shisa plugin list`.

Enable, disable, and trust are separate commands so plugin state stays explicit.

When a plugin needs host access, move from the ten-line form to an explicit capability table. Use exact allow-lists for filesystem paths, commands, network targets, and environment variables.

Current limit: plugin manifests install and validate, but plugin render functions are not yet wired into the daemon render pipeline.

Start minimal, add capabilities only when the plugin needs them, and keep the manifest easy to review.

## Captions

- [SRT captions](plugin-in-10-lines.srt)

## Recording Checklist

- Show the 10-line plugin first.
- State that omitted capabilities deny host access.
- Run strict install.
- Show `plugin list`.
- Show the current runtime limit before ending.
- Do not claim the plugin renders inside the prompt yet.

## Cut List

- Remove any direct `os`, `io`, `package`, `require`, `dofile`, or `loadfile` Lua use.
- Remove broad host-access examples.
- Remove prompt-output demo claims until plugin render pipeline wiring lands.
