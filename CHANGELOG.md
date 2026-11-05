# Changelog

## 2.0.0

What changed compared to **1.1.6**, the previous published release.

### Highlights

- Genes are edited **in the viewport** (HUD) instead of a list in the sidebar.
- The preview is **drawn** in the viewport instead of being built from temporary objects.
- The two viewport switches (HUD editor / preview) share one row at the top of the panel.

### Added

- **HUD gene editor**: opens in the bottom-left corner, above Blender's own *Adjust Last
  Operation* panel — it steps up by that panel's height, and gives the clearance up only in
  a viewport too short to hold both. Drag the gene nodes on the lattice (always snapped to
  integer points), click `R` / `M` on a segment to toggle its reverse / mirror flag, use
  the wheel for the level, `Shift`+wheel to zoom, `Tab` or `Q` for the domain, `A` to append
  a segment, `X` to remove the last one, `F` to fit, `Esc` / right click / `×` to close. It
  only captures input while the pointer is over the panel. The `?` button next to the
  domain switch opens a help card with these controls.
- **Immediate-mode viewport preview**: the current level is drawn with a `POST_VIEW` draw
  handler. No temporary objects, no hidden collection, nothing to select, delete or save.
  Each level keeps a fixed colour, and the dashed outline in the HUD uses the same one.
- **Preview level follows the point count** (~120 000 points, less on a machine with a
  small budget) instead of a fixed cap, so the Dragon curve previews up to level 16 while a
  7-segment gene stops at level 6.
- **Scene setup**: orthographic top-view camera framed on the selected curve, 2048×2048,
  Standard view transform.
- **Copy / Paste Gene** as text.
- **Polygon initiators**: triangle, square, pentagon, hexagon and octagon, with the side
  length derived from the total vector — closed fractals such as the Koch snowflake or a
  closed Gosper island need no hand-built curve.
- **Localisation**: the panel and the HUD follow Blender's interface language (Simplified
  Chinese included). The HUD falls back to English when the bundled CJK font is missing.
- **Per-machine point budget**: the output limits are derived from the memory available on
  this machine and a one-off speed calibration (~4 ms) instead of being one constant for
  everyone. The same add-on therefore stops at ~1.7 M points on an 8 GB laptop that is
  already busy and at ~4–5 M on a workstation. **There is no budget setting**: the policy is
  one fixed rule (a quarter of the free memory, ten seconds per click) and the
  Status section prints the resulting point count. The speed measurement is an add-on
  preference, so it survives a restart without touching the disk (no `files` permission,
  nothing left behind on uninstall) — and it is the only thing stored.
- **The level cap is 24**: the only limits are the point budget and the level field's own
  maximum. This is what lets a user on a large machine reach level 24, where the property
  used to stop the whole add-on at 20.
- **Cost preview** in the Generate section: `Level 6 · 1 000 001 points · about 0.15 s ·
  about 260 MB`, plus the limit for this machine. Pure arithmetic — nothing is expanded
  for it, and it is what tells you whether to wait before you click.
- **Graceful degradation**: asking for a level above the budget writes the highest level
  that *does* fit and says so, instead of refusing. The panel shows `Generated level 4
  (you asked for 6)`, the object is named after what it actually holds, and a
  `fractalfamily_requested_level` property keeps the original request on the object.
- **`Level N anyway`** — the escape hatch next to that notice, for users who know what they
  are asking of their machine. It is a single click: the button only exists inside the
  notice, names the level, and sits under the line that quotes the cost, so a second
  confirmation dialog would add nothing. Such an object is tagged `fractalfamily_over_budget`.
- **Progress and `ESC`**: a build predicted to take longer than a third of a second runs as
  a modal job in ~25 ms slices, and the progress bar replaces the two Generate buttons in
  their own row (`Generating level 12 / 22 · 55 %`, `ESC cancels` below it). The bar is
  weighted by the **points** each level writes, not by level count: levels grow
  geometrically, so an even split read 90 % while the expensive last level had not started
  — it looked like the build had finished, then froze. Measured on a two-segment level-22
  build: at 3 % of the work the old bar read 78 %, at 50 % it read 96 %.
  The evaluation that follows the build is **not** interruptible: it is one atomic
  `view_layer.update()`, and slicing it was measured at 2.4× the cost with the longest slice
  still whole, so no honest fraction exists for it. The bar therefore **ends** when the
  points are written and a line of text takes its place
  (`Points done · preparing the viewport: 12,582,912 points`), dropping the `ESC` hint —
  offering to cancel something that cannot be cancelled is worse than silence. A countdown
  was tried first and replaced: a number counting down to zero promises the curve is about to
  appear, and the last part of the wait belongs to Blender's dependency graph, which runs
  after the operator returns and is outside any prediction its timer can make. It used to be a
  status-bar string at the bottom-left of the window, far from the button that was pressed,
  and it kept the buttons live so a second click could start a second modal. `ESC` stops the
  build and removes the partially written curve. Faster builds run in one go — a progress
  bar for a 40 ms click would only flicker.

### Changed

- **The panel moved from the `Edit` category to its own `Fractal` category.** Look for it
  under `3D Viewport > Sidebar (N) > Fractal`.
- Settings are stored per scene (`scene.fractalfamily`) instead of on the window manager.
- The gene list shows each segment as `A` / `B` fields plus `R` / `M` buttons.
- **Generation is defined by an optional output range** instead of three output modes.
  Without it (the default) Generate writes the **Level** you are looking at; enabling
  **Output Range** reveals `Range From` / `Range To` and writes **one object per level**.
  **Join Levels** (off by default) puts the whole range into one object instead, one spline
  per level. The range is output only — the HUD and the preview always use *Level* (the
  wheel changes it).
- Generated objects are named from the level range, the initiator and the gene family, e.g.
  `Fractal L1-4 6gon-rev E(2, 1)`; an untouched preset also gets its name appended
  (`Fractal L4 Line G(1, 1) Dragon Curve`). The level in the name is the one that was
  written, never the requested one. Each Generate creates a new object; a name collision
  gets Blender's `.001` suffix, and existing objects are never modified or removed.
- **Shape-key output** (`Generate Shape Keys` button): one object whose base shape is the
  initiator (level 0) and which carries one key for every level from 1 to the last level —
  shape keys always cover all levels, while the plain curve follows the output range.
  Generating a curve and generating shape keys are two separate buttons. Shape keys are
  capped at level 16 and budgeted by **total key points** (cost is `levels × points`), so a
  workstation reaches level 16 with Dragon (level 14 under the old per-key cap) while a
  small machine stops lower; this keeps a high level from freezing Blender, and the panel
  reports the level they will reach. Keys use polyline splines with bulk coordinate writes,
  which makes the higher levels practical.
- **Both exponential outputs are now bounded.** A gene is limited to 256 segments, so a
  pasted gene cannot flood the HUD or the sidebar, and both outputs stay inside the
  per-machine point budget. **Generate Curve** writes the highest level that fits instead of
  freezing Blender (Dragon stops around level 21 on a 64 GB workstation; a nine-segment
  gene stops at level 6), and the panel says which level that is before you click.
- `Smooth` output is budgeted separately (~6× the memory and ~8× the evaluation time per
  point), so it degrades at a lower level than `Polyline` for the same gene.
- **Faster curves at high levels**: Bezier coordinates, handle types and handle positions,
  polyline coordinates and shape-key coordinates are written in bulk with `foreach_set`,
  and linear subdivision is vectorised. A level-14 smooth curve dropped from ~3.9 s to
  under 0.05 s; smooth shape keys stop growing quadratically.
- **Generation is streamed**: the curve datablock is created first and every level is
  appended as it is expanded, instead of holding the whole level ladder — and a second copy
  of it — until the end. Peak memory at level 24 (16.8 M points) dropped from 4.1 GB to
  2.0 GB, i.e. 255 → 126 bytes per point; a 2- and a 10-segment gene also come out 7–11 %
  faster. This is what makes the same budget build about twice as far, and what lets the
  partial result be thrown away cleanly on `ESC`.
- **Tooltips are written for users, not for the source.** Blender hands an operator's
  *entire* docstring to the tooltip when `bl_description` is missing, so the old ones showed
  source notes (`settings.notice_*`, `:data:` references, the modal slicing detail). Every
  operator now carries an explicit one-sentence `bl_description`, the notes moved into
  comments next to the class, and the panel and list docstrings — which have nothing else to
  fall back on — are one user-facing line each. A side effect: tooltips are now translated,
  because a docstring is never looked up in the translation table. `.workbuddy/bench/
  verify_docs.py` fails the build when a new operator forgets this.

### Removed

- The hidden `__fractalfamily_preview__` collection and its three preview curves.
- The old operators (`object.fractalfamily_create_teragon_curves` and the `fractalfamily.*`
  list operators). Generation is now `fractalfamily.generate`.

### Compatibility

- Blender 4.2 LTS and newer (tested on 4.2.23 and 5.2.2).
- Windows, macOS and Linux. Only the font bundled with Blender is loaded, so no
  platform-specific paths.
- One permission: `clipboard` (Paste Gene). No filesystem access: the add-on generates
  geometry and keeps its own state in Blender's preference file.
- macOS/Metal ignores line widths above 1 px; the HUD draws its polyline as geometry and
  the viewport preview conveys the level through colour.
