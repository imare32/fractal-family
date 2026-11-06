"""Sidebar (N panel) "Fractal": generate, gene list, preview settings, status.

The panel only reads ``scene.fractalfamily``; it never computes geometry.  Every string
passed to ``label``/``operator`` goes through :func:`i18n.t` — Blender does not translate
text supplied by Python code (RNA names, enum items and operator labels are translated
automatically and therefore stay plain literals).
"""

from __future__ import annotations

import unicodedata

import bpy

from . import budget, hud, preview, sysinfo
from .i18n import t, tfmt
from .ops import (
    FRACTALFAMILY_OT_clear_notice,
    FRACTALFAMILY_OT_clear_request,
    FRACTALFAMILY_OT_generate,
    FRACTALFAMILY_OT_hud,
    FRACTALFAMILY_OT_item_add,
    FRACTALFAMILY_OT_item_move,
    FRACTALFAMILY_OT_item_remove,
    FRACTALFAMILY_OT_request_generate,
    FRACTALFAMILY_OT_set_domain,
    FRACTALFAMILY_OT_setup_scene,
)
from .props import INITIATOR_SIDES

__all__ = [
    "CATEGORY",
    "FRACTALFAMILY_PT_gene_help",
    "FRACTALFAMILY_PT_initiator_help",
    "FRACTALFAMILY_PT_panel",
    "FRACTALFAMILY_UL_items",
]

#: Sidebar tab name (kept short so it fits next to other add-ons' single-line tabs).
CATEGORY = "Fractal"

#: Popover width in UI units (Blender's ``UI_UNIT_X`` is 20 px at 100 % UI scale).
#: Measured against the real box: 20 units came out 480 px wide at UI scale 1.2 while a
#: 52 character line only reached 296 px -- the right third of the popover sat empty.  17
#: units is the width where a 52 character line *just* fits, which is also a comfortable
#: measure to read; the line break itself is computed against the box by :func:`_help_width`.
HELP_UNITS = 17

#: Characters per line to aim for when the UI font cannot be measured (background runs).
HELP_WIDTH = 52

#: UIList idname.
LIST_IDNAME = "FRACTALFAMILY_UL_items"


def _char_width(char: str) -> int:
    """1 for latin/punctuation, 2 for CJK and other wide glyphs (popover text width)."""
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def _help_width(text: str) -> int:
    """How many character units of *text* fit the popover, measured in the UI font.

    The box is fixed in UI units, so how many characters fit depends on the font and the UI
    scale -- a hard coded count looked right on one machine and left an empty right third on
    the next.  Both the box and the font scale with the UI, so measuring the real sentence
    against the real box gives the same answer everywhere.

    Measuring *this* sentence matters: a sample of ``n`` overestimates the average glyph
    (``n`` is one of the widest letters, and spaces are half of it), which is exactly how the
    first attempt ended up wrapping far too early.  :data:`HELP_WIDTH` is the fallback for
    background runs, where there is no font to measure.
    """
    total = sum(map(_char_width, text))
    try:
        import blf
    except ImportError:  # pragma: no cover - blf ships with Blender
        return HELP_WIDTH
    try:
        scale = bpy.context.preferences.system.ui_scale
        # 20 px per unit, minus the inner padding on both sides (measured: ~10 px each).
        available = (HELP_UNITS * 20.0 - 20.0) * scale
        measured = blf.dimensions(0, text)[0]
    except (AttributeError, TypeError, RuntimeError, ValueError):
        return HELP_WIDTH
    if measured <= 0.0 or not total:
        return HELP_WIDTH
    # 3 % slack: the last glyph of a line is followed by the box edge, not by a margin.
    width = int(available / (measured / total) * 0.97)
    # Outside this band the font was not really measured: in background mode ``blf`` answers
    # with a stub metric, which would claim hundreds of characters fit.
    return width if 30 <= width <= 100 else HELP_WIDTH


def _wrap_help(text: str, width: int = HELP_WIDTH) -> list[str]:
    """Split a help sentence into popover lines.

    Latin breaks on spaces; a CJK run has no spaces at all, so it is cut by display width
    instead -- ``textwrap`` would leave a Chinese sentence as one very wide line.  The cut
    never adds a space of its own: the pieces of one word are glued back together, which is
    what keeps a wrapped Chinese sentence readable.
    """
    lines: list[str] = []
    current, used = "", 0
    for word in text.split(" "):
        if not word:
            continue
        pieces: list[str] = []
        while sum(map(_char_width, word)) > width:
            cut, cut_width = "", 0
            for char in word:
                if cut_width + _char_width(char) > width:
                    break
                cut += char
                cut_width += _char_width(char)
            pieces.append(cut)
            word = word[len(cut):]
        if word:
            pieces.append(word)
        for index, piece in enumerate(pieces):
            # Only the first piece of a word is preceded by the space it was split on.
            glue = " " if index == 0 and current else ""
            size = sum(map(_char_width, piece))
            if current and used + len(glue) + size > width:
                lines.append(current)
                current, used = "", 0
                glue = ""
            current = f"{current}{glue}{piece}"
            used += len(glue) + size
    if current:
        lines.append(current)
    return lines


class _HelpPopover:
    """A ``?`` that opens its explanation **in place**, anchored to the button.

    A panel in the ``HEADER`` region is never drawn in the sidebar: it exists only as the
    popover that :meth:`bpy.types.UILayout.popover` opens, so the sentence shows up under
    the click instead of at the far end of the window in the status bar -- and it stays
    until you click away, unlike a report that the next message overwrites.
    """

    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    #: Popover width.  It has to be set on the panel -- wrapping in the text alone cannot
    #: widen the box, and without it the popover picks a narrow default that elides every
    #: line with "...".  The line break is then computed against this width by
    #: :func:`_help_width`, so the two never drift apart.
    bl_ui_units_x = HELP_UNITS

    #: Explanation, translated when the popover is drawn.
    explanation = ""

    def draw(self, context):
        explanation = t(self.explanation)
        for line in _wrap_help(explanation, _help_width(explanation)):
            self.layout.label(text=line)


class FRACTALFAMILY_PT_gene_help(_HelpPopover, bpy.types.Panel):
    """Explains the word "gene" right where the question mark was clicked."""

    bl_label = "What Is a Gene?"
    explanation = ("A gene is a short list of integer segments: each one says where the "
                   "next copy of the curve goes. Applied again and again, it grows into "
                   "the fractal. The HUD edits this same gene and stays in sync with the "
                   "panel — dragging it in the viewport is the more direct way to try one.")


class FRACTALFAMILY_PT_initiator_help(_HelpPopover, bpy.types.Panel):
    """Explains the initiator: the shape the substitution is applied to first."""

    bl_label = "What Is the Initiator?"
    explanation = ("The initiator is the shape the gene is first applied to: level 0. A "
                   "straight line grows an open fractal, while a polygon closes it — that "
                   "is how a Koch snowflake or a Gosper island comes out in one click.")


#: ``layout.popover`` wants the panel's *registered* idname, and for a ``Panel`` that is its
#: class name -- ``bl_idname`` only appears on RNA after registration, not on the class.
GENE_HELP_PANEL = FRACTALFAMILY_PT_gene_help.__name__
INITIATOR_HELP_PANEL = FRACTALFAMILY_PT_initiator_help.__name__


def _help_row(row, title: str, help_panel: str, icon: str = "NONE"):
    """Title on the left, a ``?`` at the right end of the same row.

    The label is left un-capped on purpose: a plain row stretches it across the free space,
    which is what parks the button at the right edge.  Do **not** set ``alignment="LEFT"``
    here -- that pulls the button up against the text, and every help row in the panel puts
    it at the right end instead.
    """
    row.label(text=t(title), icon=icon)
    row.popover(help_panel, text="", icon="QUESTION")


def _box(layout, title: str, icon: str = "NONE", help_panel: str = ""):
    """A box whose first row is the section title.

    ``use_property_split`` is turned off on purpose: with it the label column takes ~40%
    of a 300 px panel and leaves controls with half a row.

    ``help_panel`` adds a ``?`` button at the **right end of the title row** (see
    :func:`_help_row`); clicking it opens the explanation as a popover right there.
    """
    box = layout.box()
    box.use_property_split = False
    box.use_property_decorate = False
    if not help_panel:
        box.label(text=t(title), icon=icon)
        return box
    _help_row(box.row(align=True), title, help_panel, icon)
    return box


# A ``UIList`` has no ``bl_description``: its docstring *is* the tooltip, so it must stay
# user-facing (same for panels, which do have the property but read the docstring anyway).
class FRACTALFAMILY_UL_items(bpy.types.UIList):
    """One row per segment: the two integers A and B, plus the R and M flags."""

    bl_idname = LIST_IDNAME

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index, flt_flag):
        row = layout.row(align=True)
        row.label(text=f"#{index + 1:2d}")
        row.prop(item, "a", text="")
        row.prop(item, "b", text="")
        row.separator()
        row.prop(
            item, "reverse", text="", emboss=False,
            icon="UV_SYNC_SELECT" if item.reverse else "PROP_OFF",
        )
        row.prop(
            item, "mirror", text="", emboss=False,
            icon="MOD_MIRROR" if item.mirror else "PROP_OFF",
        )


def _hud(layout, settings):
    box = _box(layout, "Editing", "GREASEPENCIL")
    # Both viewport switches live in one row, at the top of the panel and at the same
    # size: the preview used to sit far down in its own box and was hard to find.
    # ``split(factor=0.5)`` gives the two buttons exactly half the width each — a plain
    # row sizes them by label length, which leaves them visibly different.
    split = box.split(factor=0.5, align=True)
    split.scale_y = 1.4
    # The label does not change: it is the *name* of the switch, and the highlight already
    # says whether it is on -- exactly like the Preview button next to it.  "HUD Editing" /
    # "Close HUD" made one switch read like two different commands.
    open_now = hud.session() is not None
    split.operator(
        FRACTALFAMILY_OT_hud.bl_idname,
        icon="WORKSPACE",
        text=t("HUD"),
        depress=open_now,
    )
    split.prop(settings, "show_preview", text=t("Preview"), toggle=True, icon="HIDE_OFF")


def _gene(layout, settings):
    # The `?` at the right end of the title row explains the word: clicking it opens the
    # sentence in a popover under the button, so nothing is unfolded and no state is kept.
    box = _box(layout, "Gene", "RNA", GENE_HELP_PANEL)
    box.prop(settings, "preset", text=t("Preset"))
    # Domain: two plain buttons with ``depress`` marking the current value.  An expanded
    # enum draws as two unlabelled buttons in 5.2 (labels get swallowed).
    row = box.row(align=True)
    for value, text in (("G", "Gaussian G"), ("E", "Eisenstein E")):
        row.operator(
            FRACTALFAMILY_OT_set_domain.bl_idname, text=t(text),
            depress=settings.domain == value,
        ).domain = value

    row = box.row()
    row.template_list(
        LIST_IDNAME, "FRACTALFAMILY_ITEMS", settings, "items", settings, "active_index", rows=3
    )
    column = row.column(align=True)
    column.operator(FRACTALFAMILY_OT_item_add.bl_idname, icon="ADD", text="")
    column.operator(FRACTALFAMILY_OT_item_remove.bl_idname, icon="REMOVE", text="")
    column.separator()
    column.operator(FRACTALFAMILY_OT_item_move.bl_idname, icon="TRIA_UP", text="").direction = "UP"
    column.operator(FRACTALFAMILY_OT_item_move.bl_idname, icon="TRIA_DOWN", text="").direction = "DOWN"

    # Copy / Paste Gene would need the ``clipboard`` permission, which 2.0.0 deliberately
    # ships without (see the manifest): the buttons come back together with the permission.
    box.label(text=settings.family_name(), icon="FILE_PARENT")

    if not settings.is_valid():
        box.label(text=t("Invalid gene: at least two segments and a non-zero total vector"),
                  icon="ERROR")


def _shape(layout, settings):
    # The `?` rides the title row, like Gene's: the box is already called "Level &
    # Initiator", so a separate "Initiator" row above the shape buttons only repeated the
    # word and cost a full row of the narrow panel.
    box = _box(layout, "Level & Initiator", "MOD_SUBSURF", INITIATOR_HELP_PANEL)
    # Level: what you are editing and what the HUD/preview show (the wheel changes it).
    # The output range lives in the Generate section, hidden until switched on.
    # Plain number field (not a slider): the ‹ › step arrows are exactly the ±1 needed.
    box.prop(settings, "level")
    if settings.show_preview and settings.preview_truncated():
        box.label(text=tfmt("Preview stops at level {limit}", limit=settings.preview_level()),
                  icon="INFO")
    # Initiator: straight line on its own row, polygons on the next one.  Short labels
    # ("3-gon" ...) because five options share ~49 px each.
    column = box.column(align=True)
    column.enabled = not settings.initiator_custom
    column.row(align=True).prop_enum(settings, "initiator_shape", "LINE", text=t("Line"))
    polygons = column.row(align=True)
    for identifier, sides in INITIATOR_SIDES.items():
        polygons.prop_enum(
            settings, "initiator_shape", identifier, text=tfmt("{sides}-gon", sides=sides)
        )
    # A checkbox on a row of its own: it applies to every initiator, including the straight
    # line (which then grows from the total vector back to the origin).  Not a full-width
    # toggle button -- that read as a *mode* next to the shape buttons above it.
    box.prop(settings, "initiator_reverse", text=t("Reverse Initiator Direction"))

    # A custom curve object is the other way to define the initiator.
    box.prop(settings, "initiator_custom")
    if settings.initiator_custom:
        box.prop(settings, "initiator_curve", text=t("Curve"))
        if settings.initiator_curve is None:
            box.label(text=t("No curve selected: currently a straight line"), icon="ERROR")


def _size(megabytes: float) -> str:
    """``12 kB`` / ``260 MB`` / ``1.5 GB`` — matches the wording in :mod:`ops`."""
    if megabytes >= 1024.0:
        return f"{megabytes / 1024.0:.1f} GB"
    if megabytes >= 1.0:
        return f"{megabytes:.0f} MB"
    return f"{megabytes * 1024.0:.0f} kB"


def _seconds(value: float) -> str:
    """``0.15 s`` / ``1.5 s`` — two decimals below a second, one above."""
    if value < 0.01:
        return "<0.01 s"
    return f"{value:.2f} s" if value < 1.0 else f"{value:.1f} s"


def _cost(settings, level: int) -> str:
    """One line: what Generate will write, how long it takes, how much memory it needs.

    Everything here is arithmetic on the gene (no expansion): the panel must stay cheap.
    """
    # The count shown is what the object will *contain*: for a level-range build that is the
    # whole ladder, not just the top level, and the time and memory are proportional to it.
    low = settings.level_range()[0]
    count = settings.estimate_written(level, low)
    seconds = settings.estimate_seconds(level)
    megabytes = settings.estimate_peak_mb(level)
    return tfmt("{count:,} points · {seconds} · {size}",
                count=count, seconds=_seconds(seconds), size=_size(megabytes))


def _progress(column, settings):
    """The running build, drawn where the buttons were.

    ``UILayout.progress`` is the native bar Blender uses for jobs, so the panel does not have
    to fake one out of a row of characters.  It exists in both 4.2 and 5.2, but only as an
    RNA function -- ``hasattr(layout, "progress")`` is False, so do not try to feature-test
    it that way.

    The bar covers **only the part that can be measured**: expanding the points.  It reaches
    100 % and then *goes away*, replaced by a plain line of text.

    That split is deliberate.  Blender's evaluation -- the step that turns the points into
    draw data, 65-90 % of the wait on a big build -- is a single atomic ``view_layer.update()``
    call.  Measured with a real window: **zero** timers fire while it runs, so the window
    cannot redraw even once; slicing it costs 2.4x and the longest slice is still the whole
    thing.  A bar sitting at 100 % through that reads as "done, why is nothing happening",
    which is worse than no bar at all.  A line of text that says what is going on is not a
    progress claim, so it cannot be wrong.
    """
    fraction = max(0.0, min(1.0, settings.running_fraction))
    if settings.running_eval_start <= 0.0:
        column.progress(
            factor=fraction,
            type="BAR",
            text=tfmt("Generating level {level} / {high} · {percent}%",
                      level=settings.running_level, high=settings.running_high,
                      percent=int(round(fraction * 100.0))),
        )
        column.label(text=t("ESC cancels"))
        return

    # No bar here: the wait is real but unmeasurable, so it is described instead of faked.
    # Two lines, not one: at ~250 px the sidebar clips the middle of a single
    # "Points done · preparing the viewport: 16,777,217 points" into
    # "Points done · pre...6,777,217 points" -- exactly the number that matters is left
    # half-eaten.  BLANK1 keeps the second line aligned under the first one's text.
    column.label(text=t("Points done · preparing the viewport"), icon="TIME")
    column.label(text=tfmt("{count:,} points", count=settings.running_points),
                 icon="BLANK1")


def _notice(box, settings):
    """What the last Generate actually did, when it is not what was asked for.

    It has to be persistent and next to the buttons: a ``report()`` message disappears
    after a few seconds and leaves the user wondering why the curve has less detail.  Kept
    to two lines and one button row -- the numbers behind the decision are already in the
    cost line above.
    """
    kind = settings.notice_kind
    if not kind:
        return
    requested = int(settings.notice_requested)
    actual = int(settings.notice_actual)
    column = box.column(align=True)

    if kind == "PREVIEW_ONLY":
        # ``settings.error`` already carries the full sentence.
        column.label(text=settings.error or t("Not enough memory for this level"), icon="ERROR")
        return
    if kind == "FORCED":
        column.label(text=tfmt("Wrote level {actual} over the budget", actual=actual),
                     icon="ERROR")
        return
    if kind == "REFUSED":
        # ``settings.error`` names the level, the size and the free memory.
        column.label(text=settings.error or t("This level cannot be generated"),
                     icon="ERROR")
        return

    column.label(text=tfmt("Wrote level {actual}, not {requested}",
                           actual=actual, requested=requested), icon="ERROR")
    # No "level N anyway" here.  Over budget is decided *before* anything is written now
    # (:func:`_choice`), and this leftover from the old silent-degradation flow named a
    # level it did not carry in its operator: changing Level or Output Range between the
    # notice and the click made it write a completely different build.  The choice row is
    # the only place that may insist.
    column.operator(FRACTALFAMILY_OT_clear_notice.bl_idname, text=t("Keep"))


def _choice(column, settings):
    """The two answers to "your requested level is over budget".

    Drawn **in place of** the Generate buttons, so the user's eye never leaves the row they
    just clicked.  ``REFUSE`` omits the insist button entirely -- see :func:`_choice_detail`.
    """
    keys = settings.pending_generate == "KEYS"
    state, _reason, _safe, info = settings.output_verdict(keys=keys)

    # One decision per row.  Three buttons side by side in a ~250 px sidebar truncated both
    # labels to "Generate lev..." / "Level 24 any...", which is exactly the wrong place to
    # be vague: the user is choosing between a safe build and a risky one.
    degrade = column.operator(FRACTALFAMILY_OT_generate.bl_idname,
                              text=tfmt("Generate level {level}", level=info["allowed"]),
                              icon="CHECKMARK")
    degrade.keys = keys
    degrade.force = False
    degrade.level = info["allowed"]

    if state != budget.REFUSE:
        insist = column.operator(FRACTALFAMILY_OT_generate.bl_idname,
                                 text=tfmt("Level {level} anyway", level=info["level"]),
                                 icon="ERROR")
        insist.keys = keys
        insist.force = True
        insist.level = info["level"]


def _choice_detail(box, settings):
    """Why the question is being asked, with the numbers that make it answerable."""
    keys = settings.pending_generate == "KEYS"
    state, reason, safe, info = settings.output_verdict(keys=keys)
    column = box.column(align=True)
    if state == budget.REFUSE and reason == budget.REFUSE_MEMORY:
        column.label(text=t("Not enough memory"), icon="ERROR")
        column.label(text=tfmt("Level {level} needs {size}, {avail} free",
                               level=info["level"], size=_size(info["needed_mb"]),
                               avail=_size(info["available_mb"])))
        column.label(text=t("Generating it anyway is not offered"), icon="INFO")
    elif state == budget.REFUSE:
        column.label(text=t("Build would take too long"), icon="ERROR")
        column.label(text=tfmt("About {minutes} min · generating anyway is not offered",
                               minutes=int(round(info["seconds"] / 60.0))))
    else:
        column.label(text=tfmt("Level {level} · {size}",
                               level=info["level"], size=_size(info["needed_mb"])), icon="INFO")
        column.label(text=tfmt("About {seconds} · level {level} fits the budget",
                               seconds=_seconds(info["seconds"]), level=info["allowed"]))
    # Without this, greyed-out controls read as a broken panel rather than a decision in
    # progress.  The Cancel button below is the way out.
    column.label(text=t("Settings locked · Cancel to edit"), icon="INFO")
    column.separator()
    row = column.row(align=True)
    row.operator(FRACTALFAMILY_OT_clear_request.bl_idname, text=t("Cancel"), icon="X")


def _output(layout, settings, context):
    box = _box(layout, "Generate", "OUTLINER_OB_CURVE")
    # The choice row quotes memory and time for one particular configuration.  Freeze every
    # control that changes what Generate writes while that question is on screen: switching
    # Output Range on replaces ``level_range()`` with ``(level_from, level_to)`` and roughly
    # doubles the points, so an answer priced for a single level 24 would write a ladder.
    # Cancel (in :func:`_choice_detail`) is how you get back to editing.
    choosing = bool(settings.pending_generate)

    # Spline type belongs with the output, so it sits right above the button.  Expanded
    # enum (segmented buttons): two options, one click less than a dropdown, and the
    # current value stays visible.  Do **not** pass ``text=""``: the labels get swallowed
    # and only a blue highlight remains (5.2).
    box.label(text=t("Spline"))
    row = box.row(align=True)
    row.enabled = not choosing
    row.prop(settings, "spline_type", expand=True)

    # Output range: off by default (write the current level only). Switching it on reveals
    # the two range fields and enables Join Levels; it does not touch their values.
    row = box.row(align=True)
    row.enabled = not choosing
    row.prop(settings, "use_range", text=t("Output Range"))
    join = row.row(align=True)
    join.enabled = settings.use_range
    join.prop(settings, "join_objects", text=t("Join Levels"))
    if settings.use_range:
        row = box.row(align=True)
        row.enabled = not choosing
        row.prop(settings, "level_from")
        row.prop(settings, "level_to")

    # One line, three numbers: what the click writes, how long it takes, how much memory it
    # needs.  The machine's own limits live in the Status box -- quoting them here as well
    # is what made the panel read like a manual.
    over_budget = None
    if settings.is_valid():
        level = settings.level_range()[1]
        box.label(text=tfmt("Level {level} · {cost}", level=level,
                            cost=_cost(settings, level)), icon="PRESET")
        limit = settings.output_level_limit()
        if level > limit:
            over_budget = (limit, level)

    if settings.keys_truncated():
        box.label(text=tfmt("Shape keys ≤ level {limit}", limit=settings.shape_key_level()),
                  icon="INFO")

    # Two separate buttons: a curve with one spline per level, or one object that morphs
    # between levels through shape keys.  They ask first rather than silently writing less:
    # :func:`_choice` replaces this row with the two answers when the requested level is
    # over budget.
    column = box.column(align=True)
    column.scale_y = 1.3
    # While a build runs the two buttons are replaced by its progress: the row is where the
    # click just happened, and re-enabling them would invite a second modal on top of the
    # first (the operator would be re-invoked while its own timer is running).
    if settings.running_fraction >= 0.0:
        _progress(column, settings)
    elif settings.pending_generate:
        _choice(column, settings)
    else:
        button = column.operator(
            FRACTALFAMILY_OT_request_generate.bl_idname,
            text=t("Generate Curve"), icon="CURVE_DATA"
        )
        button.keys = False
        button = column.operator(
            FRACTALFAMILY_OT_request_generate.bl_idname,
            text=t("Generate Shape Keys"), icon="SHAPEKEY_DATA"
        )
        button.keys = True

    if settings.pending_generate:
        _choice_detail(box, settings)
        _notice(box, settings)
        return

    # Below the buttons, not above them: the sentence belongs to the click, so it reads as a
    # note on what that click will do -- after the user has found the button, not as a
    # footnote to the cost line that is skimmed past on the way there.
    if over_budget is not None:
        limit, level = over_budget
        box.label(text=t("Over budget"), icon="INFO")
        # A build that just came back short says the same numbers one line further down
        # ("Writes level 20, not 24" / "Wrote level 20, not 24").  Keep the header over it
        # and drop the future tense, so the panel speaks once instead of stuttering.
        squashed = (settings.notice_kind == "DEGRADED"
                    and int(settings.notice_requested) == level)
        if not squashed:
            box.label(text=tfmt("Would write level {limit}, not {level}",
                                limit=limit, level=level))

    _notice(box, settings)

    active = context.active_object
    keys = getattr(active.data, "shape_keys", None) if active is not None else None
    if keys is not None:
        box.prop(keys, "eval_time", text=t("Shape Key Time"))


def _preview(layout, settings):
    # The on/off switch itself lives at the top of the panel (see :func:`_hud`); this box
    # only holds what the preview should look like.
    box = _box(layout, "Viewport Preview", "HIDE_OFF")
    column = box.column()
    column.enabled = settings.show_preview
    # Expanded enum (segmented buttons) like the spline switch in Generate: two options,
    # one click less than a dropdown, and the current one stays visible.  Do **not** pass
    # ``text=""`` -- in 5.2 the labels get swallowed and only a blue highlight remains.
    column.label(text=t("Colour Ramp"))
    column.row(align=True).prop(settings, "preview_ramp", expand=True)
    if settings.preview_ramp == "MONO":
        column.prop(settings, "preview_colour")


def _status(layout, settings):
    """State, the last result, and the machine's budget -- one line each.

    The panel used to repeat the point count and the budget limits in three places (Level,
    Status, Generate); it now says each number once, in the box where it belongs.
    """
    box = _box(layout, "Status", "INFO")
    if settings.error:
        box.label(text=settings.error, icon="ERROR")
    elif settings.dirty:
        box.label(text=t("Changed"), icon="TIME")
    else:
        box.label(text=t("Up to date"), icon="CHECKMARK")

    if settings.last_points:
        low, high = int(settings.last_low), int(settings.last_level)
        box.label(
            text=tfmt("Last: L{levels} · {points:,} points · {ms:.0f} ms",
                      levels=str(high) if low == high else f"{low}-{high}",
                      points=settings.last_points, ms=settings.last_ms),
            icon="TIME",
        )

    # A gene that does not contract is not a fractal yet -- that is the one case worth a
    # permanent line.  On a healthy gene the ratio is noise; the HUD shows it on demand.
    if settings.is_valid() and settings.contraction() > 0.75:
        box.label(text=settings.contraction_note(),
                  icon="ERROR" if settings.contraction() > 0.9999 else "INFO")

    if settings.show_preview and preview.last_error():
        box.label(text=tfmt("Preview draw failed: {error}", error=preview.last_error()),
                  icon="ERROR")

    row = box.row()
    row.operator(FRACTALFAMILY_OT_setup_scene.bl_idname, icon="CAMERA_DATA",
                 text=t("Scene Setup"))

    # How much this machine can still build, as one number.  Not a setting: the budget is
    # derived from the memory reading behind this line (see ``budget.POLICY``), so there is
    # nothing here to choose -- only something to know, because it is the reason a level
    # gets reduced.
    available = sysinfo.available_bytes()
    if available is not None:
        box.label(text=tfmt("{size} free · up to {limit:,} points",
                            size=_size(available / 1048576.0),
                            limit=settings.output_budget()), icon="MEMORY")


class FRACTALFAMILY_PT_panel(bpy.types.Panel):
    """Fractal curves from a gene: level, output, preview and scene setup."""

    bl_idname = "FRACTALFAMILY_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_label = "Fractal Family"

    def draw(self, context):
        settings = context.scene.fractalfamily
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        _hud(layout, settings)
        _gene(layout, settings)
        _shape(layout, settings)
        _output(layout, settings, context)
        _preview(layout, settings)
        _status(layout, settings)
