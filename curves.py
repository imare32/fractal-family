"""Curve assembly: plain output (one spline per level) and shape-key output.

Two ways to write a level set:

* :func:`create_curve` — **one** curve datablock, one spline per level.  Used for normal
  output; the levels keep their own vertex counts.
* :func:`create_curve_poly` / :func:`create_curve_smooth` — **one** curve per level, every
  level subdivided to the same vertex count.  That equality is what makes shape keys work:
  the morph between levels is then a plain per-vertex interpolation with no retopology.

Polyline output uses **POLY splines**, smooth output **BEZIER** ones.  This is not only
semantically right (a polyline has no tangents), it is also much faster: setting a handle
type is a per-point RNA write, and a level-14 curve has 16 k points per spline — that alone
used to cost seconds per curve.
"""

from __future__ import annotations

from dataclasses import dataclass

import bpy
import numpy as np
from mathutils import Vector

__all__ = [
    "append_spline",
    "create_curve",
    "create_curve_poly",
    "create_curve_smooth",
    "new_curve",
    "set_handle_type",
    "set_shape_key_coords",
    "spline_coords",
    "subdivide_curve",
]


def _vector(row) -> Vector:
    """``(x, y)`` / ``(x, y, z)`` → mathutils vector."""
    values = [float(component) for component in row]
    if len(values) == 2:
        return Vector((values[0], values[1], 0.0))
    return Vector(values[:3])


#: ``handle_*_type`` 的枚举数值按 RNA 现查（``FREE`` 是 0，``AUTO`` 却是 1 —— 不能写死）。
_ENUM_VALUES: dict = {}


def _enum_value(struct_type, prop_name: str, identifier: str) -> int:
    """RNA 枚举的数值（``foreach_set`` 只接受数值）。"""
    key = (struct_type.__name__, prop_name, identifier)
    cached = _ENUM_VALUES.get(key)
    if cached is not None:
        return cached
    prop = struct_type.bl_rna.properties[prop_name]
    value = next(item.value for item in prop.enum_items if item.identifier == identifier)
    _ENUM_VALUES[key] = value
    return value


def _poly_points(curve, points, closed: bool):
    """Append a POLY spline (straight segments, no handles to maintain).

    One ``foreach_set`` on a contiguous float array instead of a Python list of four
    floats per point: at a million points the list alone cost hundreds of MB.
    """
    spline = curve.splines.new("POLY")
    array = np.asarray(points, dtype=np.float32)
    if array.size == 0:
        return spline
    array = array.reshape(-1, 2)
    spline.points.add(len(array) - 1)
    packed = np.zeros((len(array), 4), dtype=np.float32)
    packed[:, :2] = array
    packed[:, 3] = 1.0
    spline.points.foreach_set("co", packed.ravel())
    spline.use_cyclic_u = bool(closed)
    return spline


def _bezier_points(curve, points, closed: bool):
    """Append a BEZIER spline with ``AUTO`` handles (smooth).

    Handle *types* are written in bulk, then **one** point setter is assigned: that single
    RNA write triggers Blender's ``BKE_nurb_handle_calc`` for every ``AUTO`` point.  Writing
    the type per point instead recalculates the whole spline each time — quadratic, and the
    reason a level-14 smooth curve took seconds.
    """
    spline = curve.splines.new("BEZIER")
    array = np.asarray(points, dtype=np.float32)
    if array.size == 0:
        return spline
    array = array.reshape(-1, 2)
    bezier_points = spline.bezier_points
    bezier_points.add(len(array) - 1)
    co = np.zeros((len(array), 3), dtype=np.float32)
    co[:, :2] = array
    bezier_points.foreach_set("co", co.ravel())
    auto = _enum_value(bpy.types.BezierSplinePoint, "handle_left_type", "AUTO")
    bezier_points.foreach_set("handle_left_type", np.full(len(array), auto, dtype=np.int32))
    bezier_points.foreach_set("handle_right_type", np.full(len(array), auto, dtype=np.int32))
    bezier_points[0].handle_left_type = "AUTO"  # fills every AUTO handle in one pass
    spline.use_cyclic_u = bool(closed)
    return spline


# ---------------------------------------------------------------------------
# Plain output: one object, one spline per level
# ---------------------------------------------------------------------------


def new_curve(name: str = "Curve"):
    """An empty curve datablock to be filled with :func:`append_spline`.

    Filling it level by level is what makes streaming possible: the datablock is created
    first, each level is appended as it is produced, and the numpy array behind it can be
    dropped immediately.  Keeping the whole ladder alive until the end costs about as much
    again as the curve itself.
    """
    return bpy.data.curves.new(name=name, type="CURVE")


def append_spline(curve, points, spline_type: str = "POLY", closed: bool = False):
    """Append one spline to ``curve``; returns it (``None`` for fewer than two points)."""
    array = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(array) < 2:
        return None
    if spline_type == "SMOOTH":
        return _bezier_points(curve, array, closed)
    return _poly_points(curve, array, closed)


def create_curve(lines, name: str = "Curve", spline_type: str = "POLY", closed: bool = False):
    """One curve datablock with one spline per entry of ``lines`` (lowest level first)."""
    curve = new_curve(name)
    for line in lines:
        append_spline(curve, line, spline_type, closed)
    return curve


# ---------------------------------------------------------------------------
# Shape-key output: one object, one shape key per level
# ---------------------------------------------------------------------------


def _subdivide_poly(array, num_segments: int, closed: bool):
    """Linear subdivision: every segment becomes ``num_segments`` segments.

    Vectorised: the shape-key path subdivides every level up to the top point count, which
    is tens of thousands of points — a Python loop over numpy rows was the slow part.
    """
    array = np.asarray(array, dtype=float).reshape(-1, 2)
    num_segments = max(1, int(num_segments))
    if num_segments == 1:
        return array
    if len(array) < 2:
        return array
    if closed:
        starts, ends = array, np.roll(array, -1, axis=0)
    else:
        starts, ends = array[:-1], array[1:]
    steps = (np.arange(num_segments) / num_segments).reshape(num_segments, 1)
    points = starts[:, None, :] + (ends - starts)[:, None, :] * steps[None, :, :]
    points = points.reshape(-1, 2)
    if not closed:
        points = np.vstack([points, array[-1:]])
    return points


def create_curve_poly(points, name: str = "Curve", num_segments: int = 1, closed: bool = False):
    """Single POLY spline, linearly subdivided so the vertex count is predictable."""
    array = np.asarray(points, dtype=float).reshape(-1, 2)
    array = _subdivide_poly(array, num_segments, closed)
    curve = bpy.data.curves.new(name=name, type="CURVE")
    _poly_points(curve, array, closed)
    return curve


def create_curve_smooth(points, name: str = "Curve", num_segments: int = 1, closed: bool = False):
    """Single BEZIER spline, subdivided without changing its shape.

    The subdivision is shape-preserving (the Bezier segments are cut into pieces), so the
    vertex count grows while the curve stays exactly where it was.
    """
    array = np.asarray(points, dtype=float).reshape(-1, 2)
    curve = bpy.data.curves.new(name=name, type="CURVE")
    _bezier_points(curve, array, closed)
    subdivide_curve(curve, max(1, int(num_segments)))
    return curve


def set_handle_type(curve, handle_type: str = "AUTO") -> None:
    """Set both handle types of every point in the first spline (BEZIER only).

    Bulk write + one setter, for the same reason as :func:`_bezier_points`: a per-point enum
    assignment recalculates the whole spline.
    """
    if not curve.splines or curve.splines[0].type != "BEZIER":
        return
    bezier_points = curve.splines[0].bezier_points
    count = len(bezier_points)
    if not count:
        return
    try:
        value = _enum_value(bpy.types.BezierSplinePoint, "handle_left_type", handle_type)
    except StopIteration:
        return
    filled = np.full(count, value, dtype=np.int32)
    bezier_points.foreach_set("handle_left_type", filled)
    bezier_points.foreach_set("handle_right_type", filled)
    bezier_points[0].handle_left_type = handle_type  # one pass fills every handle


def spline_coords(curve):
    """Flat ``[x, y, z, ...]`` coordinates of the first spline (POLY or BEZIER)."""
    if not curve.splines:
        return np.empty(0, dtype=np.float32)
    spline = curve.splines[0]
    if spline.type == "POLY":
        raw = np.empty(4 * len(spline.points), dtype=np.float32)
        spline.points.foreach_get("co", raw)
        return np.ascontiguousarray(raw.reshape(-1, 4)[:, :3].ravel())
    raw = np.empty(3 * len(spline.bezier_points), dtype=np.float32)
    spline.bezier_points.foreach_get("co", raw)
    return raw


def set_shape_key_coords(key, coords) -> bool:
    """Write a flat xyz sequence into a curve shape key; ``False`` when the counts differ."""
    if key is None or 3 * len(key.data) != len(coords):
        return False
    key.data.foreach_set("co", np.ascontiguousarray(coords, dtype=np.float32))
    return True


@dataclass
class _Segment:
    """One cubic Bezier segment: start, two controls, end."""

    start: Vector
    ctrl1: Vector
    ctrl2: Vector
    end: Vector

    def partial(self, t0: float = 0.0, t1: float = 1.0) -> "_Segment":
        """The ``[t0, t1]`` piece (closed form of the de Casteljau split)."""
        p0, p1, p2, p3 = self.start, self.ctrl1, self.ctrl2, self.end
        if t0 > t1:
            t0, t1 = t1, t0
        if p0 == p1 and p2 == p3:  # already a straight segment: plain interpolation
            return _Segment(
                p0 * (1 - t0) + p2 * t0, p0 * (1 - t0) + p2 * t0,
                p0 * (1 - t1) + p2 * t1, p0 * (1 - t1) + p2 * t1,
            )
        u0, u1 = 1.0 - t0, 1.0 - t1
        qa = p0 * (u0 * u0) + p1 * (2 * t0 * u0) + p2 * (t0 * t0)
        qb = p0 * (u1 * u1) + p1 * (2 * t1 * u1) + p2 * (t1 * t1)
        qc = p1 * (u0 * u0) + p2 * (2 * t0 * u0) + p3 * (t0 * t0)
        qd = p1 * (u1 * u1) + p2 * (2 * t1 * u1) + p3 * (t1 * t1)
        return _Segment(
            qa * u0 + qc * t0, qa * u1 + qc * t1, qb * u0 + qd * t0, qb * u1 + qd * t1,
        )


def _spline_segments(spline) -> list:
    """All segments of a spline (closing segment included for cyclic splines)."""
    points = spline.bezier_points
    segments = [
        _Segment(points[index - 1].co, points[index - 1].handle_right,
                 points[index].handle_left, points[index].co)
        for index in range(1, len(points))
    ]
    if spline.use_cyclic_u and len(points) > 1:
        segments.append(_Segment(points[-1].co, points[-1].handle_right,
                                 points[0].handle_left, points[0].co))
    return segments


def subdivide_curve(curve, no_segs: int = 1) -> None:
    """Shape-preserving subdivision of the first spline: same shape, more points."""
    if no_segs < 2 or not curve.splines:
        return
    original = curve.splines[0]
    is_cyclic = original.use_cyclic_u

    pieces = []
    for segment in _spline_segments(original):
        pieces.extend(
            segment.partial(index / no_segs, (index + 1) / no_segs) for index in range(no_segs)
        )
    if not pieces:
        return

    points = []
    previous = None
    for index, piece in enumerate(pieces):
        if index == 0:
            handle_left = pieces[-1].ctrl2 if is_cyclic else piece.start
        else:
            handle_left = previous.ctrl2
        points.append([piece.start, handle_left, piece.ctrl1])
        previous = piece
    if is_cyclic:
        points[-1][2] = pieces[-1].ctrl1
    else:
        points.append([previous.end, previous.ctrl2, previous.end])

    spline = curve.splines.new("BEZIER")
    spline.use_cyclic_u = is_cyclic
    bezier_points = spline.bezier_points
    bezier_points.add(len(points) - 1)

    # Bulk write: co / handles are plain float vectors, and the handle *type* is the only
    # enum here — setting it per point recalculated the whole spline (quadratic).
    co = np.empty((len(points), 3), dtype=np.float32)
    left = np.empty((len(points), 3), dtype=np.float32)
    right = np.empty((len(points), 3), dtype=np.float32)
    for index, (point, handle_left, handle_right) in enumerate(points):
        co[index] = point[:3]
        left[index] = handle_left[:3]
        right[index] = handle_right[:3]
    bezier_points.foreach_set("co", co.ravel())
    bezier_points.foreach_set("handle_left", left.ravel())
    bezier_points.foreach_set("handle_right", right.ravel())
    free = _enum_value(bpy.types.BezierSplinePoint, "handle_right_type", "FREE")
    bezier_points.foreach_set("handle_right_type", np.full(len(points), free, dtype=np.int32))
    curve.splines.remove(original)
