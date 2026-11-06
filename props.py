"""场景参数：``scene.fractalfamily``。

面板、HUD、预览、生成算子读的都是这一套值；改基因的入口有三个（预设下拉、基因列表、
HUD），写进去的都是同一份 ``items``。

参数分两档：

* **几何档**（域 / 基因 / 等级 / 初始折线 / 形态）：动它就把 ``dirty`` 标起来，等用户按
  「生成」时才写数据块。RNA 回调里**不直接写几何** —— 拖滑块 / 撤销的当口写数据块等于
  从脚下抽走数据；视口预览本来就每帧按最新参数重画，所以不需要为此重算任何东西；
* **就地档**（预览配色 / 预览颜色 / 预览与 HUD 开关）：只影响 ``gpu`` 立即模式绘制的
  视口预览，拖滑块是实时的。

**不要**加 ``from __future__ import annotations``：``bpy.props`` 的注解必须是真实的
``Property`` 对象，PEP 563 的字符串注解会让注册失败。
"""

import bpy
import numpy as np

from . import budget
from . import sysinfo
from .lattice import (
    DOMAINS,
    ComplexInteger,
    FractalGenerator,
    format_gene,
    gene_family,
    parse_gene,
    polygon_initiator,
    total_vector,
)
from .i18n import t, tfmt
from .palette import CINNABAR, hex_to_rgb
from .presets import DEFAULT_GENES, GENES_BY_NAME

__all__ = [
    "INITIATOR_SIDES",
    "LEVEL_MAX",
    "LEVEL_MIN",
    "PREVIEW_POINT_BUDGET",
    "GeneratorItem",
    "GenFractalFamilySettings",
    "register",
]

#: 「正多边形」初始形状 → 边数（:attr:`GenFractalFamilySettings.initiator_shape`）。
INITIATOR_SIDES = {
    "TRIANGLE": 3,
    "SQUARE": 4,
    "PENTAGON": 5,
    "HEXAGON": 6,
    "OCTAGON": 8,
}

#: Point budget for the viewport preview.  There is **no fixed level cap**: the level is
#: reduced until the point count fits this budget, so complexity decides — a 2-segment
#: gene such as Dragon previews up to level 16, a 9-segment gene stops around level 5.
#:
#: The four budget constants below are now **fallbacks**: the live values come from
#: :mod:`budget`, which derives them from the machine (available memory and a measured
#: ns/point factor).  They stay as public names so nothing that imports them breaks, and
#: they document the shape of the limits an unknown platform falls back to.
PREVIEW_POINT_BUDGET = budget.PREVIEW_CEILING

#: Shape keys are much more expensive than the preview: every level is subdivided up to the
#: same vertex count, so the build cost is roughly ``levels × points(top level)``.  Capped
#: well below the preview — at high levels the extra detail is sub-pixel anyway and the
#: build takes long enough to hang Blender.  The budget decides: Dragon (2 elements) reaches
#: level 14 (16 385 points per key), a 5-element gene level 6, a 9-element gene level 4.
SHAPE_KEY_MAX_LEVEL = 16
SHAPE_KEY_POINT_BUDGET = budget.FALLBACK_KEY_POINTS

#: Point budget for **one Generate click** (plain curve output).  The point count grows
#: exponentially with the level (``segments × count ** level``), and unlike the preview and
#: the shape keys there is nothing to draw before the whole curve exists — a nine-element
#: gene at level 7 is already ~4.8 million points and level 8 is ~43 million, which cannot be
#: built (memory) or cancelled.  The live value comes from :mod:`budget`; this is the
#: fallback for platforms where the machine size cannot be read, and the number every
#: existing user already lives with.
OUTPUT_POINT_BUDGET = budget.FALLBACK_POINTS

#: 等级允许的硬范围。``LEVEL_MAX`` 既是属性的上限（能填到几），也是本机能生成的上限：
#: 实际写出的等级是 ``min(LEVEL_MAX, 点数预算算出来的级数)``，见
#: :meth:`GenFractalFamilySettings.output_level_limit`。超过 24 级对任何还装得下的基因
#: 都是亚像素级的差别，所以这里就是终点，不需要再叠一层「档位上限」。
LEVEL_MIN = 1
LEVEL_MAX = 24

#: 预览线的默认色：色板的朱砂。
_HEX_PREVIEW = hex_to_rgb(CINNABAR)


def _settings(context):
    """从 context 取参数组；拿不到（后台 / 加载中）返回 ``None``。"""
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    return getattr(scene, "fractalfamily", None)


def _mark_dirty(self, context):
    """几何档参数变了：标记「待生成」。

    这里**只标状态**：预览由 draw handler 每帧按最新参数画（不需要重算任何数据块），
    已生成的对象要等用户自己按「生成」。
    """
    settings = _settings(context)
    if settings is None:
        return
    settings.dirty = True
    # The over-budget question quotes memory and time for the settings as they were when
    # Generate was clicked.  The output controls are greyed out while it is on screen, but
    # Level, presets, gene segments and the initiator are edited elsewhere (and by the HUD
    # and by scripts).  Any such edit invalidates those numbers: drop the question rather
    # than let the user answer a stale one.  Usually a no-op.
    settings.pending_generate = ""


def _on_domain_change(self, context):
    """切域：基因不变，只是换点阵映射 —— 重算但不必改坐标。"""
    _mark_dirty(self, context)


def _preset_items(self, context):
    """预设下拉的条目：**家族名在前、曲线名在后**（如 ``G(1, 1) Dragon Curve``）。

    标识符仍然是曲线名（:data:`presets.GENES_BY_NAME` 的键），所以换标签不影响存盘 /
    回读；家族名放前面是为了在同一段下拉里一眼看出哪些是同族。
    """
    return [
        (item["name"], f"{item['family']} {item['name']}", f"{item['family']} · {item['gene']}")
        for item in DEFAULT_GENES
    ]


def _on_preset_change(self, context):
    """选中预设 → 直接把基因写进去（与原版一致：选完就能看）。"""
    # This callback does not go through :func:`_mark_dirty`, so the stale-question guard
    # has to be here too: a different gene means a completely different point count.
    self.pending_generate = ""
    item = GENES_BY_NAME.get(self.preset)
    if item:
        self.apply_gene(item["gene"])


def _on_geometry_toggle(self, context):
    """预览开关 / 线宽 / 颜色 / 输出模式：只影响视口立即模式绘制，标一次重绘即可。"""
    from . import hud

    hud.tag_redraw()


def _curve_points(curve, reverse: bool = False):
    """曲线对象的第 1 条样条 → ``(numpy (n, 2), closed)``；不可用时 ``(None, False)``。

    只取局部坐标、忽略对象变换（与参考实现一致）；Bezier 与 NURBS/多段线都认。
    """
    if curve is None or not getattr(curve, "splines", None) or not curve.splines:
        return None, False
    spline = curve.splines[0]
    points = []
    if spline.type == "BEZIER" and len(spline.bezier_points) > 1:
        points = [(point.co[0], point.co[1]) for point in spline.bezier_points]
    elif len(spline.points) > 1:
        points = [(point.co[0], point.co[1]) for point in spline.points]
    if len(points) < 2:
        return None, False
    if reverse:
        points.reverse()
    return np.asarray(points, dtype=float), bool(spline.use_cyclic_u)


def _curve_shape(curve):
    """``(段数, 是否闭合)``，不把点列读出来。

    :func:`scene.fractalfamily` 的签名与估点数每帧都要问一次初始曲线有几段；为此把整条
    曲线的点都过一遍 RNA，长曲线会让视口掉帧。
    """
    if curve is None or not getattr(curve, "splines", None) or not curve.splines:
        return 0, False
    spline = curve.splines[0]
    if spline.type == "BEZIER":
        count = len(spline.bezier_points)
    elif spline.type == "POLY":
        count = len(spline.points)
    else:
        points, closed = _curve_points(curve)
        return (0 if points is None else len(points)), closed
    if count < 2:
        return 0, False
    return count, bool(spline.use_cyclic_u)


def _curve_sample(curve, limit: int = 8):
    """前 ``limit`` 个点的 ``(x, y)``（保留四位小数）——签名采样，不读整条曲线。"""
    if curve is None or not getattr(curve, "splines", None) or not curve.splines:
        return ()
    spline = curve.splines[0]
    points = spline.bezier_points if spline.type == "BEZIER" else spline.points
    sample = []
    for index in range(min(limit, len(points))):
        co = points[index].co
        sample.append((round(float(co[0]), 4), round(float(co[1]), 4)))
    return tuple(sample)


def _on_initiator_curve(self, context):
    """指定了曲线对象就顺手勾上「自定义曲线」—— 否则填了曲线却不生效，很难猜。

    那个开关自己的 ``update`` 会标脏 + 排重算，这里不用再补一次。
    """
    if self.initiator_curve is not None and not self.initiator_custom:
        self.initiator_custom = True
        return
    _mark_dirty(self, context)


class GeneratorItem(bpy.types.PropertyGroup):
    """基因里的一段：复整数 ``(a, b)`` + 两个变换标记。"""

    a: bpy.props.IntProperty(
        name="A",
        description="First component of the complex integer (real part in G, "
                    "coefficient of omega in E)",
        default=0,
        soft_min=-16,
        soft_max=16,
        update=_mark_dirty,
    )

    b: bpy.props.IntProperty(
        name="B",
        description="Second component of the complex integer",
        default=1,
        soft_min=-16,
        soft_max=16,
        update=_mark_dirty,
    )

    reverse: bpy.props.BoolProperty(
        name="Reverse",
        description="Use the previous level backwards for this segment (R)",
        default=False,
        update=_mark_dirty,
    )

    mirror: bpy.props.BoolProperty(
        name="Mirror",
        description="Mirror the previous level for this segment (M)",
        default=False,
        update=_mark_dirty,
    )


class GenFractalFamilySettings(bpy.types.PropertyGroup):
    """``scene.fractalfamily``：一次生成所需的全部输入。"""

    # --- 基因 -------------------------------------------------------------

    domain: bpy.props.EnumProperty(
        name="Domain",
        description="Lattice: G = Gaussian integers (square), E = Eisenstein integers "
                    "(triangular)",
        items=[
            ("G", "Gaussian G", "Square lattice: a + bi"),
            ("E", "Eisenstein E", "Triangular lattice: a + b*omega"),
        ],
        default="G",
        update=_on_domain_change,
    )

    items: bpy.props.CollectionProperty(type=GeneratorItem)

    active_index: bpy.props.IntProperty(name="Active Segment", default=0, min=0)

    preset: bpy.props.EnumProperty(
        name="Preset",
        description="Pick a classic gene (applied immediately, then still editable)",
        items=_preset_items,
        update=_on_preset_change,
    )

    gene: bpy.props.StringProperty(
        name="Gene",
        description="Current gene as a string (read-only display; use Paste Gene to import)",
        default="",
    )

    # --- 预览（就地生效） -------------------------------------------------

    show_preview: bpy.props.BoolProperty(
        name="Viewport Preview",
        description=("Draw the current level directly in the 3D viewport, so you can see the "
                     "gene change while you edit it"),
        default=False,
        update=_on_geometry_toggle,
    )

    preview_ramp: bpy.props.EnumProperty(
        name="Colour Ramp",
        description=("How the preview line is coloured: the level's own fixed colour (so "
                     "the colour tells you which level you are looking at, levels above 6 "
                     "share the last one), or one colour you pick yourself"),
        items=(
            ("FAMILY", "Level Colour",
             "Each level has its own fixed colour; the HUD hint uses the same one"),
            ("MONO", "Single Colour",
             "Use the preview colour for every level"),
        ),
        default="FAMILY",
        update=_on_geometry_toggle,
    )

    preview_colour: bpy.props.FloatVectorProperty(
        name="Preview Colour",
        description="Line colour in Single Colour mode (sRGB)",
        size=3,
        subtype="COLOR_GAMMA",
        default=_HEX_PREVIEW,
        min=0.0,
        max=1.0,
        update=_on_geometry_toggle,
    )

    # --- 等级（编辑 / 预览 / 输出范围） -----------------------------------

    level: bpy.props.IntProperty(
        name="Level",
        description=("Level being edited and previewed — the HUD wheel changes this one. "
                     "Substitution count: level 0 is the initiator, level 1 the gene "
                     "itself, every level above replaces each segment with the whole "
                     "previous level"),
        default=4,
        min=LEVEL_MIN,
        max=LEVEL_MAX,
        update=_mark_dirty,
    )

    use_range: bpy.props.BoolProperty(
        name="Output Range",
        description=("Write several levels instead of only the current one. Each level "
                     "becomes its own object unless Join Levels is enabled"),
        default=False,
        update=_mark_dirty,
    )

    join_objects: bpy.props.BoolProperty(
        name="Join Levels",
        description=("Put every level of the range into one object, one spline per level. "
                     "Off: one object per level"),
        default=False,
        update=_mark_dirty,
    )

    level_from: bpy.props.IntProperty(
        name="Range From",
        description=("First level written to the object. Equal to Range To gives a single "
                     "curve; a wider range puts every level into one object, one spline per "
                     "level. Output only — the HUD and preview keep using Level"),
        default=1,
        min=LEVEL_MIN,
        max=LEVEL_MAX,
        update=_mark_dirty,
    )

    level_to: bpy.props.IntProperty(
        name="Range To",
        description=("Last level written to the object (output only). Substitution count: "
                     "level 0 is the initiator, level 1 the gene itself, every level above "
                     "replaces each segment with the whole previous level"),
        default=4,
        min=LEVEL_MIN,
        max=LEVEL_MAX,
        update=_mark_dirty,
    )

    # --- 输出 -------------------------------------------------------------

    spline_type: bpy.props.EnumProperty(
        name="Spline",
        description="Spline type of the generated curves: polyline (straight segments) or "
                    "smooth (Bézier with automatic handles)",
        # The labels are Blender's own names for the two spline types (``Spline.type``), and
        # they already have translations in every Blender language pack: "Poly" and
        # "Bézier" read as 多段线 / 贝塞尔 in Chinese.  Naming them anything else here -- the
        # old "Polyline" / "Smooth" -- meant the panel used words the curve editor next door
        # does not, and made the two incompatible-looking.
        items=[
            ("POLY", "Poly", "Straight segments between the points"),
            ("SMOOTH", "Bézier", "Bézier auto handles, smooth between the points"),
        ],
        default="POLY",
        update=_mark_dirty,
    )

    initiator_shape: bpy.props.EnumProperty(
        name="Initiator",
        description=("Initiator polyline (level 0): a straight line or a regular polygon. "
                     "Polygons are computed on the fly with the side length equal to the "
                     "total vector, so closed fractals such as the Koch snowflake work with "
                     "one click. To use your own curve, enable Custom Curve below"),
        items=[
            ("LINE", "Line", "A straight line from the origin to the total vector (default)"),
            ("TRIANGLE", "Triangle", "Closed regular triangle: Koch snowflake"),
            ("SQUARE", "Square", "Closed square"),
            ("PENTAGON", "Pentagon", "Closed regular pentagon"),
            ("HEXAGON", "Hexagon", "Closed regular hexagon"),
            ("OCTAGON", "Octagon", "Closed regular octagon"),
        ],
        default="LINE",
        update=_mark_dirty,
    )

    initiator_custom: bpy.props.BoolProperty(
        name="Custom Curve",
        description=("Use the curve object below as the initiator polyline (the shape "
                     "choice above is kept and comes back when unchecked)"),
        default=False,
        update=_mark_dirty,
    )

    initiator_curve: bpy.props.PointerProperty(
        name="Initiator Curve",
        description=("Custom initiator polyline (first spline only, object transform "
                     "ignored). Only used when Custom Curve is enabled"),
        type=bpy.types.Curve,
        update=_on_initiator_curve,
    )

    initiator_reverse: bpy.props.BoolProperty(
        name="Reverse",
        description="Read the initiator points in reverse order (grows inwards instead of "
                    "outwards)",
        default=False,
        update=_mark_dirty,
    )

    # --- 状态（只读，面板上显示） -----------------------------------------
    #
    # Two kinds of state live here.  ``last_*`` / ``dirty`` describe the *file* (what was
    # generated, whether edits are pending) and travel with it.  Everything marked
    # ``SKIP_SAVE`` describes **one click** -- a progress bar, a pending question, a
    # notice -- and must not.  A .blend saved mid-build used to reopen with
    # ``running_fraction = 1.0``: the panel drew a progress bar instead of the Generate
    # buttons, and no modal operator existed any more to clear it, so generation was
    # unreachable until the user restarted.  ``reset_transient_state`` is the second half
    # of the fix: it also rescues files saved by older versions of the add-on.

    dirty: bpy.props.BoolProperty(name="Pending", default=True)

    last_points: bpy.props.IntProperty(name="Points", default=0)

    last_low: bpy.props.IntProperty(name="Generated From", default=0)

    last_level: bpy.props.IntProperty(name="Generated Level", default=0)

    last_ms: bpy.props.FloatProperty(name="Time", default=0.0)

    #: Live progress of a running modal build, as ``0.0-1.0``; negative means "not running".
    #: The panel draws the bar from these two rather than from a status-bar string: the
    #: status bar is far from the button the user just clicked, and on a multi-million point
    #: build it is the only feedback for several seconds.
    running_fraction: bpy.props.FloatProperty(default=-1.0, options={"SKIP_SAVE"})

    #: Current / top level of the running build (``0`` when nothing is running).
    running_level: bpy.props.IntProperty(default=0, options={"SKIP_SAVE"})

    running_high: bpy.props.IntProperty(default=0, options={"SKIP_SAVE"})

    #: Points expanded so far / in total for the running build, straight from the job -- not
    #: re-derived from the gene, which the user may have changed mid-build.
    running_points: bpy.props.IntProperty(default=0, options={"SKIP_SAVE"})

    #: How long the build itself takes, and how long the dependency-graph evaluation after it
    #: takes.  Both are predicted before the click (see :mod:`budget`).
    #:
    #: The panel needs them as *seconds*, not as a fraction of a bar: evaluation is one
    #: atomic ``view_layer.update()`` that cannot be split, so nothing on this side can make
    #: a bar advance through it.  Saying "28 %" and stopping there ("why is it stuck?") is
    #: worse than saying "evaluating, about 3 s left" and filling the bar over that estimate
    #: -- one is a mystery, the other is an explanation that happens to be a bar.
    running_build_s: bpy.props.FloatProperty(default=0.0, options={"SKIP_SAVE"})

    running_eval_s: bpy.props.FloatProperty(default=0.0, options={"SKIP_SAVE"})

    #: Wall-clock start of the evaluation phase (``0`` while still building).
    running_eval_start: bpy.props.FloatProperty(default=0.0, options={"SKIP_SAVE"})

    #: The level the user asked for, when :attr:`last_level` is lower because the budget
    #: only allowed that much. Kept separately so the panel (and the object name) can be
    #: honest about what happened instead of silently shipping less than requested.
    last_requested_level: bpy.props.IntProperty(name="Requested Level", default=0)

    #: ``""`` | ``DEGRADED`` | ``PREVIEW_ONLY`` | ``FORCED`` | ``REFUSED`` -- what the last
    #: Generate did.  ``REFUSED`` means the click wrote nothing at all: the requested level
    #: would exhaust the memory that is actually free, so even "generate it anyway" was not
    #: offered.
    notice_kind: bpy.props.StringProperty(default="", options={"SKIP_SAVE"})

    notice_requested: bpy.props.IntProperty(default=0, options={"SKIP_SAVE"})

    notice_actual: bpy.props.IntProperty(default=0, options={"SKIP_SAVE"})

    error: bpy.props.StringProperty(name="Error", default="", options={"SKIP_SAVE"})

    #: ``""`` | ``"CURVE"`` | ``"KEYS"`` -- a Generate is waiting for the user to choose
    #: between the requested level and the level that fits.  Set by :meth:`request_generate`
    #: and cleared by either answer.  Not a user setting: it is the state of one click.
    pending_generate: bpy.props.StringProperty(default="", options={"SKIP_SAVE"})

    def clear_notice(self) -> None:
        self.notice_kind = ""
        self.notice_requested = 0
        self.notice_actual = 0
        # The refusal / preview-only notices keep their full sentence in ``error``.  Leaving
        # it behind made a stale "Not enough memory" sit in Status next to the *next*
        # question, which was no longer about that failure.
        self.error = ""

    # --- 基因读写 ---------------------------------------------------------

    def elements(self):
        """当前基因：``[(ComplexInteger, (reverse, mirror)), ...]``。"""
        domain = self.domain
        return [
            (ComplexInteger(item.a, item.b, domain), (bool(item.reverse), bool(item.mirror)))
            for item in self.items
        ]

    def set_elements(self, elements, *, domain=None) -> None:
        """整条基因一次写完（预设 / 导入走这里）。"""
        if domain is not None and domain in DOMAINS:
            self.domain = domain
        self.items.clear()
        for element, flags in elements:
            item = self.items.add()
            item.a = int(element.a)
            item.b = int(element.b)
            item.reverse = bool(flags[0])
            item.mirror = bool(flags[1])
        self.active_index = max(0, min(self.active_index, len(self.items) - 1))
        self.gene = self.current_gene()
        self.dirty = True
        _remember_gene(self)
        # Any gene edit changes the point count, so an over-budget question is no longer
        # about this gene.  These edits are not RNA ``update`` callbacks, which is why
        # ``_mark_dirty`` cannot do it for us.
        self.pending_generate = ""

    def apply_gene(self, gene: str) -> None:
        """按基因字符串写入（预设 / 导入 / 回读都走这里）。"""
        domain, elements = parse_gene(gene)
        self.set_elements(elements, domain=domain)

    def current_gene(self) -> str:
        """当前基因的字符串形式。"""
        return format_gene(self.domain, self.elements())

    def family_name(self) -> str:
        """家族名，形如 ``G(2, 0)``。"""
        return gene_family(self.domain, self.elements())

    def preset_name(self) -> str:
        """Preset name if the gene is still that exact preset, else ``""``.

        Used in the generated object's name: an untouched preset stays recognisable
        (``… G(1, 1) Dragon Curve``), an edited gene falls back to the family only.
        """
        item = GENES_BY_NAME.get(str(self.preset))
        if item and item["gene"] == self.current_gene():
            return item["name"]
        return ""

    def is_valid(self) -> bool:
        """能否展开（至少两段、总向量不为零）。"""
        elements = self.elements()
        if len(elements) < 2:
            return False
        total = total_vector(elements)
        return total.norm != 0 and not any(element.norm == 0 for element, _f in elements)

    def contraction(self) -> float:
        """自相似比 ``max(|e_i|) / |总向量|``（含义见 :attr:`lattice.FractalGenerator.contraction`）。"""
        elements = self.elements()
        if not elements:
            return 0.0
        try:
            return FractalGenerator(elements).contraction
        except ValueError:
            return 0.0

    def contraction_note(self):
        """Self-similarity ratio as a short **translated** sentence (panel and HUD).

        Translated here rather than in :mod:`hud_layout` so panel and HUD share one
        wording; the HUD layer only picks which line to show.
        """
        ratio = self.contraction()
        if ratio <= 0.0:
            return ""
        if ratio > 1.0001:
            return tfmt("Diverging: {ratio:.2f}× larger every level", ratio=ratio)
        if ratio > 0.9999:
            return t("Non-contracting: the extent grows with the level")
        if ratio > 0.75:
            return tfmt("Contraction {ratio:.2f} (weak, grows at high levels)", ratio=ratio)
        return tfmt("Contraction {ratio:.2f}", ratio=ratio)

    def initiator(self):
        """初始折线 ``(点列, 是否闭合)``；点列为 ``None`` = 从原点到总向量的直线。

        来源分两种（见 :attr:`initiator_custom`）：

        * **勾了「自定义曲线」**：读 :attr:`initiator_curve` 的第 1 条样条；
        * 否则按 :attr:`initiator_shape`：``LINE`` 是直线（返回 ``None``，交给
          :func:`lattice.teragon` 现算），正多边形按总向量现算（边长 = ``|总向量|``），
          不用建任何数据块。

        生成（:mod:`build`）与视口预览（:mod:`preview`）都走这一个入口，两条路永远同形。
        """
        if self.initiator_custom:
            return _curve_points(self.initiator_curve, bool(self.initiator_reverse))
        sides = INITIATOR_SIDES.get(str(self.initiator_shape))
        if sides:
            total = total_vector(self.elements())
            if total.norm == 0:  # 总向量为零：分形无从展开，退回直线（面板会另有报错）
                return None, False
            return polygon_initiator(sides, total, bool(self.initiator_reverse)), True
        if self.initiator_reverse:
            # Straight line read backwards: the curve grows from the total vector back to
            # the origin, i.e. the same shape turned half a turn.  Returning the explicit
            # two points is what makes the flag actually do something here — passing ``None``
            # would let :func:`lattice.teragon` build the line itself, ignoring the flag.
            total = total_vector(self.elements())
            if total.norm == 0:
                return None, False
            return [tuple(total.coord), (0.0, 0.0)], False
        return None, False

    def initiator_segments(self) -> int:
        """初始折线有几段（估点数用；直线 = 1）。"""
        if self.initiator_custom:
            count, closed = _curve_shape(self.initiator_curve)
            if count < 2:
                return 1
            return max(1, count - 1 + int(closed))
        return max(1, int(INITIATOR_SIDES.get(str(self.initiator_shape), 1)))

    def level_range(self):
        """``(low, high)`` levels written to the object.

        Without :attr:`use_range` the output is just :attr:`level` — the default is to
        generate exactly the level you are looking at.
        """
        if not self.use_range:
            level = max(LEVEL_MIN, min(int(self.level), LEVEL_MAX))
            return level, level
        low = max(LEVEL_MIN, min(int(self.level_from), LEVEL_MAX))
        high = max(LEVEL_MIN, min(int(self.level_to), LEVEL_MAX))
        return (low, high) if low <= high else (high, low)

    def shape_key_level(self):
        """Top level a shape-key object carries.

        Shape keys always run from level 1, and each level is a full copy of the curve, so
        the cost is ``levels × points``.  :meth:`key_budget` is therefore a **total** key
        point budget, and this loop keeps ``level × points(level)`` under it — a per-key
        limit would happily allow sixteen keys of a million points each.
        """
        _low, high = self.level_range()
        level = min(high, SHAPE_KEY_MAX_LEVEL)
        segments = max(1, self.initiator_segments())
        count = max(1, len(self.items))
        limit = self.key_budget()
        while level > 1 and level * (segments * count ** level + 1) > limit:
            level -= 1
        return level

    def keys_range(self):
        """``(low, high)`` levels that become shape keys: level 1 to the capped top."""
        return LEVEL_MIN, self.shape_key_level()

    def keys_truncated(self) -> bool:
        """Whether the requested level is above what shape keys will carry."""
        return self.level_range()[1] > self.shape_key_level()

    # --- 预算（本机自适应，见 budget.py） ---------------------------------

    def key_budget(self) -> int:
        """Total key-point budget for this machine (``levels × points per key``)."""
        return budget.key_budget()

    def output_budget(self) -> int:
        """Points a single Generate may write, for the current spline type."""
        return budget.peak_points(self.spline_type)

    def preview_budget(self) -> int:
        return budget.preview_budget()

    def estimate_at(self, level: int) -> int:
        """Point count of **one** level, without expanding anything."""
        segments = max(1, self.initiator_segments())
        return segments * max(1, len(self.items)) ** max(0, int(level)) + 1

    def estimate_written(self, level=None, low=None) -> int:
        """How many points the object will actually **contain**.

        This is the number every cost is proportional to, and it is what used to be wrong:
        a level-range build writes the whole ladder (``s(1 + n + n² + … + n^high)``), which
        for a two-segment gene is twice the top level.  Pricing the *top* level and drawing
        the *whole* ladder made a range build look twice as expensive as it is, and a
        single-level build (where both are equal) about twice as cheap as the constants
        assumed.  See :data:`budget.POLY_NS`.
        """
        high = self.level_range()[1] if level is None else int(level)
        first = self.level_range()[0] if low is None else int(low)
        if first >= high:
            return self.estimate_at(high)
        count = max(1, len(self.items))
        segments = max(1, self.initiator_segments())
        # Geometric ladder from level ``first`` to ``high``; the +1 endpoint of each level
        # is folded in with the count.
        total = sum(count ** exponent for exponent in range(first, high + 1))
        return segments * total + (high - first + 1)

    def is_range_output(self) -> bool:
        """Will Generate write a ladder of levels rather than one?"""
        low, high = self.level_range()
        return low < high

    def estimate_seconds(self, level=None) -> float:
        """Predicted wait (build + evaluation) for what Generate would write."""
        level = self.level_range()[1] if level is None else int(level)
        return budget.estimate_seconds(self.estimate_written(level), self.spline_type,
                                       level_range=self.is_range_output())

    def estimate_build_seconds(self, level=None) -> float:
        """Predicted time Generate itself spends, i.e. without the depsgraph evaluation.

        Evaluation runs after the operator returns and cannot be interrupted from Python, so
        it must not make an otherwise instant click look like a long one.  The share of the
        measured total that is build-only is in :func:`budget.build_seconds`.
        """
        level = self.level_range()[1] if level is None else int(level)
        return budget.build_seconds(self.estimate_written(level), self.spline_type,
                                    level_range=self.is_range_output())

    def estimate_peak_mb(self, level=None, low=None) -> float:
        return budget.estimate_mb(self.estimate_written(level, low), self.spline_type)

    def output_level_limit(self, low=None, range_output=None) -> int:
        """Highest level Generate may write on this machine.

        The comparison is against the points the *object* will hold, not against one level:
        a level-range build writes the whole ladder, which is roughly twice the top level
        for a two-segment gene.  Checking only the top level let a range build through at
        twice the budget it was supposed to respect.
        """
        first = self.level_range()[0] if low is None else int(low)
        mode = self.is_range_output() if range_output is None else bool(range_output)
        limit = self.output_budget()
        level = LEVEL_MAX
        while level > LEVEL_MIN:
            written = (self.estimate_written(level, first) if mode
                       else self.estimate_at(level))
            if written <= limit:
                return level
            level -= 1
        return LEVEL_MIN

    def output_truncated(self) -> bool:
        """Whether the requested output level is above the point budget (panel hint)."""
        return self.level_range()[1] > self.output_level_limit()

    def output_verdict(self, keys: bool = False, level: int | None = None,
                       low: int | None = None):
        """What Generate may do with a level, as ``(state, reason, safe_level, info)``.

        ``level`` defaults to the requested top level and ``low`` to the scene's range
        start.  The operator passes both levels it is *actually about to write*, so the
        memory check prices exactly the span :class:`build.BuildJob` will create.  Pricing
        one level while writing a ladder is how a build slipped past the hard wall.
        """
        range_low, high = self.level_range()
        first = range_low if low is None else int(low)
        if keys:
            top = min(high if level is None else level, SHAPE_KEY_MAX_LEVEL)
            first = LEVEL_MIN
            allowed = self.shape_key_level()
            points = self.estimate_written(top, first)
            needed_mb = points * budget.KEY_BYTES / 1048576.0
            seconds = budget.estimate_seconds(points, "POLY", level_range=True)
        else:
            top = high if level is None else int(level)
            first = min(first, top)
            allowed = self.output_level_limit(first)
            points = self.estimate_written(top, first)
            needed_mb = budget.estimate_mb(points, self.spline_type)
            seconds = budget.estimate_seconds(points, self.spline_type,
                                              level_range=first < top)

        available = sysinfo.available_bytes()
        state, reason = budget.verdict(
            needed_mb=needed_mb, seconds=seconds, fits=top <= allowed, available=available,
        )
        info = {
            "level": top,
            "low": first,
            "allowed": allowed,
            "needed_mb": needed_mb,
            "available_mb": (available or 0) / 1048576.0,
            "seconds": seconds,
            "points": points,
        }
        if state == budget.FITS:
            return state, reason, None, info
        # Degrade to the level that fits the *budget*, not to the physical ceiling: the
        # ceiling is the line past which the machine freezes, not a sensible target.  It is
        # still returned as ``safe`` so a REFUSE notice can name the highest level that was
        # physically possible.
        safe = self._safe_level(keys, first, available)
        info["safe_mb"] = budget.estimate_mb(
            self.estimate_written(safe, first), self.spline_type) if not keys else 0.0
        return state, reason, safe, info

    def _safe_level(self, keys: bool, low: int, available) -> int:
        """Highest level that stays inside the *physical* limit, not the policy budget."""
        top = min(self.level_range()[1], SHAPE_KEY_MAX_LEVEL) if keys else self.level_range()[1]
        for level in range(top, LEVEL_MIN - 1, -1):
            if keys:
                points = self.estimate_written(level, LEVEL_MIN)
                needed_mb = points * budget.KEY_BYTES / 1048576.0
                seconds = budget.estimate_seconds(points, "POLY", level_range=True)
            else:
                points = self.estimate_written(level, low)
                needed_mb = budget.estimate_mb(points, self.spline_type)
                seconds = budget.estimate_seconds(points, self.spline_type,
                                                  level_range=low < level)
            state, _reason = budget.verdict(needed_mb=needed_mb, seconds=seconds,
                                            fits=False, available=available)
            if state != budget.REFUSE:
                return level
        return LEVEL_MIN

    def preview_level(self):
        """Top level of the preview: reduced until it fits the preview budget.

        The cap is a *point count*, not a level number, so simple genes get many more
        levels than dense ones: Dragon (2 segments) reaches level 16, a 5-segment gene
        stops around 8, a 9-segment gene around 5.  The budget itself comes from
        :mod:`budget` (a fraction of the output budget, capped at 120 000 points).
        """
        level = max(0, int(self.level))
        segments = max(1, self.initiator_segments())
        count = max(1, len(self.items))
        limit = self.preview_budget()
        while level > 0 and segments * count ** level + 1 > limit:
            level -= 1
        return level

    def preview_truncated(self) -> bool:
        """Whether the preview had to stop below the requested level (panel hint)."""
        return int(self.level) > self.preview_level()

    def geometry_signature(self):
        """预览缓存键：基因 / 域 / 等级 / 初始形状与曲线一变就换一份。"""
        elements = tuple((item.a, item.b, bool(item.reverse), bool(item.mirror)) for item in self.items)
        initiator = self.initiator_curve
        initiator_key = initiator.name if initiator else ""
        # Sample the custom initiator's points: renaming it is not the only way it changes
        # (editing the curve must refresh the preview too).  Read a handful, not the whole
        # spline — this runs on every redraw.
        if self.initiator_custom:
            count, closed = _curve_shape(initiator)
            sample = _curve_sample(initiator)
            initiator_geometry = (count, bool(closed), sample) if count >= 2 else (0, False)
        elif self.initiator_shape in INITIATOR_SIDES:
            initiator_geometry = (int(INITIATOR_SIDES[str(self.initiator_shape)]), True)
        else:
            initiator_geometry = (1, False)
        return (
            self.domain,
            elements,
            self.preview_level(),
            bool(self.initiator_custom),
            str(self.initiator_shape),
            initiator_key,
            bool(self.initiator_reverse),
            initiator_geometry,
        )

    # --- 基因编辑（HUD 与面板按钮共用） -----------------------------------

    def add_item(self, a: int = 1, b: int = 0) -> None:
        """末尾追加一段。"""
        item = self.items.add()
        item.a = int(a)
        item.b = int(b)
        self.active_index = len(self.items) - 1
        self._finish_edit()

    def remove_item(self, index: int = -1) -> None:
        """删掉一段（少于两段就不删：分形至少要两段）。"""
        count = len(self.items)
        if count <= 2:
            return
        if index < 0:
            index = count - 1
        self.items.remove(min(index, count - 1))
        self.active_index = max(0, min(self.active_index, len(self.items) - 1))
        self._finish_edit()

    def move_node(self, index: int, a: int, b: int) -> bool:
        """把第 ``index`` 个节点挪到格点 ``(a, b)``（整数格点），返回是否真的动了。

        节点是相邻两段的公共端点，所以一次改两段；挪出零长度段时撤回（HUD 上表现为
        "拖不过去"）。末节点没有下一段，总向量因此可以自由变化。
        """
        from .lattice import moved_node

        moved = moved_node(self.elements(), int(index), (int(a), int(b)))
        if moved is None:
            return False
        for item, (element, flags) in zip(self.items, moved):
            item.a = element.a
            item.b = element.b
            item.reverse = bool(flags[0])
            item.mirror = bool(flags[1])
        self._finish_edit()
        return True

    def toggle_flag(self, index: int, flag: str) -> None:
        """切某一端的 ``reverse`` / ``mirror``。"""
        if not 0 <= index < len(self.items):
            return
        item = self.items[index]
        if flag == "reverse":
            item.reverse = not item.reverse
        else:
            item.mirror = not item.mirror
        self._finish_edit()

    def _finish_edit(self) -> None:
        """一次编辑结束：更新基因字符串、标脏、请求重绘。"""
        self.gene = self.current_gene()
        self.dirty = True
        _remember_gene(self)
        self.pending_generate = ""
        from . import hud

        hud.tag_redraw()


def register():
    bpy.types.Scene.fractalfamily = bpy.props.PointerProperty(type=GenFractalFamilySettings)
    install_undo_guard()


def unregister():
    remove_undo_guard()
    del bpy.types.Scene.fractalfamily


# ---------------------------------------------------------------------------
# 撤销不该吃掉基因
# ---------------------------------------------------------------------------
#
# Undo restores a *snapshot of the scene*, and the gene is only in the snapshot if an
# operator put it there.  Several paths write it outside any operator -- the startup timer
# below, property callbacks (a preset picked in the dropdown), and any ``.blend`` saved with
# a gene already in it.  So on a fresh file the undo step behind the first Generate was
# taken with an **empty** gene list, and Ctrl+Z after generating restores "no gene": the
# curve disappears as asked, but so does the input, and the panel reports "Invalid gene".
#
# A Python module variable is the one place undo cannot reach: it is not RNA, so it is not
# in the snapshot.  The gene is read from the scene in ``undo_pre`` -- before the snapshot
# replaces it -- kept here, and put back by ``undo_post`` if it came back empty.  Only the
# empty case is touched: undoing an *edit* has to keep restoring the previous gene, or
# Ctrl+Z would do nothing to the gene at all.
#
#: ``(domain, elements)`` of the last valid gene, or ``None``.
_LAST_GENE = None


def _remember_gene(settings) -> None:
    """Cache the current gene, if it is one that can be expanded."""
    global _LAST_GENE
    elements = settings.elements()
    if len(elements) < 2 or any(element.norm == 0 for element, _flags in elements):
        return
    if total_vector(elements).norm == 0:
        return
    _LAST_GENE = (settings.domain, elements)


@bpy.app.handlers.persistent
def remember_gene_before_undo(scene=None, *_args):
    """Capture the gene *before* the snapshot is loaded.

    Reading it here rather than at write time is the whole trick: a gene can reach the
    scene without any Python write we could hook -- a ``.blend`` saved with one, the
    startup file, a file opened after the add-on was already enabled.  ``undo_pre`` fires
    while that scene is still intact, so the cache is populated no matter how the gene got
    there.
    """
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    settings = getattr(scene, "fractalfamily", None) if scene is not None else None
    if settings is None:
        return
    _remember_gene(settings)


@bpy.app.handlers.persistent
def restore_gene_after_undo(scene=None, *_args):
    """Put the cached gene back when undo wiped the list (see the note above).

    Registered on ``undo_post``: it runs after the snapshot is loaded, so writing here
    lands in the restored scene rather than being overwritten by the load itself.
    Deliberately narrow -- it acts **only** when the list came back empty, so undoing a
    segment edit still steps back through the gene history as the user expects.

    ``persistent`` because Blender drops handlers when it loads a file: without it the
    guard would work once, then quietly disappear on the first ``File > Open``.
    """
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    settings = getattr(scene, "fractalfamily", None) if scene is not None else None
    if settings is None or settings.items or _LAST_GENE is None:
        return
    domain, elements = _LAST_GENE
    settings.set_elements(elements, domain=domain)


@bpy.app.handlers.persistent
def forget_cached_gene(*_args):
    """Drop the cache when another file is opened.

    The cache lives in the module, so it would otherwise survive ``File > Open`` and a
    brand-new file -- whose own gene list is empty -- would be handed the previous file's
    gene on the first undo.  That is not a restore, it is a leak.
    """
    global _LAST_GENE
    _LAST_GENE = None


#: Defaults for the fields that describe one click, not the file.  ``SKIP_SAVE`` keeps them
#: out of new saves; this table also repairs files written by older versions, where the
#: values are still inside the .blend and would otherwise come back as a frozen progress
#: bar (no modal left to clear it) or a question nobody is answering any more.
_TRANSIENT_DEFAULTS = {
    "running_fraction": -1.0,
    "running_level": 0,
    "running_high": 0,
    "running_points": 0,
    "running_build_s": 0.0,
    "running_eval_s": 0.0,
    "running_eval_start": 0.0,
    "notice_kind": "",
    "notice_requested": 0,
    "notice_actual": 0,
    "error": "",
    "pending_generate": "",
}


@bpy.app.handlers.persistent
def reset_transient_state(*_args):
    """Drop click-scoped state after ``File > Open``."""
    scene = getattr(bpy.context, "scene", None)
    settings = getattr(scene, "fractalfamily", None) if scene is not None else None
    if settings is None:
        return
    for name, default in _TRANSIENT_DEFAULTS.items():
        if getattr(settings, name, default) != default:
            setattr(settings, name, default)


def install_undo_guard() -> None:
    """Attach the undo handlers (idempotent across a hot reload)."""
    for handlers, function in (
        (bpy.app.handlers.undo_pre, remember_gene_before_undo),
        (bpy.app.handlers.undo_post, restore_gene_after_undo),
        (bpy.app.handlers.load_post, forget_cached_gene),
        (bpy.app.handlers.load_post, reset_transient_state),
    ):
        while function in handlers:
            handlers.remove(function)
        handlers.append(function)


def remove_undo_guard() -> None:
    for handlers, function in ((bpy.app.handlers.undo_pre, remember_gene_before_undo),
                               (bpy.app.handlers.undo_post, restore_gene_after_undo),
                               (bpy.app.handlers.load_post, forget_cached_gene),
                               (bpy.app.handlers.load_post, reset_transient_state)):
        while function in handlers:
            handlers.remove(function)


# ---------------------------------------------------------------------------
# 首次启用：给一条能看的基因
# ---------------------------------------------------------------------------

#: 计时器键（热重载后还能摘掉上一次挂的）。
_BOOTSTRAP_KEY = "fractalfamily_bootstrap_timer"


def bootstrap_default_gene(*_args):
    """基因列表为空时填第一条预设（龙形曲线）。

    用 timer 而不是在 ``register()`` 里直接写：注册那一刻不一定有可用的 scene context，
    而参数组是通过 ``Scene`` 上的指针挂上去的。返回值 ``None`` = 一次性 timer。

    这里**不做**速度标定：测出来的斜率一开机偏高约 25 %（冷页表、分配器与 numpy 都还没
    热身），而这个数字会决定此后整个会话的每一个估算。标定改到第一次点击生成时做，那
    时进程已经跑过导入和场景装配（见 :func:`ops.FRACTALFAMILY_OT_generate._prepare`）。
    """
    try:
        scene = bpy.context.scene
    except AttributeError:  # 还没有窗口 / 场景
        return 0.2
    settings = getattr(scene, "fractalfamily", None)
    if settings is None:
        return 0.2
    if settings.items:
        return None
    item = DEFAULT_GENES[0] if DEFAULT_GENES else {"name": "", "gene": "G 1 0 0 0 0 1 1 0"}
    if item["name"]:
        settings.preset = item["name"]
    settings.apply_gene(item["gene"])
    return None


def install_bootstrap() -> None:
    """Attach the first-enable gene timer."""
    remove_bootstrap()
    bpy.app.timers.register(bootstrap_default_gene, first_interval=0.1)
    bpy.app.driver_namespace[_BOOTSTRAP_KEY] = bootstrap_default_gene


def remove_bootstrap() -> None:
    """Detach the timer (must run from ``unregister``)."""
    for func in (bpy.app.driver_namespace.pop(_BOOTSTRAP_KEY, None), bootstrap_default_gene):
        if func is None:
            continue
        try:
            if bpy.app.timers.is_registered(func):
                bpy.app.timers.unregister(func)
        except (TypeError, RuntimeError, ValueError):
            pass
