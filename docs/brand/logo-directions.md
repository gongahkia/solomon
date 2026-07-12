# Shibahama logo directions

## Constraints

The mark must describe deliberate recall control, not destruction: source history remains while ordinary recall recedes. It avoids brains, erasers, robot heads, wave clip-art, and any reference to an existing AI brand. At 16 px, use the supplied one-colour mark only; do not render the wordmark below 96 px wide.

## Direction 1 — Shoreline ledger (selected)

Three horizontal, offset strokes form a shoreline and an archival stack. Their shared left edge is stable; the right ends recede in deliberate steps. The negative space therefore reads as selective availability rather than deletion.

- **Palette:** deep ink `#13202A`; tide `#2D7382`; sand `#D7B98A`; paper `#F7F4ED`.
- **Typography:** `IBM Plex Sans` Semibold for the wordmark; use tracking `-0.02em`; use sentence case only.
- **16 px:** use `docs/assets/shibahama-mark.svg` in a single colour. Its 2 px rounded strokes and 2 px gaps survive rasterisation.
- **SVG-ready construction:** use a `24 × 24` viewBox. Draw three `2 px` round-capped strokes at y=`7`, `12`, and `17`, each beginning at x=`4`; end them at x=`20`, `16`, and `12`. Keep the bounding-box clear space at least `2 px` on every side. The production asset uses `currentColor` so monochrome and dark-mode use need no derivative file.

## Direction 2 — Tidemark interval

An open rounded rectangle suggests a durable record. Two inset, receding horizontal lines stop short of its right side, making the current recall window visible without implying data loss.

- **Palette:** charcoal `#20252B`; sea glass `#4A9E95`; clay `#C66B4A`; mist `#E8ECE9`.
- **Typography:** `Manrope` SemiBold; tracking `-0.025em`; pair the mark to the left of the wordmark at a `1:3.5` mark-to-name width ratio.
- **16 px:** collapse to the outer interval plus one inset stroke; omit the second inset stroke below 20 px.
- **SVG-ready construction:** use a `24 × 24` viewBox. Make a `16 × 16` rounded outline from x=`4`, y=`4` with radius `4` and `2 px` stroke. Add `2 px` round-capped lines from x=`7` to `15` at y=`10` and from x=`7` to `12` at y=`15`. Reserve `3 px` clear space.

## Direction 3 — Memory islet

Three irregular but measured shore contours surround a central empty islet. Each contour has one intentional break aligned on the southeast edge: the memory remains as a trace, while recall narrows by policy.

- **Palette:** midnight `#102A43`; blue-green `#177E89`; copper `#C46A3A`; shell `#F3E9D2`.
- **Typography:** `Public Sans` Bold; normal tracking; use all-lowercase `shibahama` only in the lockup.
- **16 px:** reduce the mark to two contours and preserve the southeast break as a square `2 px` gap.
- **SVG-ready construction:** use a `24 × 24` viewBox. Use three non-intersecting `2 px` round-capped paths centred on `(12,12)`, with radii approximately `8`, `5.5`, and `3`. Stop each path between 35° and 65° from the positive x-axis. Keep contour spacing at least `2 px` and clear space `2 px`.

## Asset usage

Direction 1 is the repository mark. Use it alone for favicons and small app surfaces; pair it with the wordmark only where the product name is already legible. Do not add gradients, outlines, shadows, or separate coloured layers to the monochrome asset.
