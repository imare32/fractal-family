# Changelog

## 2.0.0

What changed compared to **1.1.6**, the previous published release.

### Highlights

- Genes are edited **in the viewport** (HUD) instead of a list in the sidebar.
- The preview is **drawn** in the viewport instead of being built from temporary objects.
- The two viewport switches (HUD editor / preview) share one row at the top of the panel.

### Added

- **A `?` at the right end of the Gene title** answers the one question a first-time user
  has: why does a curve add-on talk about genes? Clicking it opens **a popover anchored to
  the button** — in place, and it stays up until you click away. The sentence says the gene
  is a short list of integer segments, each one telling where the next copy of the curve
  goes, and that applying it over and over grows the fractal; it then points at the HUD,
  which edits the same gene and stays in sync, because dragging the nodes in the viewport is
  the more direct way to try one. A status-bar report was the first version and it read
  badly: the sentence appeared at the
  far end of the window and the next message overwrote it.
- **The same `?` on the Level & Initiator title row**, for the other piece of jargon in the
  panel: it says the initiator is the level-0 shape, and that a polygon initiator is what
  closes the curve (Koch snowflake, Gosper island). It rides the box title instead of a row
  of its own -- the title already says "Initiator", and a separate label row above the shape
  buttons cost the narrow panel a full line for a repeated word. Both buttons share one
  helper and one popover draw (a `Panel` in the `HEADER` region, so it never shows up as a
  second sidebar section), which makes a third explanation a one-line addition.
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

### Fixed

- **Chinese tooltips for every control in the panel.** RNA property descriptions were never
  put into the translation table, so in a Chinese UI every hover answered in English --
  `show_preview` was the one that got noticed. All fourteen drawn controls now have a
  translated name and tooltip, and `verify_ui.py` fails if a control the panel draws has no
  entry.
- **The `Range From` tooltip no longer contradicts `Join Levels`.** It claimed a wider range
  "puts every level into one object, one spline per level" -- that is what Join Levels does.
  Measured: range 1–3 with Join Levels off writes three objects, with it on one object with
  three splines; the tooltip now says so.
- **Click-scoped UI state is no longer saved into `.blend` files.** Saving during a build, or
  with the over-budget question open, used to reopen with `running_fraction = 1.0`: the panel
  drew the progress bar in place of the Generate buttons and no modal existed any more to
  clear it, so generation was unreachable until a restart. Progress, pending-question,
  notice and error fields now use `SKIP_SAVE`, and a `load_post` handler resets them in files
  written by older versions too. The gene, Level and last-result figures still travel with
  the file.
- **The post-build `Level N anyway` button is gone.** It was a leftover from the old
  silent-degradation flow and named a level it did not pass to the operator: changing Level
  or Output Range between the notice and the click wrote a different build (measured: the
  button said level 20, the click wrote level 8). Over budget is decided before anything is
  written now, so the notice is informational only. Along the same line, `request_generate`
  refuses to open a question while a build is running, every gene edit — including HUD
  segment edits made through collection methods — drops a pending question, and
  `clear_notice` clears the stale error text that otherwise sat in Status beside the next
  question.

- **An explicit level no longer writes a level ladder.** The over-budget choice buttons pass
  a one-off `level`, and `_prepare()` treated that like a shape-key build, whose levels start
  at 1. With **Output Range** off, `Generate level 20` / `Level 24 anyway` therefore wrote
  `Fractal L1-24 ...` — every level in one object — although the user had asked for one
  curve. Worse, the physical-memory wall priced only the top level while the job wrote the
  whole ladder (roughly twice the points for a two-segment gene), so both the quoted figure
  and the hard limit were wrong. A curve now takes its low end from **Output Range** (the
  level itself when the switch is off); only shape keys start at level 1.
  `output_verdict()` also accepts the low level the operator is about to write and prices
  that exact span, so the check and the job cannot silently disagree again.

- **The post-build "preparing the viewport" line no longer clips its point count.** In a
  ~250 px sidebar Blender cuts the *middle* of a long `label`, so
  `Points done · preparing the viewport: 16,777,217 points` rendered as
  `Points done · pre...6,777,217 points` — the number that matters was the part eaten.
  The count now has its own line, indented under the status text with a `BLANK1` icon.

- **Output settings are frozen while an over-budget build waits for an answer.** The choice
  row quotes memory and time for one configuration, yet **Output Range**, **Join Levels**,
  **Range From / To** and **Spline** were still clickable. Switching Output Range on replaces
  `level_range()` with `(level_from, level_to)` and roughly doubles the written points, so an
  answer priced for a single level 24 could have written an unpriced ladder. Those controls
  are now disabled until **Cancel**, with a *Settings locked · Cancel to edit* line saying
  why. Edits made outside the Generate box (Level, presets, gene segments, initiator — the
  HUD and scripts included) cannot be greyed out, so any of them drops the pending question
  instead of leaving stale numbers on screen.

### Changed

- **The HUD title bar reads *Fractal Gene Editor*.** It used to say *Fractal Gene*, which
  named the thing being shown but not what the panel does; the panel is an editor, and the
  word makes the relationship to the sidebar panel obvious. The help card and the gene
  popover now say it out loud as well: the HUD edits **the same settings** as the sidebar
  panel and the two stay in sync, so a gene can be started in one place and finished in the
  other — and editing on top of the curve is the more direct of the two, because what you
  drag is what you see.
- **Generate asks before writing less.** The old flow silently wrote the highest level that
  fit and left a `Wrote level 20, not 24` notice with a `Level 24 anyway` button; users
  reasonably objected to having spent several GB on a curve they never agreed to. Now the
  Generate buttons only *ask*: the panel offers the budget level and the requested level
  (with the memory and time each costs) plus **Cancel**, and writes nothing until one is
  chosen. The choice applies to that build alone — the scene's Level, HUD and preview do
  not move — so a scripted `EXEC_DEFAULT` still behaves as before.
- **"Anyway" now has a hard boundary.** The budget is a policy (25 % of free memory, ten
  seconds) and can be overridden; a build that exceeds 85 % of the memory *actually free
  right now*, or takes some ten minutes, cannot be. That level gets no insist button in
  the choice row or in the post-build notice, because the allocation is an uninterruptible
  C call: once the OS swaps, the progress bar and `ESC` cannot rescue the session. The
  check lives in `budget.verdict()` and is re-applied in `_prepare()` on the level that is
  about to be **written**, so it holds for curves, shape keys, and a scripted `force=True`
  alike. A build that fits but takes minutes is still the user's call — a sliced build is
  a visible, cancellable wait, not a hang.

- **The panel moved from the `Edit` category to its own `Fractal` category.** Look for it
  under `3D Viewport > Sidebar (N) > Fractal`.
- Settings are stored per scene (`scene.fractalfamily`) instead of on the window manager.
- The gene list shows each segment as `A` / `B` fields plus `R` / `M` buttons.
- **The spline switch uses Blender's own names**: `Poly` and `Bézier` instead of `Polyline`
  and `Smooth`. Blender calls the two spline types exactly that (`Spline.type`), and every
  language pack already translates them, so the panel no longer introduces a third pair of
  words for the same thing two clicks away from the curve editor.
- **Generation is defined by an optional output range** instead of three output modes.
  Without it (the default) Generate writes the **Level** you are looking at; enabling
  **Output Range** reveals `Range From` / `Range To` and writes **one object per level**.
  **Join Levels** (off by default) puts the whole range into one object instead, one spline
  per level. The range is output only — the HUD and the preview always use *Level* (the
  wheel changes it).
- **One Chinese word for the initiator: 初始折线.** The panel title already said that while
  the help popover said 初始形状 and the switch said 自定义初始曲线 -- each string had been
  translated on its own. Every one of them, plus `README.zh-CN.md`, now uses the panel's word;
  the only 曲线 left is the Curve datablock pointer, which is literally a curve.
- Generated objects are named **family first, then the curve, then the level range and the
  initiator**, e.g. `G(1, 1) Dragon Curve L4 3gon`. The curve slot holds the preset name, or
  `Custom Curve` when the gene matches none, so the shape of the name never changes and
  reads the same way as the preset dropdown. **No fixed prefix**, and the default
  straight-line initiator is omitted — the characters go to what tells two results apart.
  Shape keys are marked `Shape-Keys` in full, not `Keys`, and hyphenated so the marker
  stays one token among space separated ones: the outliner is the only place it shows, and
  the object has to be recognisable as the morphing one at a glance. A custom initiator is
  prefixed `Init:` (`… L4 Init:MySquare`) so it cannot be read as the curve-name slot. The
  level in the name is the one that was written, never the requested one. Each Generate
  creates a new object; a name collision gets Blender's `.001` suffix, and existing objects
  are never modified or removed.
- **The `Custom Curve` switch is now `Custom Initiator Curve`.** A gene that matches no
  preset names its object `Custom Curve`, so the two sat in the same words one click apart
  and meant different things: one is the initiator, the other is the identity of the gene.
  The initiator is the only one that gets "Initiator" in the label.
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
- `Bézier` output is budgeted separately (~6× the memory and ~8× the evaluation time per
  point), so it degrades at a lower level than `Poly` for the same gene. A `Bézier` curve
  also says so in its object name (`Fractal L22 Bézier Line G(1, 1)`); `Poly` is the default
  and carries no marker.
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
- **Ctrl+Z no longer takes the gene with it.** Undo restores a snapshot of the scene, and
  the gene only lands in such a snapshot when an operator writes it — the startup default
  and a preset picked from the dropdown both write it outside one. So on a fresh file the
  undo step behind the first Generate had an empty gene list, and undoing the curve also
  emptied the panel into `Invalid gene`. The gene is now read from the scene in `undo_pre`,
  kept in a module variable (the one place undo cannot reach, since it is not RNA), and put
  back by `undo_post` — but **only** if the list came back empty, so undoing a gene edit
  still steps back through its history.

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
