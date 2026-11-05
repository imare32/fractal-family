"""Generation: expand the teragon and write it as **one curve object**, one spline per level.

The object name describes the design — level range, initiator, gene family and, for an
untouched preset, the preset name::

    Fractal L4 Line G(1, 1) Dragon Curve
    Fractal L1-4 6gon-rev E(2, 1)

Generating always creates a **new** object.  If the name is already taken Blender appends
``.001``; nothing that already exists is modified or deleted, so materials, modifiers or
animation applied to an earlier result survive.

``Shape Keys`` builds one object with one key per level instead of one spline per level;
the spline type applies to every spline.

The build runs as a :class:`BuildJob` so it can be **stepped**: one level per call, with the
curve written as the levels arrive.  The modal Generate uses that to show progress and to
stop on ``ESC``; :func:`rebuild` runs the same job straight through.
"""

from __future__ import annotations

import time

import bpy

from . import curves
from .i18n import tfmt
from .lattice import FractalGenerator, teragon_iter
from .props import INITIATOR_SIDES

__all__ = [
    "BuildJob",
    "Canceled",
    "LEVEL_KEY",
    "OWNER_KEY",
    "REQUESTED_KEY",
    "object_name",
    "rebuild",
]

#: Marker on generated objects (the cleanup only touches objects carrying it).
OWNER_KEY = "fractalfamily_owner"
#: Top level of the generated range (handy for scripts and the panel).
LEVEL_KEY = "fractalfamily_level"
#: Set only when the budget forced a lower level than the user asked for.
REQUESTED_KEY = "fractalfamily_requested_level"
#: Name prefix.
NAME_PREFIX = "Fractal"

#: Blender truncates datablock names at 63 bytes; clamp a little earlier.
MAX_NAME = 58


def _target_collection(collection=None):
    """Where new objects are linked: the given collection > active one > scene root."""
    return collection or bpy.context.collection or bpy.context.scene.collection


def _initiator_token(settings) -> str:
    """Short, readable description of the initiator (part of the object name)."""
    if settings.initiator_custom:
        curve = settings.initiator_curve
        token = f"Curve:{curve.name}" if curve is not None else "Curve"
    else:
        sides = INITIATOR_SIDES.get(str(settings.initiator_shape))
        token = f"{sides}gon" if sides else "Line"
    if settings.initiator_reverse:
        token += "-rev"
    return token


def object_name(settings, keys: bool = False, levels=None) -> str:
    """``Fractal L<range>[ Keys][ Bézier] <initiator> <family>[ <preset>]``.

    The family (``G(1, 1)``) is short and readable where the raw gene is not.  If the gene
    still matches an untouched preset, the preset name is appended too, so the outliner
    reads like ``Fractal L4 Line G(1, 1) Dragon Curve``; an edited gene falls back to the
    family alone.  The ``Keys`` marker keeps the shape-key object apart from the plain one.

    ``Poly`` splines are the default and stay unmarked; a smooth curve carries ``Bézier``,
    because that is the difference you cannot see in the outliner -- two objects at the same
    level look identical by name and behave differently when you edit them.

    :param keys: shape-key output (the name describes its key range).
    :param levels: override the level span, e.g. ``(2, 2)`` for one object of a per-level
        output.
    """
    if levels is None:
        # The name describes what the object holds: shape keys may ignore the output range.
        levels = settings.keys_range() if keys else settings.level_range()
    low, high = levels
    levels_text = f"L{low}" if low == high else f"L{low}-{high}"
    mode = " Keys" if keys else ""
    # "Bézier" is the label Blender itself uses for a BEZIER spline, and it is spelled with
    # the accent in its own source; the name is datablock text, not interface text, so it
    # is not translated.
    smooth = " Bézier" if str(settings.spline_type) == "SMOOTH" else ""
    parts = [NAME_PREFIX, f"{levels_text}{mode}{smooth}", _initiator_token(settings),
             settings.family_name()]
    preset = settings.preset_name()
    if preset:
        parts.append(preset)
    # Blender truncates datablock names at 63 bytes; clamp here so the name we look up
    # later is exactly the name the object gets.
    return " ".join(parts)[:MAX_NAME]


def initiator_points(settings):
    """Initiator polyline ``(points, closed)``; ``(None, False)`` for a straight line."""
    return settings.initiator()


def _new_object(name: str, curve, collection=None):
    """Create a new object and let Blender resolve a name collision (``.001``).

    Nothing that already exists is touched: generating again adds another object, so
    materials, modifiers or animation applied to an earlier result survive.
    """
    obj = bpy.data.objects.new(name, curve)
    _target_collection(collection).objects.link(obj)
    return obj


def _build_shape_keys(settings, name, all_lines, low, high, closed, collection=None):
    """One object + one shape key per level (the morphing output).

    The **base shape is the initiator (level 0)**, so the animation always starts from the
    plain line; every level from ``low`` to ``high`` becomes a key (``low`` is 1 unless the
    range is allowed to affect the keys).  Each level is subdivided in shape-preserving
    fashion until all of them share the same vertex count — that equality is what lets the
    keys interpolate per vertex.  The base uses ``AUTO`` handles so the tangents follow the
    interpolated points.
    """
    subdivision = max(2, len(settings.items))
    spline_type = settings.spline_type

    def build(line, level, num_segments):
        if spline_type == "SMOOTH":
            return curves.create_curve_smooth(
                line, name=f"{name} L{level}", num_segments=num_segments, closed=closed
            )
        return curves.create_curve_poly(
            line, name=f"{name} L{level}", num_segments=num_segments, closed=closed
        )

    temp = [build(all_lines[0], 0, subdivision ** max(0, high))]
    for level in range(low, high + 1):
        temp.append(build(all_lines[level], level, subdivision ** max(0, high - level)))

    obj = _new_object(name, temp[0], collection)
    if spline_type == "SMOOTH":
        curves.set_handle_type(obj.data, "AUTO")
    try:
        obj.shape_key_add(name="Basis")
    except (RuntimeError, TypeError) as exc:
        for curve in temp:
            if curve.users == 0:
                bpy.data.curves.remove(curve)
        raise ValueError(f"this object type does not support shape keys: {exc}") from exc
    if obj.data.shape_keys is not None:
        # Absolute mode: Evaluation Time interpolates between the level shapes.
        obj.data.shape_keys.use_relative = False

    for offset, curve in enumerate(temp[1:], start=low):
        if not len(curve.splines):
            continue
        key = obj.shape_key_add(name=f"Level {offset}")
        if key is None:
            continue
        # Curve shape keys store coordinates only; handles come from the base shape.
        # ``foreach_set`` instead of a per-point Python loop: at level 14+ a key holds tens
        # of thousands of points and the loop was the slowest part of the build.
        curves.set_shape_key_coords(key, curves.spline_coords(curve))

    for curve in temp:
        if curve.users == 0:
            bpy.data.curves.remove(curve)
    return obj


class Canceled(Exception):
    """The caller stopped a build that was in progress (ESC in the modal Generate)."""


class BuildJob:
    """One Generate, done in steps instead of in one blocking call.

    :meth:`step` expands **one level** and writes it; the caller decides how often to call
    it.  The operator does that inside a modal timer in ~25 ms slices, which is what makes
    the wait visible and ``ESC`` responsive; :func:`rebuild` just runs it to the end.

    Plain output is **streamed**: the curve datablock is created up front and every level is
    appended as soon as it exists, so the peak is one level plus the curve rather than the
    whole ladder (the level cache alone used to be about half of it).  Shape keys are built
    in a single step at the end: their budget caps them at a fraction of a second on every
    machine, and the keys need every level at once anyway.
    """

    def __init__(self, settings, *, keys: bool = False, collection=None, levels=None,
                 requested: int | None = None):
        started = time.perf_counter()
        elements = settings.elements()
        if len(elements) < 2:
            raise ValueError("a gene needs at least two segments")
        if any(element.norm == 0 for element, _flags in elements):
            raise ValueError("the gene has a zero-length segment (adjacent nodes coincide)")
        if not settings.is_valid():
            raise ValueError("invalid gene: total vector is zero (nothing to expand into)")

        if levels is not None:
            low, high = int(levels[0]), int(levels[1])
        elif keys:
            low, high = settings.keys_range()
        else:
            low, high = settings.level_range()

        # The plain output is one copy of the curve, but its point count is exponential too
        # (``segments × count ** level``).  Past the budget the build cannot finish in
        # reasonable memory -- so refuse it and say which level still fits.  ``levels=``
        # skips this on purpose: that is the escape hatch for "generate it anyway".
        if levels is None and not keys and high > settings.output_level_limit():
            segments = max(1, settings.initiator_segments())
            raise ValueError(tfmt(
                "Level {level} needs about {count:,} points (limit {limit:,}); "
                "the highest level that fits is {max}",
                level=high, count=segments * max(1, len(elements)) ** high + 1,
                limit=settings.output_budget(), max=settings.output_level_limit(),
            ))

        self.settings = settings
        self.keys = bool(keys)
        self.collection = collection
        self.requested = None if requested is None else int(requested)
        self.low = low
        self.high = high
        # One object per level unless the levels are joined (shape keys always need the
        # whole ladder inside a single object).
        self.separate = bool(settings.use_range) and not settings.join_objects and not keys

        self.generator = FractalGenerator(elements)
        self._initiator, self.closed = initiator_points(settings)
        self._walker = teragon_iter(self.generator, high, self._initiator, self.closed)

        #: Levels 0..high are expanded (the ones below ``low`` are needed to reach ``high``).
        self.total = high + 1
        self.done = 0
        self.level = 0

        # Progress is weighted by **points**, not by level count: each level costs the level
        # before it times the segment count, so level 21 alone is half of the whole ladder
        # and level 2 is a rounding error.  Counting "9 of 22 levels" made the bar sit at
        # 40 % for one tick and then sprint -- it looked like the build had stalled, then
        # jumped.  The weights come from the same geometric series the point budget uses, so
        # the bar advances in proportion to the work, and the last level (the visible one)
        # gets the share it really takes.
        count = max(1, len(elements))
        self._weights = [count ** exponent for exponent in range(high + 1)]
        self._weight_total = max(1, sum(self._weights))
        self._weight_done = 0

        self._objects: list = []
        self._lines: list | None = [] if keys else None
        self._curve = None
        self._name = ""
        self._last_points = 0
        self._started = started

        if not keys and not self.separate:
            self._name = object_name(settings, levels=(low, high))
            self._curve = curves.new_curve(self._name)

    # --- progress ----------------------------------------------------------

    @property
    def fraction(self) -> float:
        """0..1, for a progress line, weighted by the number of points each level writes.

        Not ``done / total``: levels grow geometrically, so an even split shows most of the
        bar filled before any real work has happened and then freezes where the work is.
        """
        return self._weight_done / float(self._weight_total)

    @property
    def points_done(self) -> int:
        """Points already expanded -- also the weight behind :attr:`fraction`."""
        return self._weight_done

    def step(self) -> bool:
        """Expand and write the next level.  ``False`` once there is nothing left."""
        try:
            level, line = next(self._walker)
        except StopIteration:
            return False

        self.level = level
        self.done += 1
        if level < len(self._weights):
            self._weight_done += self._weights[level]
        if self.keys:
            # Shape keys need every level at once; collect and build them in ``finish``.
            self._lines.append(line)
        elif self.low <= level <= self.high:
            if self.separate:
                self._write_separate(level, line)
            else:
                curves.append_spline(self._curve, line, self.settings.spline_type, self.closed)
                self._last_points = len(line)
        return True

    def _write_separate(self, level: int, line) -> None:
        """One object for this level alone (``Output Range`` without ``Join Levels``)."""
        name = object_name(self.settings, levels=(level, level))
        curve = curves.create_curve(
            [line], name=name, spline_type=self.settings.spline_type, closed=self.closed
        )
        obj = _new_object(name, curve, self.collection)
        obj[OWNER_KEY] = "fractal"
        obj[LEVEL_KEY] = level
        self._objects.append(obj)
        self._last_points = len(line)

    def cancel(self) -> None:
        """Drop every datablock this job created.  Safe to call more than once."""
        if self._curve is not None and self._curve.users == 0:
            bpy.data.curves.remove(self._curve)
        self._curve = None
        for obj in self._objects:
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.curves.remove(data)
        self._objects = []
        if self._lines is not None:
            self._lines = []

    # --- completion --------------------------------------------------------

    def finish(self) -> dict:
        """Write the remaining datablocks and return the summary."""
        settings = self.settings

        if self.keys:
            # The name must carry the levels that were actually written: after a budget
            # degradation the requested level is *not* what this object holds.
            name = object_name(settings, keys=True, levels=(self.low, self.high))
            self._objects.append(_build_shape_keys(
                settings, name, self._lines, self.low, self.high, self.closed, self.collection
            ))
            if self._lines:
                self._last_points = len(self._lines[-1])
        elif not self.separate:
            self._objects.append(_new_object(self._name, self._curve, self.collection))

        for obj in self._objects:
            obj[OWNER_KEY] = "fractal"
            if obj.get(LEVEL_KEY) is None:
                obj[LEVEL_KEY] = self.high
            # Traceability: "why is this file lighter than I asked for".
            if self.requested is not None and self.requested != self.high:
                obj[REQUESTED_KEY] = self.requested
            obj.select_set(True)
        bpy.context.view_layer.objects.active = self._objects[-1]

        settings.last_points = self._last_points
        settings.last_low = self.low
        settings.last_level = self.high
        if self.requested is not None:
            settings.last_requested_level = self.requested
        settings.last_ms = (time.perf_counter() - self._started) * 1000.0
        settings.dirty = False

        first = self._objects[0]
        key_count = 0
        if first.data is not None and first.data.shape_keys is not None:
            key_count = max(0, len(first.data.shape_keys.key_blocks) - 1)
        return {
            "objects": self._objects,
            "splines": sum(len(obj.data.splines) for obj in self._objects if obj.data is not None),
            "keys": key_count,
            "separate": self.separate,
            "points": self._last_points,
            "low": self.low,
            "high": self.high,
            "ms": settings.last_ms,
        }


def rebuild(settings, *, keys: bool = False, collection=None, levels=None,
            requested: int | None = None, progress=None, cancelled=None) -> dict:
    """Rebuild the design, all the way through.

    :param keys: build shape keys (one per level) instead of one spline per level.
    :param levels: ``(low, high)`` to write, overriding :meth:`level_range`.  The caller
        uses this when the machine's budget only allows a lower level than requested --
        the object name and the ``last_level`` field must describe what was **actually**
        built, not what was asked for.
    :param requested: the level the user asked for, when it differs from ``levels``.
    :param progress: called as ``progress(done, total)`` after every level.
    :param cancelled: polled after every level; returning ``True`` aborts the build.
    :returns: ``{"objects", "splines", "keys", "points", "low", "high", "ms"}``.
    :raises Canceled: ``cancelled()`` returned ``True``; everything written so far is gone.
    :raises ValueError: invalid gene (fewer than two segments / zero-length segment / zero
        total vector), or a level above the point budget when ``levels`` was not given.
    """
    job = BuildJob(settings, keys=keys, collection=collection, levels=levels,
                   requested=requested)
    while job.step():
        if progress is not None:
            progress(job.done, job.total)
        if cancelled is not None and cancelled():
            job.cancel()
            raise Canceled("generation cancelled")
    return job.finish()
