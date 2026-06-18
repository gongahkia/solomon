# Built-in Themes

Built-ins:

- `plain`
- `minimal-monochrome`
- `okiya-night`
- `okiya-day`
- `nord-dark`
- `gruvbox-rainbow`
- `tokyo-night`
- `pure`
- `a11y`

These files follow `docs/theme-spec.md` and are intended to be copied as starter external themes.

## Font Requirements

| Theme | Glyph capability | Minimum Nerd Fonts version |
| --- | --- | --- |
| `plain` | ASCII | none |
| `minimal-monochrome` | ASCII | none |
| `okiya-night` | ASCII | none |
| `okiya-day` | ASCII | none |
| `nord-dark` | ASCII | none |
| `gruvbox-rainbow` | ASCII | none |
| `tokyo-night` | ASCII | none |
| `pure` | ASCII | none |
| `a11y` | ASCII | none |

Built-in themes currently render without Nerd Fonts. Any future built-in that sets `glyphs = "nerd-font"` must list a concrete minimum Nerd Fonts version here and pass `shisa font check`.

CI runs `scripts/theme-preview-screenshots.sh` and uploads SVG previews from `zig-out/theme-previews`.
