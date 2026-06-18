# Theme Spec

Theme files are TOML documents. Built-in theme ids use the same schema as external theme files.

Built-in ids: `plain`, `minimal-monochrome`, `okiya-night`, `nord-dark`, `gruvbox-rainbow`, `tokyo-night`, `pure`, `a11y`.

## File Shape

```toml
version = 1
name = "plain"
extends = ""

[capabilities]
color = "ansi" # none | ansi | ansi256 | truecolor
glyphs = "ascii" # ascii | nerd-font

[palette]
fg = "15"
muted = "8"
accent = "14"
success = "2"
warning = "3"
danger = "1"

[separators]
segment = " "
left = ""
right = ""

[segments.cwd]
fg = "@fg"
bg = ""
style = "bold"
glyph = ""
ascii = ""
suffix = ""

[segments.git_branch]
fg = "@accent"
bg = ""
style = ""
glyph = ""
ascii = "git:"
suffix = ""
```

## Top-Level Keys

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `version` | integer | yes | Must be `1`. |
| `name` | string | yes | Built-in id or external theme display id. |
| `extends` | string | no | Empty means no parent. Built-ins may extend only built-ins. External files may extend built-ins by id. |

Unknown top-level keys are invalid.

## `[capabilities]`

| Key | Values | Default |
| --- | --- | --- |
| `color` | `none`, `ansi`, `ansi256`, `truecolor` | `ansi` |
| `glyphs` | `ascii`, `nerd-font` | `ascii` |

The renderer must downgrade to terminal capabilities at runtime. `glyphs = "nerd-font"` requires every glyph-bearing segment to also define `ascii`.

## `[palette]`

Palette values are strings:

- ANSI indexes: `"0"` through `"15"`.
- ANSI-256 indexes: `"16"` through `"255"`.
- Truecolor hex: `"#RRGGBB"`.
- Oklab: `"oklab(0.72 0.04 -0.08)"`; lightness also accepts percent.
- Oklch: `"oklch(72% 0.12 240deg)"`; hue accepts bare degrees, `deg`, `rad`, or `turn`.
- Palette references: `"@accent"`.

References resolve inside the final inherited palette. Cycles are invalid.

Required semantic slots:

| Slot | Use |
| --- | --- |
| `fg` | Default prompt foreground. |
| `muted` | Low-emphasis metadata. |
| `accent` | Current working context. |
| `success` | OK state. |
| `warning` | Slow or risky state. |
| `danger` | Error state. |

Themes may add custom palette slots, but custom slots must be referenced at least once.

## `[separators]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `segment` | string | `" "` | Inserted between rendered segments. |
| `left` | string | `""` | Optional prefix for every segment. |
| `right` | string | `""` | Optional suffix for every segment. |

Separators are plain strings. Color is inherited from the segment unless a later schema adds separator-specific style.

## `[segments.<id>]`

Segment ids are core module ids or plugin module ids.

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `fg` | color ref | no | Empty means default foreground. |
| `bg` | color ref | no | Empty means no background color. |
| `style` | string | no | Space-separated `bold`, `dim`, `italic`, `underline`. |
| `glyph` | string | no | Preferred glyph for rich terminals. |
| `ascii` | string | no | ASCII fallback. Required when `glyph` is non-empty. |
| `prefix` | string | no | Text before segment content. |
| `suffix` | string | no | Text after segment content. |

Unknown keys are invalid.

## Inheritance

Inheritance is a shallow table merge:

1. Load parent.
2. Replace top-level scalar keys from child.
3. Merge `[palette]`, `[separators]`, and `[segments.<id>]` by key.
4. Validate the final theme.

Parent cycles are invalid.

## Validation Rules

- `version` must be `1`.
- `name` must match `[a-z0-9][a-z0-9_-]*`.
- Palette refs must resolve to concrete colors.
- Palette refs may not form cycles.
- Contrast checks use Oklab lightness deltas for perceptual diagnostics and WCAG ratios for AA thresholds.
- Segment color fields must be empty or valid palette refs/concrete colors.
- `style` may contain only known style tokens.
- Non-ASCII `glyph` requires `ascii`.
- Built-in themes must not require `truecolor`; they must render acceptably at `ansi256` or lower.
- A theme must define segment styles for `cwd`, `git_branch`, `exit_status`, `jobs`, and `cmd_duration`.
