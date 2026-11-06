# Fractal Family for Blender

[![Blender Extensions](https://img.shields.io/badge/Extensions-Fractal_Family-blue?logo=blender)](https://extensions.blender.org/add-ons/fractal-family/) ![Blender Version](https://img.shields.io/badge/Blender-4.2%2B-orange) ![License](https://img.shields.io/badge/License-GPL-green)

English · [简体中文](README.zh-CN.md)

Fractal Family generates fractal curves from a short list of complex integers. It is based
on [Jeffrey Ventrella's research](http://www.fractalcurves.com/familytree/): every curve in
the "family tree" is described by a small **gene**, and the fractal is what that gene grows
into when its substitution rule is applied over and over.

The panel lives in **3D Viewport → Sidebar (`N`) → Fractal**.

## What it does

A **gene** is a sequence of complex integers plus two transform flags per segment. Each
segment says where the next copy of the curve goes; the flags say whether that copy is
reversed or mirrored. Applying the substitution to a straight line once gives level 1;
applying it to *that* result gives level 2, and so on. The result is a **teragon** — the
polyline that passes through every level.

Two lattices are supported:

- **Gaussian (`G`)** — square lattice, complex integers `a + bi`.
- **Eisenstein (`E`)** — triangular lattice, `a + bω`; three-way junctions, hexagonal
  structures and Gosper-style curves come from here.

The gene's total vector (shown as **family**, e.g. `G(1, 1)`) describes where the whole
curve ends up, and different genes with the same total vector share a visual family.

Everything you can generate is one of two things:

1. **A curve** with one spline per level — good for rendering, extruding, converting to
   mesh, or using as a path. With **Output Range** off (the default) you get a single
   spline at the current level; with it on you get one object per level, or one object with
   one spline per level if you tick **Join Levels**.
2. **Shape keys** — one object whose base shape is the initiator and which carries one
   shape key per level, so animating **Evaluation Time** grows the fractal. This is the
   headline feature: a whole fractal growth animation as a single curve object.

While you design a gene you never have to generate anything: the **viewport preview** draws
the current level with immediate-mode rendering, so edits show up as you type or drag.

## Installation

Install **Fractal Family** from the Blender Extensions platform (Edit → Preferences →
Get Extensions), or use *Install from Disk* with a `.zip` built from this repository.
Requires Blender **4.2 LTS** or newer.

## User guide

### Quick start

1. Open the `Fractal` tab in the 3D viewport sidebar.
2. Pick a **Preset** — the dropdown groups them by family, e.g. `E(3, 2) Gosper Island`.
3. Set the **Level** (default 4) and press **Generate Curve**, or press **Generate Shape
   Keys** to get the morphing version.

Work in **Top View** (`Numpad 7`): the curves are generated on the XY plane.

### The gene

"Gene" is a strange word to meet in a curve add-on. Click the **`?`** at the right end of the
**Gene** title and the explanation opens in a popover right under the button, where it stays
until you click away: **a gene is a short list of integer segments, each saying where the next
copy of the curve goes; apply it over and over and it grows into the fractal.** It closes by
pointing at the HUD: that editor changes this same gene and stays in sync with the panel, and
dragging the nodes in the viewport is the more direct way to try one.

- **A / B** — the complex integer of a segment (real and imaginary part in `G`; in `E`, the
  coefficients of `1` and `ω`).
- **R (Reverse)** — traverse the previous level backwards for this segment.
- **M (Mirror)** — mirror the previous level for this segment.
- The list is ordered: the curve visits the segments in the order shown, starting at the
  origin. Dragging rows up/down reorders them.
- At least two segments are required, none may be zero-length, and the total vector must
  not be zero — otherwise the panel shows what is wrong instead of generating.

The **family** label under the list (`G(2, 1)`, `E(1, 0)`…) is the total vector of the
gene: it tells you where the curve ends and which family of curves you are in.

### Level and preview

**Level** is what you are editing and looking at; the HUD wheel changes this one. Level 0
is the initiator, level 1 is the gene itself, and every level above replaces each segment
with the whole previous level.

The **viewport preview** draws that level in the viewport while you edit. It needs no
Generate and creates no objects. Its depth is limited by a point budget rather than a fixed
number, so simple genes go deep and dense ones stop earlier: a two-segment gene such as
Dragon Curve previews up to level 16, a five-segment gene around level 7, a nine-segment
gene around level 5. When the preview has to stop below the requested level, the panel says
so.

**Preview** (top of the panel) switches the drawing on and off; it is off by default.
**Colour Ramp** chooses between one fixed colour per level and a single colour of your
choice.

### Initiator

The level-0 shape is what the first substitution is applied to. Click the **`?`** at the
right end of the **Level & Initiator** title and one sentence appears in a popover there:

> **The initiator is the shape the gene is first applied to: level 0. A straight line grows
> an open fractal, while a polygon closes it — that is how a Koch snowflake or a Gosper
> island comes out in one click.**

The choices are:

- **Line** (default) — from the origin to the total vector.
- **3-gon … 8-gon** — closed regular polygons, with the side length derived from the total
  vector, so closed fractals such as the Koch snowflake or a closed Gosper island need no
  hand-built curve.
- **Custom Initiator Curve** — any curve object's first spline (the object transform is
  ignored).

**Reverse Initiator Direction** reads the initiator backwards. For a line that means the
fractal grows from the total vector back to the origin (the same shape turned half a turn);
for polygons and custom curves it flips the direction the curve grows in, which is how you
get "inward" variants of a snowflake.

### Output: curve or shape keys

**Generate Curve** writes the current level (or the output range) as a curve with one
spline per level. The point count grows exponentially with the level (`segments × gene
segments ^ level`), so Generate works inside a **budget derived from this machine**: the
memory that is actually available, and a speed calibration measured once and kept in the
preferences. That comes out around 1.7 million points on a busy 8 GB laptop and 5–6 million
on a workstation. The panel shows both the limit and what the level you are about to
generate costs (`Level 6 · 1 000 001 points · about 0.15 s · about 260 MB`), before you
press anything.

Anything predicted to take longer than a third of a second runs **in steps**, and the
progress bar appears **where the Generate buttons were** — the same box, so the feedback is
where you just clicked rather than in a status line at the other end of the window. It reads
`Generating level 12 / 22 · 55 %`, with `ESC cancels` underneath, and `ESC` stops the build
and removes whatever had been written. Once the points are written the bar **goes away** and
a line of text takes over (`Points done · preparing the viewport: 4,194,305 points`):
Blender's own evaluation is a single uninterruptible step — an atomic C call during which
the window cannot even redraw — so there is no honest fraction to show for it, and a bar
parked at 100 % would read as "finished, why is nothing happening". A statement of fact
cannot be wrong; a fake percentage can. The curve is filled level by level as it is expanded,
so the peak is the current level plus the curve instead of the whole ladder — about half of
what it used to be, which is why the same budget now builds further. The last part of the
wait is Blender's own: once Generate returns, the dependency graph evaluates the new curve,
and that cannot be interrupted from Python.

Generate writes the curve you asked for and nothing else: it never hides, converts or moves
the result. A heavy curve is simply a heavy curve — orbit it, render it, or hide it yourself
with Blender's own tools.

The budget is **derived, not chosen**, and it answers exactly two questions: is there
enough free memory (a quarter of it, less a reserve), and is the wait still reasonable (ten
seconds including evaluation). Those are the only reasons a level ever gets reduced. Ten
seconds is generous on purpose — if you typed a big level you asked to wait, and past 0.35 s
the build is already a modal job with a progress line and `ESC`, so it is a visible wait
rather than a hang. There is no separate point ceiling: a machine that is fast enough and has
the memory is entitled to build the level you asked for. There is no budget setting anywhere — the Status
section prints the number it ended up with (`45.5 GB free · up to 6,622,516 points`), which
is also the reason a level gets reduced. The level field goes up to 24 for everybody;
Generate writes the highest level that fits under that point count, and says so.

**Over budget asks first, it does not silently write less.** When the requested level is
above this machine's budget, pressing **Generate Curve / Generate Shape Keys** writes
nothing; the panel offers two answers in place of the buttons — **Generate level 20** (the
level that fits the budget) and **Level 24 anyway** — with the memory and time each one
costs, plus **Cancel**. The chosen level applies to that one build only: the scene's
**Level** field is untouched, so the HUD and the preview keep showing what you are editing.
Objects are named after the level they actually hold; an insisted build also keeps the
original request in `fractalfamily_requested_level`.

**When "anyway" is not offered.** The budget is a *policy* (a quarter of free memory, ten
seconds) and you may disagree with it. Physical memory is not a policy. If the predicted
peak exceeds 85 % of the memory that is actually free right now, or the predicted build +
evaluation runs to about ten minutes, the panel shows only the level that fits and
**Cancel**, with the numbers that caused the refusal. The allocation happens inside a C
call that Python cannot interrupt: once the OS starts swapping, neither the progress bar
nor `ESC` brings the window back, so that is not a slow build, it is a frozen machine. The
wall applies to *every* path, a scripted `force=True` included. The post-build notice
is informational only — it no longer carries an "anyway" button, because the decision is
made before anything is written. Conversely, as long as it fits, a build far over the
budget is still your call: a sliced build has a progress bar and can be cancelled, which is
a visible wait rather than a hang.

**Generate Shape Keys** writes one object that morphs: the base shape is the initiator,
every level from 1 to the last becomes a key, and animating **Shape Key Time** (Evaluation
Time) grows the fractal from a straight line into the curve. Levels are subdivided so all
keys share the same vertex count. Shape keys always cover all levels, whatever the output
range is.

Shape keys are budgeted separately, because each key is a full copy of the curve (cost ≈
levels × points): the budget counts **total key points**, not points per key, so a
workstation reaches level 16 with Dragon while a small machine stops earlier. When the cap
applies, the panel says which level the keys will reach; shape-key splines are written in
bulk, which keeps the high end of that range usable.

The **Spline** switch chooses how each spline is written: *Poly* (straight segments) or
*Bézier* (automatic handles). These are Blender's own names for the two spline types, so the
panel uses the words the curve editor already uses two clicks away. A Bézier curve says so
in its object name (`Fractal L22 Bézier Line G(1, 1)`); Poly is the default and stays
unmarked, since a name is only worth a word when it tells you what you would not otherwise
know.

**Output Range** (off by default) writes several levels at once. Its two fields appear when
it is on; the start level defaults to 1. Each level becomes its own object unless **Join
Levels** is ticked, in which case the whole range goes into one object with one spline per
level, lowest first.

Every press of Generate adds a new object. If the name is already taken Blender appends
`.001`, and nothing that already exists is modified, so materials, modifiers or animation
you applied earlier survive.

### Editing in the viewport (HUD)

Press **HUD** at the top of the panel to edit the gene directly in the viewport; the button
stays highlighted while the panel is open, and pressing it again closes the panel.
Everything the HUD edits is the **same setting** as the sidebar panel — the two stay in sync,
so you can start a gene in one place and finish it in the other. Editing on top of the curve
is also the more direct of the two: what you drag is what you see.
The panel opens in the bottom-left corner — **above Blender's own *Adjust Last Operation*
panel**, so neither covers the other — and can be dragged anywhere from its title bar.
The `?` button in its title bar (*Fractal Gene Editor*) opens a help card with the same
controls:

| Action | Result |
| --- | --- |
| Drag a node | Move it to another lattice point (always snapped) |
| Click `R` / `M` on a segment | Toggle that segment's reverse / mirror flag |
| `Wheel` | Change the level |
| `Shift` + `Wheel` | Zoom the HUD lattice |
| `Tab` or `Q` | Switch Gaussian / Eisenstein domain |
| `A` | Append a segment |
| `X` or `Delete` | Remove the last segment |
| `F` | Fit the view |
| `Esc`, right click, or `×` | Close the HUD |
| Drag the title bar | Move the panel |

The HUD never takes over the viewport: it only captures keys and clicks while the pointer
is over the panel, so selection, navigation and shortcuts keep working everywhere else.

### Scene setup

**Scene Setup** frames the **selected** curve with an orthographic top-view camera, sets a
2048×2048 render and the Standard view transform so the curve renders in the colours shown
in the viewport. With nothing selected it falls back to the current preview.

### Object naming

Generated objects are named family first, then the curve (the preset name, or `Custom
Curve` when the gene matches none), then the level range and finally the initiator:

```
G(1, 1) Dragon Curve L4 3gon
E(2, 1) Custom Curve L2-4 6gon-rev
E(3, 0) Koch Curve L1-5 Shape-Keys Bézier
G(1, 1) Dragon Curve L4 Init:MySquare
```

The shape of the name is fixed, so it can be read at a glance whether or not a preset
matched. There is no prefix, and the default straight-line initiator is omitted — every
character goes to something that tells two results apart. `Shape-Keys` is spelled out
rather than shortened to `Keys`, and hyphenated so it stays one token: the outliner is the
only place it shows, and it has to be obvious that the object morphs instead of holding one
spline per level. A custom initiator is prefixed `Init:` so it cannot be mistaken for the
curve-name slot.

The name is a label, not a fingerprint: two different genes in the same family, with the
same range and initiator, produce the same name (the newer one gets `.001`).

## Localisation

The panel and the HUD follow Blender's interface language (Simplified Chinese is included).
The HUD falls back to English labels if the CJK font bundled with Blender is unavailable.

## Permissions

**No permissions.** The add-on generates geometry and stops there: it opens no files, makes
no network request and does not touch the clipboard. Turning points into a file is Blender's
job or your own — there are plenty of exporters for that.

Copy / Paste Gene as text would need the `clipboard` permission, so it is planned for a
follow-up version rather than for this one (see the changelog). 1.1.6 asked for nothing
either, so an update keeps the permission list exactly as it was.

The add-on also asks the operating system how much memory is free, to size the generation
budget (see *Output* above). That number is used locally and is never sent anywhere; no
network access is involved.

The measured speed factor is an ordinary add-on **preference**, which Blender stores in
its own preference file — that is why it survives a restart without the add-on touching the
disk, and why nothing is left behind when it is uninstalled. It is the only thing the
add-on stores: the budget has no setting to store. (The initiator curve you pick with
*Custom Initiator Curve* is read through Blender's data API, not from disk.)

## Limitations

- Edge-replacement fractals on complex-integer lattices on the XY plane only. Node
  replacement (e.g. the standard Hilbert curve) and L-systems are not supported.
- The preview is drawn in the viewport and does not appear in renders; renders use the
  generated curve objects.
- macOS/Metal ignores line widths above 1 px. The HUD draws its polyline as geometry
  instead of GL lines; in the 3D preview the level colour is the reliable cue.
- Custom initiators read the first spline only and ignore the object transform.
- Very high levels produce very many points; the panel warns but does not stop you.

## Changelog

See [CHANGELOG.md](CHANGELOG.md). License: GPL-3.0-or-later.
