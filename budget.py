"""How much geometry a single click may build on *this* machine.

The three budgets used to be constants (2 M points, 20 k per shape key, level 20).  On a
64 GB workstation those numbers used up about 1 % of the machine; on an 8 GB laptop with a
heavy scene open, 2 M points is already enough to push it into swapping.  Since the add-on
is installed from extensions.blender.org, both of those are somebody's real machine, so the
budget is derived instead of declared::

    reserve = max(0.8 GB, 15 % of total)
    usable  = max(0, available - reserve)
    budget  = min(usable * mem_fraction / bytes_per_point,
                  target_seconds * 1e9 / ns_per_point)

Time and memory are the only two reasons to reduce a level, and they bind on different
machines: a fast workstation runs out of *time* first, a small laptop runs out of *memory*
first.  Whichever is smaller decides, and either one alone is enough to leave the requested
level untouched -- there is deliberately no third, "sensible" ceiling.

Everything here is measured through the **real operator** on the reference machine
(i9-14900KF, Blender 5.2.2), so the figure is what the user actually waits for -- build plus
datablock creation plus dependency-graph evaluation.  The unit is one **written point**,
because that is what the cost is proportional to:

===================  ============  ================
path                 ns/written pt  bytes/written pt
===================  ============  ================
POLY, single level       169            260
POLY, level range        100            260
SMOOTH, single level   1 410          1 650
SMOOTH, level range      800          1 650
shape key                 89            118   (per key point)
===================  ============  ================

Two things about this table are worth stating plainly, because both were wrong before and
each made the panel quote roughly twice the real wait:

- **Written points, not the top level.**  A level-range build writes the whole ladder, which
  for a two-segment gene is twice its top level.  The old model multiplied an evaluation cost
  measured on range builds by the *top* level count, so a single-level L22 was predicted at
  4.0 s and ran in 2.1 s.
- **Two modes have different costs.**  A range build's lower levels are small and
  cache-resident; one huge spline is memory-bandwidth bound.  One constant cannot cover both
  -- hence the two rows.

Evaluation is the *larger* half of a POLY build (117 of the 169 ns for a single level), which
is why the panel's own "how long did that take" figure has to include it.  The shape-key row
never binds: the level cap is 16 and memory is checked first.

``ns`` values assume the reference machine; :func:`ensure_calibration` scales them by a
micro-benchmark so a slower CPU gets a smaller budget instead of a longer freeze.  The
benchmark measures the *small-build slope* (~45 ns/point, where the output still fits in
cache), so that slope -- not the 63 ns above -- is what it is compared against.

The measured factor is an ordinary *add-on preference*: Blender persists it in its own
preference file, so this add-on performs **no filesystem access at all** (no `files`
permission, no cache directory, nothing to clean up on uninstall).  It is the *only* thing
this module stores -- the budget itself has no setting, see :data:`POLICY`.
"""

from __future__ import annotations

import os
import platform
import time

import bpy

from . import sysinfo
from .i18n import t, tfmt

__all__ = [
    "FRACTALFAMILY_AP_preferences",
    "POLICY",
    "Snapshot",
    "build_seconds",
    "bytes_per_point",
    "eval_seconds",
    "cost_ns",
    "draw_preferences",
    "ensure_calibration",
    "estimate_mb",
    "estimate_seconds",
    "key_budget",
    "peak_points",
    "preview_budget",
    "snapshot",
    "speed_factor",
]

#: Cost of one **written** point on the reference machine (i9-14900KF, 5.2.2), measured
#: 2026-11-06 through the real operator so the figure includes everything the user waits
#: for -- build, datablock creation and dependency-graph evaluation:
#:
#: ===========  ==============  ==============  ==============
#: spline       single level    level range     memory
#: ===========  ==============  ==============  ==============
#: POLY            169 ns          100 ns        260 B
#: SMOOTH        1 410 ns          800 ns      1 650 B
#: ===========  ==============  ==============  ==============
#:
#: Two corrections are baked into these numbers, and both were sources of the estimate
#: being *twice* the real wait:
#:
#: 1. **The unit is the written point, not the top level.**  A level-range build writes
#:    the whole ladder (``1 + s + s² + …``), twice the top level for a two-segment gene.
#:    The old model multiplied an evaluation cost measured on *range* builds by the *top
#:    level* count, so a single-level L22 was predicted at 4.0 s and ran in 2.1 s.
#: 2. **A range build is cheaper per point than a single one** (100 vs 169 ns): the lower
#:    levels are small and their evaluation is dominated by cache-resident arrays, while a
#:    single huge spline pays memory bandwidth on every point.  One constant cannot cover
#:    both, so :func:`cost_ns` takes the mode.
POLY_NS = {"single": 163.0, "range": 97.0}
SMOOTH_NS = {"single": 1403.0, "range": 795.0}

#: The same measurement split into the two phases the user experiences differently: the
#: *build* is what the progress bar covers and what ``ESC`` can interrupt; the *evaluation*
#: happens inside the depsgraph after the operator returns and cannot be interrupted at all.
#: Evaluation is the larger half of a POLY build (117 of 163 ns) and almost all of a SMOOTH
#: one, which is why a bar that stops at the build looks like it hangs at 100 %.
POLY_BUILD_NS = {"single": 45.0, "range": 32.0}
POLY_EVAL_NS = {"single": 117.0, "range": 64.0}
SMOOTH_BUILD_NS = {"single": 142.0, "range": 130.0}
SMOOTH_EVAL_NS = {"single": 1260.0, "range": 665.0}

POLY_BYTES = 260.0
SMOOTH_BYTES = 1650.0

#: Per key point: a shape key stores its own copy of the curve, so the unit is again the
#: point actually allocated, and the build has to make every level at once.
KEY_NS = 89.0
KEY_BYTES = 118.0

#: Safety margins applied to the *gate* (not to the numbers shown to the user -- those
#: should match what actually happens; the margin belongs in the decision, not the report).
#: Bytes get a margin because the benchmark is headless (no viewport display buffers, no
#: undo copy); time does not, because the model already includes evaluation and the fit is
#: within ±8 %.
BYTES_MARGIN = 1.15
TIME_MARGIN = 1.0

#: Never go below this, whatever the formula says: a wrong reading must not brick the
#: add-on. 100 000 points is ~26 MB and a few milliseconds.
FLOOR_POINTS = 100_000

#: Used when the platform cannot report its memory at all (and kept as the historical
#: default the add-on applied everywhere before 2.1).
FALLBACK_POINTS = 2_000_000
FALLBACK_KEY_POINTS = 20_000

#: The small-build slope the calibration measures.  It is not a cost constant: at 65-260 k
#: points the build fits in cache and runs at ~45 ns/point, while a single six-million point
#: spline pays memory bandwidth and lands near 170.  It exists only to answer "how fast is
#: this CPU compared to the reference machine", so it must be the *same* measurement the
#: reference machine was calibrated against -- hence the single-level POLY figure below.
#:
#: Getting this wrong is subtle: comparing a 45 ns slope against the old 63 ns big-build
#: constant produced a factor of 1.4 on a machine that was actually at parity, and every
#: estimate in the panel inherited that error.
CALIBRATION_SLOPE_NS = 45.0

#: The budget policy -- one, fixed, and not a user setting.  A dropdown of "how much may I
#: build" asks the user to price their own time and their own RAM before they know what the
#: curve looks like; the add-on can read both.
#:
#: ``target_s``: how long a single Generate may block before the level is reduced.  Ten
#: seconds is deliberately generous: a user who typed a big level *chose* to wait, and the
#: modal job (progress line + `ESC`) starts at 0.35 s, so a few seconds is a visible,
#: cancellable wait rather than a hang.  Reducing a build the user asked for at three
#: seconds was answering a question they had not asked.
#: ``mem_fraction``: share of the *free* memory a build may take.  This is the other, and
#: only, reason to reduce: below 1.0 because Blender keeps growing after the build (undo copy
#: removed, but display data and the render follow).
#:
#: There is no separate point ceiling.  A ceiling would reduce the level *before* either of
#: those two rules fired, which is exactly what this policy is supposed to avoid; a machine
#: with enough memory and speed to reach the level is entitled to build it.
POLICY = {"target_s": 10.0, "mem_fraction": 0.25}

#: Preview is redrawn on every edit, so it gets a fraction of the output budget and a hard
#: ceiling of its own: 120 000 points is ~5 ms, and going much past that makes editing lag.
PREVIEW_CEILING = 120_000
PREVIEW_FLOOR = 30_000
PREVIEW_SHARE = 8

ENV_FAKE_NS = "FRACTALFAMILY_FAKE_NS_PER_POINT"

#: The measured factor is stored in the add-on preferences -- no file of our own -- so the
#: panel can show a budget before the first Generate.  It is *refreshed* every session
#: (see :func:`ensure_calibration`): a stored value describes the machine as it was when it
#: was measured, and one taken during a render can be 50 % off, which then shrinks every
#: budget until someone clears the preferences by hand.
#:
#: Bump this when the meaning of the stored number changes, so old values are discarded
#: instead of being reinterpreted.  1 -> 2: the divisor became ``CALIBRATION_SLOPE_NS``
#: (45 ns, measured at 65-260 k points) instead of the big-build cost (41 ns), and the
#: whole cost model was re-baselined.
CALIBRATION_VERSION = 2

#: Measured speed relative to the reference machine (1.0 = as measured).  ``measured`` says
#: whether the number came from *this* session or was adopted from the preferences: the
#: stored value is only there so the first paint has something to show, and it is replaced
#: by a fresh measurement on the first Generate.
_SPEED = {"factor": 1.0, "calibrated": False, "measured": False}


# ---------------------------------------------------------------------------
# Add-on preferences
# ---------------------------------------------------------------------------


def _preferences():
    """The add-on preferences object, or ``None`` when it is not registered."""
    try:
        addon = bpy.context.preferences.addons.get(__package__)
    except (AttributeError, TypeError):  # no preferences at all (background, shutdown)
        return None
    return getattr(addon, "preferences", None) if addon is not None else None


class Snapshot:
    """The current budget, plus where it came from (shown in the panel)."""

    __slots__ = ("points", "keys", "preview", "available", "total", "source")

    def __init__(self, points, keys, preview, available, total, source):
        self.points = points
        self.keys = keys
        self.preview = preview
        self.available = available
        self.total = total
        self.source = source

    def __repr__(self):
        return (f"Snapshot(points={self.points:,}, keys={self.keys:,}, "
                f"preview={self.preview:,}, source={self.source!r})")


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def speed_factor() -> float:
    """``1.0`` on the reference machine; ``2.0`` on a CPU that takes twice as long.

    Adopts a previously measured value on first use (from the preferences, so no disk), so
    the panel shows the right budget *before* the first Generate instead of assuming the
    speed of the reference machine.  That stored value is a *guess about the past*: it is
    replaced by a fresh measurement on the first Generate, because a factor measured while
    the machine was busy can be 50 % off and would then shrink every budget for weeks.
    """
    if not _SPEED["calibrated"]:
        stored = _stored_calibration()
        if stored is not None:
            _SPEED.update(factor=stored, calibrated=True)
    return _SPEED["factor"]


def ensure_calibration() -> float:
    """Time a tiny build once, then remember the scale factor.

    Measured **once per session** (the whole thing costs ~35 ms, paid on the first click):
    a factor measured weeks ago describes the machine as it was then, not the load it is
    under now.  It is still written to the add-on preferences, not to a file -- Blender
    persists preferences itself, so the add-on does no filesystem access -- but only so the
    panel has a number to show before the first Generate.

    The environment override is checked first so a pinned value wins even when a stored one
    has already been adopted by :func:`speed_factor`.

    Must not be called from ``draw()``: it creates and deletes a curve datablock, which is
    not allowed while the UI is being drawn.
    """
    override = _env_float(ENV_FAKE_NS, 0.0)
    if override > 0.0:
        _SPEED.update(factor=max(0.3, min(5.0, override / cost_ns("POLY"))),
                      calibrated=True)
        return _SPEED["factor"]

    if _SPEED["measured"]:
        return _SPEED["factor"]

    try:
        measured = _time_small_build()
    except Exception:  # a failed calibration must never break generation
        measured = 0.0
    if measured > 0.0:
        factor = max(0.3, min(5.0, measured / CALIBRATION_SLOPE_NS))
        _SPEED.update(factor=factor, calibrated=True, measured=True)
        _store_calibration(factor)
    elif not _SPEED["calibrated"]:
        # Measurement failed *and* nothing was stored: assume the reference machine.
        _SPEED.update(factor=1.0, calibrated=True)
    return _SPEED["factor"]


# ---------------------------------------------------------------------------
# The stored factor (add-on preferences, no file of our own)
# ---------------------------------------------------------------------------


def _machine_key() -> str:
    """Identifies "this machine + this Blender".

    A stored factor is only reused when the key matches, so moving the preferences to another
    computer (or upgrading Blender) re-measures instead of inheriting the old speed.  Every
    part is stringified: ``CALIBRATION_VERSION`` is an int.
    """
    parts = [CALIBRATION_VERSION, bpy.app.version_string, platform.machine(),
             os.cpu_count(), platform.processor()]
    return "|".join(str(part) for part in parts)


def _stored_calibration():
    """The persisted factor, or ``None`` when it is missing or from another machine."""
    prefs = _preferences()
    if prefs is None:
        return None
    try:
        if prefs.calibration_key != _machine_key():
            return None
        factor = float(prefs.calibration_factor)
    except (AttributeError, TypeError, ValueError):
        return None
    return factor if 0.3 <= factor <= 5.0 else None


def _store_calibration(factor: float) -> None:
    prefs = _preferences()
    if prefs is None:
        return  # development install without preferences: session-only, re-measured
    try:
        prefs.calibration_key = _machine_key()
        prefs.calibration_factor = factor
    except (AttributeError, TypeError, ValueError):
        pass


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


def _time_small_build() -> float:
    """``ns/point`` for a POLY build on this machine (0.0 when it cannot be measured).

    Two sizes, not one: a 1 000-point build is dominated by fixed costs (datablock
    creation, spline allocation, numpy call overhead) and reports ~3x the real per-point
    cost -- which would shrink the budget by the same factor on a machine that is
    perfectly fast.  The slope between 4 k and 65 k points cancels that fixed part.
    """
    from . import curves
    from .lattice import ComplexInteger, FractalGenerator, teragon

    elements = [(ComplexInteger(1, 0), (False, False)),
                (ComplexInteger(0, 1), (False, False))]

    def measure(level: int):
        """``(points, seconds)`` for one fresh build."""
        # A fresh generator each time: ``level_points`` caches every level, so reusing one
        # would measure the cache instead of the work.
        generator = FractalGenerator(elements)
        curve = None
        started = time.perf_counter()
        try:
            lines = teragon(generator, level)
            curve = curves.create_curve([lines[-1]], name="__fractal_calibration__")
            elapsed = time.perf_counter() - started
            points = len(lines[-1])
        finally:
            if curve is not None:
                bpy.data.curves.remove(curve)
            del generator
        return points, elapsed

    # Warm up three times, and at two sizes: the first builds of a session pay page-faults on
    # freshly mapped heap, populate the allocator's free lists and run numpy cold.  That cost
    # does not scale with the point count, so it lands in the *slope* -- the first run
    # measured 58.6 ns/point against 41-46 for every run after it, a 27 % error that every
    # estimate in the panel then inherits.
    for _ in range(3):
        measure(16)
    measure(18)

    # Median of three slopes, each from the best of three timings: the noise is one-sided
    # (something else can only make a build slower), so a minimum is the right statistic
    # inside one size, and a median across sizes keeps one unlucky pair from deciding.
    slopes = []
    for _ in range(3):
        small = min((measure(16) for _ in range(3)), key=lambda item: item[1])
        large = min((measure(18) for _ in range(3)), key=lambda item: item[1])
        delta_points = large[0] - small[0]
        delta_seconds = large[1] - small[1]
        if delta_points > 0 and delta_seconds > 0:
            slopes.append(delta_seconds * 1e9 / delta_points)
    if not slopes:
        return 0.0
    slopes.sort()
    return slopes[len(slopes) // 2]


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------


def cost_ns(spline_type: str = "POLY", level_range: bool = False) -> float:
    """``ns`` per **written** point, on the reference machine.

    ``level_range`` means the build writes the whole ladder (one spline per level) rather
    than a single level -- measured at 100 ns/point against 169, because the small lower
    levels are cache-resident while a single huge spline is memory-bandwidth bound.
    """
    table = SMOOTH_NS if spline_type == "SMOOTH" else POLY_NS
    return table["range" if level_range else "single"]


def bytes_per_point(spline_type: str = "POLY") -> float:
    """Memory per **written** point -- the same in both modes (each point is stored once)."""
    return SMOOTH_BYTES if spline_type == "SMOOTH" else POLY_BYTES


def estimate_seconds(points: int, spline_type: str = "POLY",
                     level_range: bool = False) -> float:
    """Predicted wait (build + evaluation) for ``points`` written points, on this machine."""
    ns = cost_ns(spline_type, level_range)
    return max(0, int(points)) * ns * speed_factor() / 1e9


def build_seconds(points: int, spline_type: str = "POLY",
                  level_range: bool = False) -> float:
    """Time Generate itself spends expanding ``points`` points -- **without** evaluation.

    Evaluation runs in the depsgraph *after* the operator returns and cannot be interrupted
    from Python, so counting it would put a progress bar on a click whose slow half is not
    cancellable -- and on a large build evaluation is the *longer* half (119 of the 169 ns
    for a single-level POLY build).

    Both phases are measured separately (see ``*_BUILD_NS`` / ``*_EVAL_NS``) rather than
    derived by subtracting one from the total: a subtraction that went negative was clamped
    to 1 ns and made the *level-range* build look like it takes no time at all.
    """
    table = SMOOTH_BUILD_NS if spline_type == "SMOOTH" else POLY_BUILD_NS
    ns = table["range" if level_range else "single"]
    return max(0, int(points)) * ns * speed_factor() / 1e9


def eval_seconds(points: int, spline_type: str = "POLY",
                 level_range: bool = False) -> float:
    """Predicted time the depsgraph spends building draw data for ``points`` points.

    Not interruptible from Python, so it is kept apart from :func:`build_seconds`: the
    progress bar cannot advance through it, and the panel has to say so instead of showing
    100 % and then freezing.
    """
    table = SMOOTH_EVAL_NS if spline_type == "SMOOTH" else POLY_EVAL_NS
    ns = table["range" if level_range else "single"]
    return max(0, int(points)) * ns * speed_factor() / 1e9


def estimate_mb(points: int, spline_type: str = "POLY") -> float:
    """Predicted memory for ``points`` written points."""
    return max(0, int(points)) * bytes_per_point(spline_type) / 1048576.0


# ---------------------------------------------------------------------------
# The budget itself
# ---------------------------------------------------------------------------


def _reserve(total):
    """Memory held back for the rest of Blender and the scene."""
    if not total:
        return 1.5 * 2 ** 30
    return max(0.8 * 2 ** 30, 0.15 * total)


def snapshot(spline_type: str = "POLY") -> Snapshot:
    """Current budget for this machine.  Cheap: memory reads are cached for 1 s."""
    spec = POLICY
    available, total = sysinfo.read()
    # A budget in points is mode independent for memory (a point costs 260 B either way) but
    # not for time: a range build writes more points for the same wall clock.  The budget is
    # enforced per *output*, so it is sized against the more expensive single-level cost --
    # that way a range build always fits too.
    ns = cost_ns(spline_type) * TIME_MARGIN * speed_factor()
    per_point = bytes_per_point(spline_type) * BYTES_MARGIN

    if available is None:
        # Unknown platform: fall back to the constant this add-on used before, which is
        # what every existing user already lives with.
        points, source = FALLBACK_POINTS, "UNKNOWN"
        keys = FALLBACK_KEY_POINTS * 8  # ~8 keys worth of the old per-key budget
    else:
        usable = max(0.0, available - _reserve(total))
        by_memory = usable * spec["mem_fraction"] / per_point
        by_time = spec["target_s"] * 1e9 / ns
        points = min(by_memory, by_time)
        source = "MEMORY" if by_memory <= by_time else "TIME"
        # Total key points: memory first, then the (slower) per-point build cost.
        keys = min(usable * spec["mem_fraction"] / (KEY_BYTES * BYTES_MARGIN),
                   spec["target_s"] * 1e9 / (KEY_NS * TIME_MARGIN * speed_factor()))

    points = int(max(FLOOR_POINTS, points))
    keys = int(max(FALLBACK_KEY_POINTS, keys))
    preview = int(max(PREVIEW_FLOOR, min(PREVIEW_CEILING, points // PREVIEW_SHARE)))
    return Snapshot(points, keys, preview, available, total, source)


def peak_points(spline_type: str = "POLY") -> int:
    return snapshot(spline_type).points


def key_budget() -> int:
    return snapshot("POLY").keys


def preview_budget() -> int:
    return snapshot("POLY").preview


# ---------------------------------------------------------------------------
# Add-on preferences
# ---------------------------------------------------------------------------


class FRACTALFAMILY_AP_preferences(bpy.types.AddonPreferences):
    """Storage for the speed measurement -- there is nothing here for the user to set.

    The budget is derived, not chosen (see :data:`POLICY`), so this panel exists to *report*
    the machine: how much memory Blender sees, how fast this CPU builds a point, and what
    that adds up to.  The only writable properties are hidden calibration fields, and they
    live here rather than in a file of our own because Blender persists preferences itself.

    ``bl_idname`` must be the add-on's module name: ``fractal_family`` for a legacy
    install, ``bl_ext.<repo>.fractal_family`` for an extension.  ``__package__`` is both.
    """

    bl_idname = __package__

    #: Measured speed relative to the reference machine, and which machine it was measured
    #: on.  Hidden: the panel reports it in words ("speed 1.26x reference"), and these exist
    #: so the measurement survives a restart **without the add-on touching the disk** --
    #: Blender writes the preferences file, not us.
    calibration_factor: bpy.props.FloatProperty(
        name="Calibrated Speed Factor",
        description="Measured cost per point relative to the reference machine (1.0 = same)",
        default=0.0, min=0.0, max=5.0, options={"HIDDEN"},
    )

    calibration_key: bpy.props.StringProperty(
        name="Calibration Key",
        description="Machine/Blender the factor was measured on; a mismatch re-measures",
        default="", options={"HIDDEN"},
    )

    def draw(self, context):
        draw_preferences(self.layout)


def draw_preferences(layout) -> None:
    """Body of the preferences panel, as a function so it can be smoke-tested.

    ``AddonPreferences.layout`` only exists while Blender is drawing (it is provided by the
    C side), so ``draw()`` cannot be called from a test; this function can be handed any
    layout-like object.
    """
    layout.use_property_split = False
    layout.use_property_decorate = False

    # No controls: everything below is read out of the machine.  A settings page with
    # nothing to set is honest here -- the alternative was one dropdown that only moved
    # the same numbers around.
    snap = snapshot("POLY")
    column = layout.column(align=True)
    column.label(text=_measure_line(snap), icon="MEMORY")
    if not _SPEED["calibrated"]:
        column.label(text=t("Speed calibration runs on the first Generate"), icon="TIME")


def _measure_line(snap: "Snapshot") -> str:
    """Memory / speed / limit of this machine, in one line.

    The speed factor is only shown once it has been measured: printing ``1.00× reference``
    before the first Generate would claim the CPU was benchmarked when it was not.
    """
    memory = "?" if snap.available is None else _size(snap.available / 1048576.0)
    if not _SPEED["calibrated"]:
        return tfmt("Available memory {size} · up to {limit:,} points",
                    size=memory, limit=snap.points)
    return tfmt(
        "Available memory {size} · speed {speed:.2f}× reference · up to {limit:,} points",
        size=memory, speed=speed_factor(), limit=snap.points,
    )


def _size(megabytes: float) -> str:
    """``260 MB`` / ``1.5 GB`` — same wording as the panel."""
    if megabytes >= 1024.0:
        return f"{megabytes / 1024.0:.1f} GB"
    return f"{megabytes:.0f} MB"
