"""Viewport preview: draw the **current level** in the 3D view, no temporary data-blocks.

The 1.x preview created a hidden collection (``__fractalfamily_preview__``) with three
curve objects and wrote points into ``curve.splines``: it left objects in the outliner,
could be selected or deleted by accident, got saved into the file, and had to be hidden
again when switched off.  This is a ``POST_VIEW`` draw handler instead: one pass per
frame, nothing left behind, and what you see comes from the same code that generates the
final curve.

One level, one line:

* only the **current level** is drawn (``settings.preview_level()``) — stacking every
  level on top of each other ("onion skin") made it hard to tell which line was the one
  that Generate would produce, and the colour ramp implied an ordering that is not there;
* the colour is the level's own fixed colour (:func:`palette.level_colour`, one entry per
  level), so the line tells you which level you are looking at and the HUD hint can use
  exactly the same colour;
* the line width is a single constant: the driver quantises ``line_width`` (5.2 measured:
  1.2 / 1.45 / 1.7 / 1.96 / 2.5 all become 2 px, 3.4 becomes 4 px), so a width per level
  would be a promise the platform cannot keep;
* everything lies on the XY plane (z = 0), the plane of the generated curve;
* the 3D view goes through colour management, so colours are converted to linear first.

Cache: the point set is recomputed only when gene / domain / level / initiator change —
the key is :meth:`props.GenFractalFamilySettings.geometry_signature`.  Orbiting the view
or dragging panel sliders hits the cache.
"""

from __future__ import annotations

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from .lattice import FractalGenerator, teragon
from .palette import hex_to_rgb, level_colour, srgb_to_linear

#: 最近一次绘制失败的原因（面板「状态」里显示；成功画一帧就清掉）。
_LAST_ERROR = None


def last_error():
    """最近一次预览绘制失败的原因；没有则返回 ``None``。"""
    return _LAST_ERROR


#: Width of the preview line in pixels.  One constant on purpose: the driver quantises
#: ``line_width`` and macOS ignores values above 1 px, so any per-level ramp would be a
#: promise the platform cannot keep.  The colour carries the information instead.
LINE_WIDTH = 2.0


__all__ = [
    "install",
    "last_error",
    "line_vertices",
    "lines_for",
    "remove",
    "tag_redraw",
]

#: 句柄：模块变量是主，``driver_namespace`` 只是跨热重载的兜底（见根 README）。
_HANDLE = None
_HANDLE_KEY = "fractalfamily_preview_handle"
_HANDLE_REGION = "WINDOW"

#: 点列缓存（键 = :meth:`props.GenFractalFamilySettings.geometry_signature`）。
#: ``closed`` 与 ``lines`` 一起缓存：它只由初始折线决定，重算点列时顺手带出来。
_CACHE = {"key": None, "lines": [], "closed": False}

#: 每次绘制重建的 batch 缓存（键同上；文件加载后 GPU 资源可能失效，出错就清空重来）。
_BATCH = {"key": None, "items": []}


# ---------------------------------------------------------------------------
# 几何：取参数 → 分级折线
# ---------------------------------------------------------------------------


def _initiator(settings):
    """初始折线 ``(points, closed)``；直线时返回 ``(None, False)``。

    来源（直线 / 正多边形 / 自定义初始折线）由
    :meth:`props.GenFractalFamilySettings.initiator` 决定，与生成共用同一份。
    """
    return settings.initiator()


def line_vertices(line, closed: bool = False) -> np.ndarray:
    """折线 → ``(n, 3)`` 顶点数组（``z = 0``；闭合时补上首点）。

    闭合的初始折线（正多边形 / 闭合样条）在 :func:`lattice.teragon` 里**已经去掉**了那个
    "回到起点"的重复点 —— 生成物靠 ``spline.use_cyclic_u`` 自己闭合，而预览用的是
    ``LINE_STRIP``：不在这里补一段"末点 → 首点"，画出来就差最后一条边（生成的是闭合的，
    预览却开着一个口子）。
    """
    vertices = np.column_stack([line[:, 0], line[:, 1], np.zeros(len(line))])
    if closed and len(vertices) > 2:
        vertices = np.vstack([vertices, vertices[:1]])
    return vertices


def _cached(settings):
    """``(lines, closed)``：当前参数对应的分级折线与闭合标记（带缓存）。"""
    key = settings.geometry_signature()
    if _CACHE["key"] == key:
        return _CACHE["lines"], _CACHE["closed"]

    lines = []
    closed = False
    if settings.is_valid():
        generator = FractalGenerator(settings.elements())
        initiator, closed = _initiator(settings)
        # The level already respects the point budget (props.preview_level): the cap is a
        # point count, not a level number, so simple genes preview much deeper.
        level = settings.preview_level()
        try:
            lines = teragon(generator, level, initiator, closed)
        except (ValueError, ZeroDivisionError):
            lines = []
            closed = False
    _CACHE["key"] = key
    _CACHE["lines"] = lines
    _CACHE["closed"] = closed
    _BATCH["key"] = None
    return lines, closed


def lines_for(settings):
    """当前参数对应的分级折线（``[np.ndarray (n, 2), ...]``，带缓存）。"""
    return _cached(settings)[0]


def _batches(settings):
    """``[(batch, rgba, width, shader)]`` for the **current level** only.

    ``lines`` always ends at the current level (``settings.preview_level()``), so the last
    entry is the one Generate would produce.  The colour comes from the level number, the
    width is a single constant (see :data:`LINE_WIDTH`).
    """
    lines, closed = _cached(settings)
    if not lines:
        return []
    line = lines[-1]
    if len(line) < 2:
        return []
    index = len(lines) - 1
    ramp = getattr(settings, "preview_ramp", "FAMILY")
    # The key must include the ramp and the picked colour: they only affect drawing, so a
    # stale batch would keep the old colour until something else changes.
    key = (
        settings.geometry_signature(),
        str(ramp),
        tuple(round(float(component), 4) for component in settings.preview_colour),
    )
    if _BATCH["key"] == key:
        return _BATCH["items"]

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    if ramp == "MONO":
        base = tuple(float(component) for component in settings.preview_colour)
    else:
        base = hex_to_rgb(level_colour(index))
    colour = (
        srgb_to_linear(base[0]),
        srgb_to_linear(base[1]),
        srgb_to_linear(base[2]),
        1.0,
    )
    # A closed initiator needs the closing "last → first" segment, otherwise LINE_STRIP
    # leaves a visible gap.
    vertices = line_vertices(line, closed)
    # Contiguous float32: a non-contiguous view is uploaded as garbage (and silently
    # draws nothing) on some builds, and numpy 2.x changed what ``astype`` guarantees.
    positions = np.ascontiguousarray(vertices, dtype=np.float32)
    batch = batch_for_shader(shader, "LINE_STRIP", {"pos": positions})
    items = [(batch, colour, LINE_WIDTH, shader)]
    _BATCH["key"] = key
    _BATCH["items"] = items
    return items


# ---------------------------------------------------------------------------
# 绘制
# ---------------------------------------------------------------------------


def _settings():
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return None
    return getattr(scene, "fractalfamily", None)


def _draw():
    """``POST_VIEW`` 回调：每个 3D 视图各调一次，只画线，别在这里做重活。"""
    global _LAST_ERROR
    settings = _settings()
    if settings is None or not settings.show_preview:
        return
    try:
        items = _batches(settings)
        _LAST_ERROR = None
    except Exception as exception:
        # 这里**必须**兜住：draw handler 抛异常会刷一屏报错。但也不能白吞 ——
        # 记住最后一条，面板「状态」里会显示出来（早期就是这样静默失败，
        # 表现为"等级 1/2 时预览什么都不显示"，查了很久）。
        message = f"{type(exception).__name__}: {exception}"
        if message != _LAST_ERROR:  # 每帧都打一遍会刷屏，只在变化时打
            import traceback

            _LAST_ERROR = message
            traceback.print_exc()
        _BATCH["key"] = None
        _CACHE["key"] = None
        return
    if not items:
        return

    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    try:
        for batch, colour, width, shader in items:
            gpu.state.line_width_set(max(1.0, width))
            shader.bind()
            shader.uniform_float("color", colour)
            batch.draw(shader)
    finally:
        # Restore the defaults the next draw handler expects: leaving depth testing on makes
        # the HUD (drawn later, also in this area) disappear behind scene geometry.
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")
        gpu.state.depth_test_set("NONE")


# ---------------------------------------------------------------------------
# 句柄装卸
# ---------------------------------------------------------------------------


def tag_redraw() -> None:
    """请求所有 3D 视图重绘（参数一变就调，立即模式绘制才会跟上）。"""
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


def install() -> None:
    """挂上 ``POST_VIEW`` 句柄（重复调用不会重复挂）。"""
    global _HANDLE
    remove()
    _HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw, (), _HANDLE_REGION, "POST_VIEW")
    bpy.app.driver_namespace[_HANDLE_KEY] = (_HANDLE, _HANDLE_REGION)


def remove() -> None:
    """摘掉句柄（``unregister`` 必须调，否则重载会残留两份）。"""
    global _HANDLE
    stored = bpy.app.driver_namespace.pop(_HANDLE_KEY, None)
    candidates = [_HANDLE]
    if isinstance(stored, tuple):
        candidates.append(stored[0])
    elif stored is not None:
        candidates.append(stored)
    for handle in candidates:
        if handle is None:
            continue
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, _HANDLE_REGION)
        except (ValueError, TypeError):
            pass
    _HANDLE = None
    _BATCH["key"] = None
    _CACHE["key"] = None
