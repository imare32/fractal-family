"""算子：生成 / 删除 / 场景预设 / 参数回读 / 基因复制粘贴 / **HUD 编辑**。

HUD 编辑是本插件与参考实现最大的交互差别：原版的编辑发生在侧栏的基因列表里（改两个整数、
点两个小图标），预览靠三条临时曲线对象；这里是一个视口内的**模态 HUD**：点阵上直接拖节点、
段上点 R/M 切标记、滚轮换等级，视口里的预览（:mod:`preview`）与 HUD 同步刷新，全程不建
任何临时数据块。

模态算子的取巧点：

* 面板只画在**发起会话的那个 3D 视图**里（``hud`` 按区域指针过滤），别的视图不受影响；
* 鼠标坐标直接用 ``event.mouse_region_x/y`` —— 与 ``POST_PIXEL`` 是同一个像素空间，
  命中测试不必做投影换算；
* 拖节点时把像素坐标换算成整数格点（:func:`hud_layout.snap`），所以"怎么拖都是合法的基因"；
* 拖出零长度段时 :meth:`props.GenFractalFamilySettings.move_node` 会拒绝，表现为拖不过去。
"""

# NOTE: no "from __future__ import annotations" in this module — it declares bpy.props, and
# PEP 563 stringises those annotations.  Property registration from string annotations is not
# portable across Blender versions, so the annotations stay real objects here.

import time

import bpy
from mathutils import Vector

from . import budget, build, hud, hud_layout, preview, sysinfo
from .i18n import t, tfmt
from .props import LEVEL_MAX, LEVEL_MIN

__all__ = [
    "FRACTALFAMILY_OT_clear_notice",
    "FRACTALFAMILY_OT_clear_request",
    "FRACTALFAMILY_OT_copy_gene",
    "FRACTALFAMILY_OT_generate",
    "FRACTALFAMILY_OT_hud",
    "FRACTALFAMILY_OT_item_add",
    "FRACTALFAMILY_OT_item_move",
    "FRACTALFAMILY_OT_item_remove",
    "FRACTALFAMILY_OT_paste_gene",
    "FRACTALFAMILY_OT_request_generate",
    "FRACTALFAMILY_OT_set_domain",
    "FRACTALFAMILY_OT_setup_scene",
]


def _settings(context):
    return context.scene.fractalfamily


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------


#: Predicted wait above which Generate runs as a **modal** job (progress line + ``ESC``).
#: Below it the whole build is shorter than a UI refresh, and a modal would only cost a
#: frame and a cursor change.
MODAL_THRESHOLD_S = 0.35

#: How long one timer tick may spend expanding before handing the event loop back.  A tick
#: that overruns delays ``ESC`` by exactly that much, so this is a *responsiveness* budget,
#: not a speed knob: 25 ms is one frame at 40 fps.
MODAL_SLICE_S = 0.025


class _Abort(Exception):
    """Generate stopped before anything was written; ``message`` is user-facing already."""

    def __init__(self, message: str, kind: str = "ERROR"):
        super().__init__(message)
        self.message = message
        self.kind = kind


def _set_busy(window, busy: bool) -> None:
    """WAIT cursor while generating.  Silent when there is no window (background)."""
    if window is None:
        return
    try:
        window.cursor_set("WAIT" if busy else "DEFAULT")
    except (AttributeError, TypeError, RuntimeError):
        pass


def _evaluate(context) -> None:
    """Force the dependency graph through the new curve, i.e. pay the stall here.

    Every viewport needs the draw data for the curve it is showing, and Blender builds it on
    the first evaluation after the object exists.  Doing it inside the operator means the
    cost lands where it can be *measured* (and where the status line is still up), instead of
    on whatever redraw happens to come next.

    Tolerant on purpose: a context without a view layer (a scripted call, a test harness)
    simply has nothing to evaluate, and generation must not fail over a clock.
    """
    view_layer = getattr(context, "view_layer", None)
    update = getattr(view_layer, "update", None)
    if update is None:
        return
    try:
        update()
    except RuntimeError:  # e.g. called while the depsgraph is already evaluating
        pass


def _tag_panels() -> None:
    """Ask every sidebar so the panel redraws on the next frame.

    ``ui.progress_*`` values change while the modal timer runs; without this the panel keeps
    its last paint until some other event happens to invalidate it, which for a modal build
    can be several seconds.
    """
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return
    for window in window_manager.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# Note (source only -- the tooltip is ``bl_description`` below): when the requested level is
# above what this machine's budget allows the operator does **not** refuse.  It writes the
# highest level that fits and records the degradation in ``settings.notice_*`` so the panel
# can explain it.  ``force`` is the escape hatch the panel offers next to that notice -- it
# asks for confirmation and then ignores the budget, which is the only way to get an
# "it will probably freeze" result.
#
# A build predicted to take longer than MODAL_THRESHOLD_S runs as a modal job: a timer
# expands it a level at a time in ~25 ms slices, the status bar shows how far it has got and
# ESC stops it and removes whatever was written.  Anything faster runs in one go -- a
# progress line for a 40 ms build would only flicker.
class FRACTALFAMILY_OT_generate(bpy.types.Operator):
    """Build one curve object from the gene and the level range."""

    bl_idname = "fractalfamily.generate"
    bl_label = "Generate Fractal Curves"
    bl_description = ("Build the curve for the current gene. A level too heavy for this "
                      "machine is written at the highest level that fits, and the panel "
                      "says which one was used")
    bl_options = {"REGISTER", "UNDO"}

    #: ``True`` builds one shape key per level instead of one spline per level.
    #:
    #: ``HIDDEN``: this and ``force`` are set by the *buttons in the sidebar*, not by the
    #: user.  Without it Blender adds them to the redo panel ("Adjust Last Operation") as two
    #: unlabelled checkboxes -- and that panel is drawn exactly where the HUD opens.
    keys: bpy.props.BoolProperty(default=False, options={"HIDDEN"})

    #: Ignore the budget (set by the "level N anyway" button inside the notice).
    force: bpy.props.BoolProperty(default=False, options={"HIDDEN"})

    #: Explicit level for this one build, or ``0`` to use the scene's Level.  Set by the
    #: choice buttons so "generate the level that fits" writes exactly the number it named,
    #: without moving the scene's Level (which also drives the HUD and the preview).
    level: bpy.props.IntProperty(default=0, min=0, options={"HIDDEN"})

    #: Modal state (per call; the class values are only defaults).
    _job = None
    _timer = None
    #: ``True`` on the tick after the build finished: the next tick runs the evaluation.
    _evaluating = False
    _allowed = 0
    _requested = 0

    def invoke(self, context, event):
        settings = _settings(context)
        # No confirmation dialog for ``force``: the button that sets it exists only inside the
        # degradation notice, it names the level it is about to build, and the cost line above
        # it already quotes the point count -- a modal on top of that is a click that carries
        # no information.
        # No window (background / a scripted INVOKE_DEFAULT): there is nothing to report to.
        if context.window is None or not settings.is_valid() or not self._is_slow(settings):
            return self.execute(context)
        return self._start_modal(context)

    def execute(self, context):
        try:
            job = self._prepare(context)
        except _Abort as stop:
            self.report({stop.kind}, stop.message)
            return {"CANCELLED"}

        window = context.window
        _set_busy(window, True)
        try:
            while job.step():
                pass
            # ``_finish`` writes the shape-key object, which is part of the wait.
            return self._finish(context, job)
        except Exception as exc:
            job.cancel()
            return self._fail(context, exc)
        finally:
            _set_busy(window, False)

    # --- modal path --------------------------------------------------------

    def _start_modal(self, context):
        try:
            self._job = self._prepare(context)
        except _Abort as stop:
            self.report({stop.kind}, stop.message)
            return {"CANCELLED"}
        window_manager = context.window_manager
        try:
            self._timer = window_manager.event_timer_add(0.05, window=context.window)
        except (AttributeError, TypeError, RuntimeError):
            # No timer, no modal: build in one go rather than leak a half-made job.
            self._job.cancel()
            self._job = None
            return self.execute(context)
        window_manager.modal_handler_add(self)
        _set_busy(context.window, True)
        self._report_progress(context)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        # ``Event.timer`` is gone in Blender 5.x (it existed up to 4.x), and this operator
        # owns exactly one timer, so the event *type* is enough to tell the ticks apart.
        try:
            return self._modal(context, event)
        except Exception as exc:
            # Anything unforeseen must still hand the window back: timer off, status text
            # cleared, partial datablocks dropped.
            self._teardown(context)
            if self._job is not None:
                self._job.cancel()
            return self._fail(context, exc)

    def _modal(self, context, event):
        if event.type == "ESC" or self._job is None:
            return self._cancel(context)
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}
        # Time-sliced: keep expanding until this tick's budget is spent, then return to the
        # event loop so the window can redraw and ``ESC`` can arrive.
        # The evaluation phase has its own tick.  ``view_layer.update()`` blocks the main
        # thread, and Blender draws between events -- so calling it in the same tick that sets
        # up the caption meant the caption was never painted: the panel showed 100 %, froze,
        # and the curve appeared.  Returning once first gives the window a frame to draw the
        # countdown before the blocking call.
        if self._evaluating:
            return self._finish(context, self._job)

        deadline = time.perf_counter() + MODAL_SLICE_S
        while time.perf_counter() < deadline:
            if not self._job.step():
                self._teardown(context, keep_progress=True)
                self._report_progress(context, finished=True)
                self._evaluating = True
                return {"RUNNING_MODAL"}
        self._report_progress(context)
        return {"RUNNING_MODAL"}

    def _cancel(self, context):
        """``ESC``: drop what was written and leave no trace of the attempt."""
        job = self._job
        self._teardown(context)
        if job is not None:
            job.cancel()
        self.report({"WARNING"}, t("Generation cancelled"))
        return {"CANCELLED"}

    def _teardown(self, context, keep_progress: bool = False) -> None:
        """Stop the timer.  ``keep_progress`` leaves the panel showing the running state.

        The timer is **not** removed when ``keep_progress`` is set: the evaluation runs on the
        tick *after* the build finishes (so the panel gets one frame to draw the "evaluating"
        caption before the blocking call), and without a timer there is no next tick.
        """
        if not keep_progress and self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except (AttributeError, TypeError, RuntimeError):
                pass
            self._timer = None
        _set_busy(context.window, False)
        if keep_progress:
            # The build finished but Blender still has to evaluate the curve, and on a large
            # one that is the longer half.  Leaving the bar up keeps the panel from flashing
            # back to the buttons; ``_clear_progress`` runs once the evaluation is done.
            return
        self._clear_progress(context)

    def _clear_progress(self, context) -> None:
        """The bar keys off a negative fraction: leaving the last value would show a frozen
        87 % over a finished build."""
        settings = _settings(context)
        settings.running_fraction = -1.0
        settings.running_level = 0
        settings.running_high = 0
        settings.running_points = 0
        settings.running_build_s = 0.0
        settings.running_eval_s = 0.0
        settings.running_eval_start = 0.0
        _tag_panels()

    def _report_progress(self, context, finished: bool = False) -> None:
        """Move the panel bar.

        The bar covers the **whole wait**, not just the part Python controls.  Expanding the
        points is only 28-35 % of the total on a big POLY build: after it, Blender's
        depsgraph still has to build the draw data, and that phase is neither interruptible
        nor observable from here.  So the build fills the bar up to ``build_share`` and the
        evaluation is the remainder -- shown as a caption, because the bar cannot advance
        through something it cannot measure.  A bar that ran to 100 % and then froze for
        longer than the build had taken was the panel lying about what was left.
        """
        job = self._job
        if job is None:
            return
        # The panel bar is the only place the progress is drawn.  It used to also write into
        # ``workspace.status_text_set``; that string sits at the far bottom-left of the
        # window, away from the button that was just pressed, and keeping both in sync meant
        # two places to read a single number from.
        settings = _settings(context)
        if finished:
            # Build done: the bar is full *of the part this side can measure*, and the panel
            # keeps it full while it counts the evaluation down by time.  Splitting the bar at
            # 28 % and freezing there left the user watching a stall with no explanation.
            settings.running_fraction = 1.0
            settings.running_level = job.high
            settings.running_eval_start = time.perf_counter()
        else:
            settings.running_fraction = job.fraction
            settings.running_level = job.level
        settings.running_high = job.high
        # The point count the bar and the evaluation caption quote has to be the number that
        # was actually expanded -- ``estimate_written(high)`` would re-derive it from the
        # current gene, which no longer describes what is being evaluated if the user typed
        # while the build ran.
        settings.running_points = job.points_done
        _tag_panels()

    # --- shared ------------------------------------------------------------

    def _is_slow(self, settings) -> bool:
        """Would this click take long enough that the user needs to see it working?"""
        if self.keys:
            # Shape keys are budgeted to a fraction of a second on every machine *and* are
            # built in one pass (the keys need every level at once), so a modal cannot
            # interrupt them -- it would only add a frame.
            return False
        requested = int(self.level) if int(self.level) > 0 else settings.level_range()[1]
        limit = settings.output_level_limit()
        top = requested if (self.force or int(self.level) > 0) else min(requested, limit)
        # Build time only: evaluation happens after the operator returns, so it cannot be
        # reported or interrupted -- counting it would put a modal on a 60 ms build whose
        # slow half is not ours to control.
        return settings.estimate_build_seconds(top) >= MODAL_THRESHOLD_S

    def _prepare(self, context):
        """Calibrate, clamp to the budget, check memory, and open the job."""
        settings = _settings(context)
        settings.error = ""
        # Either answer closes the question; a scripted call finds nothing to clear.
        settings.pending_generate = ""

        # First click on this machine: time a tiny build so the budget knows how fast this
        # CPU is. ~4 ms, once per session.
        budget.ensure_calibration()
        sysinfo.clear_cache()  # the click is exactly when a fresh reading matters

        # An explicit level is a one-off choice from the panel.  It never touches the
        # scene's Level, so the HUD and the preview still show what the user is editing.
        explicit = int(self.level) > 0
        requested = int(self.level) if explicit else settings.level_range()[1]
        # Only shape keys begin at level 1: one key per level is what they *are*.  For a
        # curve, the low end comes from the Output Range switch -- with it off that is the
        # requested level itself, i.e. a single curve.  An explicit ``level`` (either answer
        # in the over-budget choice) used to be lumped in with ``keys`` here, which wrote
        # "L1-24" for a user who had never enabled Output Range and priced just the top
        # level while writing the entire ladder.
        low = LEVEL_MIN if self.keys else settings.level_range()[0]
        allowed = settings.shape_key_level() if self.keys else settings.output_level_limit()
        # An explicit level or an insisted build names its level: write exactly it, without
        # re-clamping to a budget that was computed for a different request.
        top = requested if (self.force or explicit) else min(requested, allowed)
        first = LEVEL_MIN if self.keys else min(low, top)

        # Hard limit, and the one ``force`` must never cross.  The point budget above is a
        # policy: 25 % of free memory and ten seconds, both chosen for comfort.  A user is
        # entitled to override it -- they may be about to close the other file, or simply
        # not mind waiting.  But a build whose predicted peak exceeds the memory that is
        # *actually free right now* is not a comfort question: the allocation happens inside
        # an uninterruptible C call, so the OS starts swapping and no amount of ESC brings
        # the window back.  See :data:`budget.REFUSE_FRACTION`.
        #
        # This is checked on the level that is about to be **written**, not the requested
        # one: a degraded build is small enough to pass even when the request itself was
        # refused.  Shape keys price their points differently, and get the same wall.
        state, reason, safe, info = settings.output_verdict(
            keys=self.keys, level=top, low=first)
        if state == budget.REFUSE:
            settings.notice_kind = "REFUSED"
            settings.notice_requested = requested
            settings.notice_actual = safe
            if reason == budget.REFUSE_MEMORY:
                message = tfmt(
                    "Level {level} needs about {size}, but only {avail} is free. "
                    "Generating it would freeze this machine, so it was not written",
                    level=top, size=_size(info["needed_mb"]),
                    avail=_size(info["available_mb"]),
                )
            else:
                message = tfmt(
                    "Level {level} would take about {minutes} minutes to build. "
                    "It was not written",
                    level=top, minutes=int(round(info["seconds"] / 60.0)),
                )
            settings.error = message
            preview.tag_redraw()
            # WARNING, not ERROR: a refusal is a normal answer on a small machine, and
            # ``bpy.ops`` turns an ERROR report into a RuntimeError that aborts scripts.
            raise _Abort(message, "WARNING")

        # Last resort for a build that is allowed by the physical limit but too close to it
        # to be wise: show it in the viewport instead of writing a datablock.  ``force``
        # skips this one (it is a policy, and the user just insisted), but not the wall above.
        if not self.keys and not self.force:
            needed = budget.estimate_mb(
                settings.estimate_written(top, first), settings.spline_type)
            available = sysinfo.available_bytes()
            if available and needed * 1048576.0 > available * 0.9:
                settings.notice_kind = "PREVIEW_ONLY"
                settings.notice_requested = requested
                settings.notice_actual = top
                message = tfmt(
                    "Not enough memory for level {level}: it needs about {size} and "
                    "{avail} is available. The viewport preview shows it instead",
                    level=top, size=_size(needed), avail=_size(available / 1048576.0),
                )
                settings.error = message
                preview.tag_redraw()
                raise _Abort(message, "WARNING")

        self._allowed = allowed
        self._requested = requested

        # What share of the total wait the bar can actually advance through.  Shape keys are
        # exempt: they are built in a single step whose own cost dominates, and calibration
        # already keeps them short.
        written = settings.estimate_written(top, first)
        build_s = budget.build_seconds(written, settings.spline_type,
                                       level_range=first < top)
        total_s = build_s + budget.eval_seconds(written, settings.spline_type,
                                                level_range=first < top)
        settings.running_build_s = build_s
        settings.running_eval_s = max(0.0, total_s - build_s)

        try:
            return build.BuildJob(
                settings, keys=self.keys, collection=context.collection,
                levels=(first, top), requested=requested,
            )
        except Exception as exc:
            message = t(str(exc))
            settings.error = message
            settings.dirty = True
            raise _Abort(tfmt("Generation failed: {error}", error=message)) from exc

    def _fail(self, context, exc):
        settings = _settings(context)
        message = t(str(exc))
        settings.error = message
        settings.dirty = True
        self.report({"ERROR"}, tfmt("Generation failed: {error}", error=message))
        return {"CANCELLED"}

    def _finish(self, context, job):
        settings = _settings(context)
        try:
            summary = job.finish()
        except Exception as exc:
            return self._fail(context, exc)

        # ``job.finish`` stops the clock when the datablocks exist, but the wait does not end
        # there: Blender still has to evaluate the new curve.  On a six-million point build
        # that is 1.6 s, four times the build itself -- reporting only the build made the
        # status bar say "362 ms" for an operation that took two seconds, which is exactly
        # the kind of number that makes a budget feel arbitrary.  Evaluate here so the figure
        # is measured instead of predicted, and it matches what the user waited for.
        started = time.perf_counter()
        _evaluate(context)
        evaluated_ms = (time.perf_counter() - started) * 1000.0
        settings.last_ms += evaluated_ms
        summary["ms"] = settings.last_ms
        summary["eval_ms"] = evaluated_ms
        # The bar stayed up through the evaluation (see ``_teardown``), and so did the timer
        # that scheduled this very call; now the wait is really over.
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except (AttributeError, TypeError, RuntimeError):
                pass
            self._timer = None
        self._clear_progress(context)

        requested = self._requested
        top = summary["high"]
        degraded = top < requested
        over_budget = top > self._allowed

        if self.force and over_budget:
            # The user insisted; keep the trace on the object so a later "why is this file
            # so heavy" question has an answer.
            settings.notice_kind = "FORCED"
            settings.notice_requested = requested
            settings.notice_actual = top
            for obj in summary["objects"]:
                obj[build.REQUESTED_KEY] = requested
        elif degraded and not self.keys:
            settings.notice_kind = "DEGRADED"
            settings.notice_requested = requested
            settings.notice_actual = top
        else:
            # Shape keys keep their own long-standing hint ("Shape keys stop at level N");
            # repeating it as an error block would cry wolf on every key generate.
            settings.clear_notice()

        message = _summary_message(summary, degraded, requested)
        self.report({"WARNING"} if (degraded or over_budget) else {"INFO"}, message)
        return {"FINISHED"}


def _size(megabytes: float) -> str:
    """``12 kB`` / ``260 MB`` / ``1.5 GB`` -- one decimal from a gigabyte upwards."""
    if megabytes >= 1024.0:
        return f"{megabytes / 1024.0:.1f} GB"
    if megabytes >= 1.0:
        return f"{megabytes:.0f} MB"
    return f"{megabytes * 1024.0:.0f} kB"


def _summary_message(summary: dict, degraded: bool, requested: int) -> str:
    """Report line for the info bar (the panel carries the persistent version)."""
    if summary["keys"]:
        return tfmt(
            "Levels {low}-{high} · {keys} shape keys · {points} points · {ms:.0f} ms",
            low=summary["low"], high=summary["high"], keys=summary["keys"],
            points=summary["points"], ms=summary["ms"],
        )
    if degraded:
        return tfmt("Generated level {actual} instead of {requested} (budget for this machine)",
                    actual=summary["high"], requested=requested)
    if summary["separate"]:
        return tfmt(
            "Levels {low}-{high} · {count} objects · {points} points · {ms:.0f} ms",
            low=summary["low"], high=summary["high"],
            count=len(summary["objects"]), points=summary["points"], ms=summary["ms"],
        )
    return tfmt(
        "Levels {low}-{high} · {splines} splines · {points} points · {ms:.0f} ms",
        low=summary["low"], high=summary["high"], splines=summary["splines"],
        points=summary["points"], ms=summary["ms"],
    )


class FRACTALFAMILY_OT_clear_notice(bpy.types.Operator):
    """Close the "generated at a lower level" notice (the one with the force button)."""

    bl_idname = "fractalfamily.clear_notice"
    bl_label = "Dismiss"
    bl_description = "Hide this notice"

    @classmethod
    def poll(cls, context):
        settings = _settings(context)
        return settings is not None and bool(settings.notice_kind)

    def execute(self, context):
        settings = _settings(context)
        settings.clear_notice()
        settings.error = ""
        return {"FINISHED"}


class FRACTALFAMILY_OT_request_generate(bpy.types.Operator):
    """The panel's Generate buttons: ask first when the requested level is over budget."""

    bl_idname = "fractalfamily.request_generate"
    bl_label = "Generate Fractal Curves"
    bl_description = ("Check the requested level before writing anything. A level over this "
                      "machine's budget asks whether to write the level that fits or to "
                      "insist on the requested one")

    keys: bpy.props.BoolProperty(default=False, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        settings = _settings(context)
        # The panel replaces its buttons with the progress bar while a build runs, but a
        # scripted call does not go through the panel.  Letting one set ``pending_generate``
        # mid-build hid the question behind the bar and sprang it on the user afterwards,
        # priced for a state that no longer existed.
        return settings is not None and settings.running_fraction < 0.0

    def execute(self, context):
        settings = _settings(context)
        # ``poll`` can be bypassed by an explicit EXEC_DEFAULT; repeat the guard where the
        # state is actually written.
        if settings.running_fraction >= 0.0:
            return {"CANCELLED"}
        # The panel is the only caller; a scripted EXEC_DEFAULT still goes straight to
        # ``fractalfamily.generate`` and keeps its one-click behaviour.
        sysinfo.clear_cache()
        state, _reason, _safe, _info = settings.output_verdict(keys=self.keys)
        if state == budget.FITS:
            settings.pending_generate = ""
            return bpy.ops.fractalfamily.generate(
                "INVOKE_DEFAULT", keys=self.keys, force=False)
        # Nothing is written yet.  The panel now quotes the numbers and offers the choices;
        # REFUSE simply offers fewer of them.
        settings.pending_generate = "KEYS" if self.keys else "CURVE"
        settings.clear_notice()
        return {"FINISHED"}


class FRACTALFAMILY_OT_clear_request(bpy.types.Operator):
    """Cancel a pending Generate without writing anything."""

    bl_idname = "fractalfamily.clear_request"
    bl_label = "Cancel"
    bl_description = "Cancel this build without generating anything"

    @classmethod
    def poll(cls, context):
        settings = _settings(context)
        return settings is not None and bool(settings.pending_generate)

    def execute(self, context):
        _settings(context).pending_generate = ""
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# 场景预设
# ---------------------------------------------------------------------------


def _bounds(context, settings):
    """Frame the **selected** object; fall back to the preview when nothing is selected."""
    obj = context.active_object
    if obj is not None and obj.type in {"CURVE", "MESH"} and obj.data is not None:
        corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        if corners:
            return corners

    lines = preview.lines_for(settings)
    if not lines:
        return []
    points = lines[-1]
    return [Vector((float(x), float(y), 0.0)) for x, y in points[:100000]]


# Note (source only): reuses the scene camera when there is one, sets a 2048×2048 render and
# the Standard view transform, and falls back to the current preview when nothing is selected.
class FRACTALFAMILY_OT_setup_scene(bpy.types.Operator):
    """Camera, resolution and colour management for a top-down render of the curve."""

    bl_idname = "fractalfamily.setup_scene"
    bl_label = "Scene Setup"
    bl_description = ("Frame the selected curve with an orthographic top-view camera, "
                      "a 2048×2048 render and the Standard view transform")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        corners = _bounds(context, _settings(context))
        if not corners:
            self.report({"WARNING"}, t("Nothing to frame: select a curve, or generate one first"))
            return {"CANCELLED"}

        centre = sum(corners, Vector()) / len(corners)
        radius = max((corner - centre).length for corner in corners)
        if radius < 1e-6:
            self.report({"WARNING"}, t("Content size is zero"))
            return {"CANCELLED"}

        camera = scene.camera
        if camera is None or camera.type != "CAMERA":
            data = bpy.data.cameras.new("Fractal Family Camera")
            camera = bpy.data.objects.new("Fractal Family Camera", data)
            (context.collection or scene.collection).objects.link(camera)
            scene.camera = camera

        # 分形在 XY 平面上：正交 + 俯视，留 8% 边距
        camera.data.type = "ORTHO"
        margin = 1.08
        camera.data.ortho_scale = radius * 2.0 * margin
        camera.location = Vector((centre.x, centre.y, max(1.0, radius * 4.0)))
        camera.rotation_euler = (0.0, 0.0, 0.0)

        scene.render.resolution_x = 2048
        scene.render.resolution_y = 2048
        scene.render.film_transparent = False
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"

        self.report(
            {"INFO"},
            tfmt("Orthographic top view · frame {scale:.2f} · 2048×2048 · Standard view",
                 scale=camera.data.ortho_scale),
        )
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# 基因列表（侧栏用；HUD 是另一条路）
# ---------------------------------------------------------------------------


class FRACTALFAMILY_OT_item_add(bpy.types.Operator):
    """Append a segment, reusing the direction of the last one."""

    bl_idname = "fractalfamily.item_add"
    bl_label = "Add Segment"
    bl_description = "Add a segment at the end, starting in the direction of the last one"

    def execute(self, context):
        settings = _settings(context)
        # 默认沿用最后一段的方向：新手最常做的是"再走一格"
        last = settings.items[-1] if settings.items else None
        settings.add_item(last.a if last else 1, last.b if last else 0)
        hud.tag_redraw()
        return {"FINISHED"}


class FRACTALFAMILY_OT_item_remove(bpy.types.Operator):
    """Remove the selected segment; the last two cannot be removed."""

    bl_idname = "fractalfamily.item_remove"
    bl_label = "Remove Segment"
    bl_description = "Remove the selected segment. A gene needs at least two"

    @classmethod
    def poll(cls, context):
        return len(_settings(context).items) > 2

    def execute(self, context):
        settings = _settings(context)
        settings.remove_item(settings.active_index)
        hud.tag_redraw()
        return {"FINISHED"}


class FRACTALFAMILY_OT_item_move(bpy.types.Operator):
    """Reorder the selected segment; ``direction`` picks the swap partner."""

    bl_idname = "fractalfamily.item_move"
    bl_label = "Move Segment"
    bl_description = "Move the selected segment one place up or down"

    direction: bpy.props.EnumProperty(items=(("UP", "Up", ""), ("DOWN", "Down", "")))

    @classmethod
    def poll(cls, context):
        return len(_settings(context).items) > 1

    def execute(self, context):
        settings = _settings(context)
        items = settings.items
        index = settings.active_index
        neighbour = index + (-1 if self.direction == "UP" else 1)
        if 0 <= neighbour < len(items):
            items.move(index, neighbour)
            settings.active_index = neighbour
            settings.set_elements(settings.elements())
            hud.tag_redraw()
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# 点阵域
# ---------------------------------------------------------------------------


# The panel draws the domain as two explicit buttons instead of an expanded enum:
# ``layout.prop(..., expand=True)`` renders two unlabelled blocks in 5.2 (the labels get
# swallowed and only a blue highlight remains), so the button text is given explicitly and
# ``depress`` marks the current value.
class FRACTALFAMILY_OT_set_domain(bpy.types.Operator):
    """Switch the lattice used for the integer coordinates."""

    bl_idname = "fractalfamily.set_domain"
    bl_label = "Switch Lattice Domain"
    bl_description = ("Switch between the Gaussian (square) and Eisenstein (triangular) "
                      "lattice: the same two integers point in different directions")

    domain: bpy.props.EnumProperty(
        items=(("G", "Gaussian G", ""), ("E", "Eisenstein E", "")),
        default="G",
    )

    @classmethod
    def poll(cls, context):
        return _settings(context) is not None

    def execute(self, context):
        settings = _settings(context)
        if settings.domain != self.domain:
            # 赋值会触发 _on_domain_change（标脏 + 排 timer），这里只补一次重绘
            settings.domain = self.domain
        hud.reset_view()
        hud.tag_redraw()
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# 基因复制 / 粘贴
# ---------------------------------------------------------------------------


class FRACTALFAMILY_OT_copy_gene(bpy.types.Operator):
    """Put the gene string on the clipboard (the format Paste Gene reads)."""

    bl_idname = "fractalfamily.copy_gene"
    bl_label = "Copy Gene"
    bl_description = 'Copy this gene as text, for example "G 1 0 0 0 0 1 1 0"'

    def execute(self, context):
        settings = _settings(context)
        context.window_manager.clipboard = settings.current_gene()
        self.report({"INFO"}, settings.current_gene())
        return {"FINISHED"}


class FRACTALFAMILY_OT_paste_gene(bpy.types.Operator):
    """Parse the clipboard into a gene, then apply it."""

    bl_idname = "fractalfamily.paste_gene"
    bl_label = "Paste Gene"
    bl_description = "Read a gene from the clipboard and make it the current gene"

    def execute(self, context):
        settings = _settings(context)
        text = (context.window_manager.clipboard or "").strip()
        if not text:
            self.report({"WARNING"}, t("The clipboard is empty"))
            return {"CANCELLED"}
        try:
            settings.apply_gene(text)
        except (ValueError, IndexError) as exc:
            settings.error = tfmt("Paste failed: {error}", error=exc)
            self.report({"ERROR"}, settings.error)
            return {"CANCELLED"}
        settings.error = ""
        hud.tag_redraw()
        self.report({"INFO"}, tfmt("Imported {family}", family=settings.family_name()))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# HUD 编辑（模态）
# ---------------------------------------------------------------------------

#: 悬停光标。节点可以拖，用手形；R/M 只有 12 px 见方，**手形会把两个方块一起挡住**
#: （实测：手形图标比方块还大，悬停时根本看不见 R/M 的字），所以小方块用细十字准星。
_CURSOR_NODE = "HAND"
_CURSOR_FLAG = "CROSSHAIR"
_CURSOR_DEFAULT = "DEFAULT"


def _cursor_for(hotspot) -> str:
    """悬停到某个 hotspot 时该用哪个光标。"""
    if hotspot is None:
        return _CURSOR_DEFAULT
    if hotspot["kind"] == "node":
        return _CURSOR_NODE
    if hotspot["kind"] == "flag":
        return _CURSOR_FLAG
    return _CURSOR_DEFAULT


#: 模态里的按键（**只在指针停在面板上时**生效，其余按键照常走视口快捷键）。
_KEY_DOMAIN = {"TAB", "Q"}
_KEY_ADD = {"A"}
_KEY_REMOVE = {"X", "DELETE"}
_KEY_FIT = {"F"}
_KEY_EXIT = {"ESC"}


class FRACTALFAMILY_OT_hud(bpy.types.Operator):
    """Open the gene HUD in the 3D viewport: drag nodes, toggle R/M, wheel the level."""

    bl_idname = "fractalfamily.hud"
    bl_label = "HUD Gene Editor"
    bl_description = ("Open the in-viewport gene editor: drag nodes, click R/M to toggle "
                      "flags, wheel to change the level. Esc or × closes it, and the rest "
                      "of the viewport keeps working as usual")

    @classmethod
    def poll(cls, context):
        return getattr(context, "area", None) is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        if hud.session() is not None:
            # 已经开着：再点一次就是收起来
            self._shutdown(context)
            return {"FINISHED"}
        if not _settings(context).items:
            # 第一次用：给一条能看的基因（龙形曲线）
            _settings(context).apply_gene("G 1 0 0 0 0 1 1 0")
        self._drag = ""
        self._drag_offset = (0.0, 0.0)
        # The button lives in the sidebar, so ``context.region`` is the UI region here.  The
        # HUD is drawn in the area's WINDOW region (that is what POST_PIXEL and the mouse
        # coordinates use), so hold on to that one instead.
        self._region = self._window_region(context)
        hud.begin(context, self._region)
        # Start with the normal cursor: the hand only appears while hovering a node, and
        # the hover is resolved on the first mouse move (see _on_mouse_move).
        self._set_cursor(context, _CURSOR_DEFAULT)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    # --- 生命周期 ---------------------------------------------------------

    @staticmethod
    def _window_region(context):
        """The area's WINDOW region (where the HUD is drawn), whatever invoked us."""
        region = getattr(context, "region", None)
        if getattr(region, "type", "") == "WINDOW":
            return region
        area = getattr(context, "area", None)
        for candidate in getattr(area, "regions", ()) or ():
            if candidate.type == "WINDOW":
                return candidate
        return region

    def _set_cursor(self, context, cursor: str) -> None:
        try:
            context.window.cursor_set(cursor)
        except (AttributeError, TypeError):
            pass

    def _shutdown(self, context) -> None:
        hud.end(context)
        self._drag = ""
        self._set_cursor(context, _CURSOR_DEFAULT)

    # --- 事件 -------------------------------------------------------------

    def modal(self, context, event):
        """**不抢视口**的模态：只吃指针落在面板上的事件，其余一律 ``PASS_THROUGH``。

        这一点很重要 —— 早期版本把所有事件都吃掉，HUD 一开就没法摆视角 / 选中 / 用别的
        面板。现在的规则是：

        * 指针在面板外：所有事件照常交给视口与快捷键（面板只是"看得见、不挡路"）；
        * 指针在面板内：点击 / 滚轮 / 面板上写明的几个按键归 HUD；
        * 正在拖（节点或标题栏）时：不管指针跑到哪都归 HUD，否则松手事件被别人吃掉、
          节点会卡在拖拽状态。
        """
        if hud.session() is None:
            self._set_cursor(context, _CURSOR_DEFAULT)
            return {"FINISHED"}

        settings = _settings(context)
        layout = hud.layout_for(context)
        if layout is None:
            self._shutdown(context)
            return {"FINISHED"}

        x = event.mouse_region_x
        y = event.mouse_region_y
        # Do NOT gate this on ``context.region``: in a modal operator that field is the
        # region the operator was started from (or empty), not the region under the
        # pointer, so comparing it with the session region swallowed every mouse move and
        # broke dragging.  The panel rectangle itself is the hit test.
        inside = self._inside(layout, x, y)
        dragging = bool(self._drag)

        # The help card covers the panel body, so it takes the clicks: any click or Esc
        # closes it, everything else goes through to the viewport.
        if hud.help_open():
            if event.type in {"ESC", "LEFTMOUSE", "RIGHTMOUSE"} and event.value == "PRESS":
                hud.toggle_help(False)
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            self._on_mouse_move(context, settings, layout, x, y)
            return {"RUNNING_MODAL"} if dragging else {"PASS_THROUGH"}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            if not inside:
                return {"PASS_THROUGH"}
            step = 1 if event.type == "WHEELUPMOUSE" else -1
            if event.shift:
                # Shift + 滚轮：缩放 HUD 视图（不改基因，只是看得细一点）
                session = hud.session()
                zoom = session.get("zoom") or layout["zoom"]
                factor = 1.15 if step > 0 else 1.0 / 1.15
                session["zoom"] = max(
                    hud_layout.MIN_ZOOM, min(hud_layout.MAX_ZOOM * 2.0, zoom * factor)
                )
            else:
                # The wheel stops at LEVEL_MAX like every other control: the budget is a
                # point count, not a level, so scrolling cannot silently cross it -- the
                # panel reports the level that will actually be written.
                settings.level = max(LEVEL_MIN, min(int(settings.level) + step, LEVEL_MAX))
            hud.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                target = hud_layout.hit(layout["hotspots"], x, y)
                if target is None:
                    # 面板是实心的：点空白处不该"穿透"去选中它后面的物体
                    return {"RUNNING_MODAL"} if inside else {"PASS_THROUGH"}
                if self._on_press(context, settings, layout, target, x, y) == "EXIT":
                    self._shutdown(context)
                    return {"FINISHED"}
                return {"RUNNING_MODAL"}
            if not dragging:
                return {"PASS_THROUGH"}
            self._drag = ""
            if hud.session() is not None:
                hud.session()["drag"] = ""
            hud.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "RIGHTMOUSE" and event.value == "PRESS":
            if not inside and not dragging:
                return {"PASS_THROUGH"}
            # 面板上右键 = 收起 HUD（和 × 一样）；拖拽中右键 = 松手，避免节点卡住
            if dragging:
                self._drag = ""
                hud.session()["drag"] = ""
                hud.tag_redraw()
                return {"RUNNING_MODAL"}
            self._shutdown(context)
            return {"FINISHED"}

        if event.value != "PRESS":
            return {"PASS_THROUGH"}

        # 键盘：只有指针停在面板上才接管，否则让快捷键照常工作
        if not inside and not dragging:
            return {"PASS_THROUGH"}

        if event.type in _KEY_EXIT:
            if dragging:
                self._drag = ""
                hud.session()["drag"] = ""
                hud.tag_redraw()
                return {"RUNNING_MODAL"}
            self._shutdown(context)
            return {"FINISHED"}

        if event.type in _KEY_DOMAIN:
            settings.domain = "E" if settings.domain == "G" else "G"
            hud.reset_view()
            return {"RUNNING_MODAL"}

        if event.type in _KEY_ADD:
            self._append_segment(settings)
            return {"RUNNING_MODAL"}

        if event.type in _KEY_REMOVE:
            settings.remove_item(-1)
            return {"RUNNING_MODAL"}

        if event.type in _KEY_FIT:
            hud.reset_view()
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    # --- 交互细节 ---------------------------------------------------------

    @staticmethod
    def _append_segment(settings) -> None:
        """末尾追加一段（沿用最后一段的方向：新手最常做的是"再走一格"）。"""
        last = settings.items[-1] if settings.items else None
        settings.add_item(last.a if last else 1, last.b if last else 0)

    def _on_press(self, context, settings, layout, target, x, y):
        """处理一次点击；返回 ``"EXIT"`` 表示要收起面板。"""
        if target is None:
            return None
        kind = target["kind"]
        ident = target["id"]

        if kind == "node":
            self._drag = ident
            hud.session()["drag"] = ident
        elif kind == "flag":
            settings.toggle_flag(int(target["index"]), str(target["flag"]))
        elif kind == "bar":
            # 拖标题栏搬面板
            self._drag = "bar"
            origin = hud.session()["origin"]
            self._drag_offset = (x - origin[0], y - origin[1])
        elif ident == "btn:close":
            return "EXIT"
        elif ident.startswith("btn:domain:"):
            settings.domain = ident.rsplit(":", 1)[-1]
            hud.reset_view()
        elif ident == "btn:level:+":
            settings.level = min(LEVEL_MAX, int(settings.level) + 1)
        elif ident == "btn:level:-":
            settings.level = max(LEVEL_MIN, int(settings.level) - 1)
        elif ident == "btn:add":
            self._append_segment(settings)
            hud.reset_view()
        elif ident == "btn:remove":
            settings.remove_item(-1)
            hud.reset_view()
        elif ident == "btn:fit":
            hud.reset_view()
        elif ident in {"btn:help", "help:close"}:
            hud.toggle_help(None if ident == "btn:help" else False)
        hud.tag_redraw()
        return None

    def _on_mouse_move(self, context, settings, layout, x, y) -> None:
        session = hud.session()
        if self._drag == "bar":
            # 搬面板：留一点边在外面，别让用户把整块面板拖进看不见的地方
            region = getattr(context, "region", None)
            if region is not None:
                session["size"] = [region.width, region.height]
            _panel_x, _panel_y, panel_w, panel_h = layout["panel"]
            area_w, area_h = session["size"]
            session["origin"] = [
                max(-panel_w + 80.0, min(x - self._drag_offset[0], area_w - 80.0)),
                max(-panel_h + 40.0, min(y - self._drag_offset[1], area_h - 30.0)),
            ]
            hud.tag_redraw()
            return
        if self._drag.startswith("node:"):
            index = int(self._drag.split(":", 1)[1])
            origin = layout["lattice_origin"]
            a, b = hud_layout.snap(settings.domain, x, y, origin[0], origin[1], layout["zoom"])
            if settings.move_node(index, a, b):
                hud.tag_redraw()
            return
        hovered = hud_layout.hit(layout["hotspots"], x, y)
        ident = hovered["id"] if hovered else ""
        if ident != session.get("hover"):
            session["hover"] = ident
            self._set_cursor(context, _cursor_for(hovered))
            hud.tag_redraw()

    @staticmethod
    def _inside(layout, x, y) -> bool:
        px, py, pw, ph = layout["panel"]
        return px <= x <= px + pw and py <= y <= py + ph
