# Custom Theme Inheriting from okiya-night

Create a small external theme that overrides only the parts that differ from `okiya-night`.

## 1. Copy the theme path into config

Use an absolute path in `shisa.toml`:

```toml
version = 1
theme = "/Users/me/.config/shisa/themes/okiya-coral.toml"

[prompt]
modules = ["cwd", "git_branch", "exit_status", "jobs", "cmd_duration"]
```

`theme` accepts a built-in id or an external theme TOML path.

## 2. Write the child theme

```toml
version = 1
name = "okiya-coral"
extends = "okiya-night"

[palette]
accent = "216"
warning = "@accent"

[segments.cwd]
fg = "@accent"
style = "bold"

[segments.git_branch]
fg = "@warning"
ascii = "branch:"

[segments.cmd_duration]
style = "dim italic"
```

Inheritance is a shallow table merge:

- top-level scalar keys in the child replace the parent
- `[palette]`, `[separators]`, and `[segments.<id>]` keys merge by key
- palette references resolve after inheritance

## 3. Keep fallbacks explicit

If a segment sets `glyph`, also set `ascii`:

```toml
[segments.git_branch]
glyph = ""
ascii = "git:"
```

Use ANSI or ANSI-256 palette values for themes intended to work outside truecolor terminals.

## 4. Verify config resolution

```sh
shisa explain
```

The output includes the configured theme string. Theme contrast validation is tracked separately under `shisa theme validate`.

See [Theme Spec](../theme-spec.md) and [Config Schema](../config-schema.md).
