import itertools
import math

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from .default_presets import default_curvedefs
from .subdivide import subdivide_curve

# ==============================================================================
# Fractal Math & Logic
# ==============================================================================

SQRT_3_OVER_2 = 0.8660254037844386


class ComplexInteger:
    """Represents a complex integer in either G (Gaussian) or E (Eisenstein) domain."""

    def __init__(self, a: int = 0, b: int = 0, domain: str = "G"):
        """
        Initialize the complex integer.

        Args:
            a (int): The real part or first component.
            b (int): The imaginary part or second component.
            domain (str): The domain type, "G" for Gaussian or "E" for Eisenstein.
        """
        self.a = a
        self.b = b
        self.domain = domain

    def __add__(self, other: "ComplexInteger"):
        """
        Add two complex integers.

        Args:
            other (ComplexInteger): The other complex integer to add.

        Returns:
            ComplexInteger: The sum of the two complex integers.
        """
        return ComplexInteger(self.a + other.a, self.b + other.b, self.domain)

    def __repr__(self):
        """Return a string representation of the complex integer."""
        return f"{self.domain}{self.a, self.b}"

    @property
    def coord(self):
        """
        Convert to coordinate vector based on domain.

        Returns:
            Vector: A 3D vector representing the complex integer's coordinates.
        """
        if self.domain == "G":
            return Vector((self.a, self.b, 0))

        return Vector((self.a - self.b / 2, self.b * SQRT_3_OVER_2, 0))

    @property
    def norm(self):
        """
        Calculate the norm based on domain.

        Returns:
            int: The squared norm of the complex integer.
        """
        if self.domain == "G":
            return self.a * self.a + self.b * self.b
        return self.a * self.a - self.a * self.b + self.b * self.b

    def to_tuple(self):
        """
        Convert to a tuple.

        Returns:
            tuple: A tuple (a, b).
        """
        return self.a, self.b


def calculate_transform_matrix(points: list[Vector]):
    """
    Calculate the transformation matrix to align segment src_start -> src_end to tgt_start -> tgt_end.
    Forces calculation on the XY plane (rotation around Z axis).

    Args:
        points (list[Vector]): A list of 4 vectors [src_start, src_end, tgt_start, tgt_end].

    Returns:
        Matrix: The 4x4 transformation matrix.
    """
    src_start, src_end, tgt_start, tgt_end = points

    src_vec = src_end - src_start
    tgt_vec = tgt_end - tgt_start

    src_len = src_vec.length
    tgt_len = tgt_vec.length
    scale_factor = tgt_len / src_len
    scale_mat = Matrix.Scale(scale_factor, 4)

    # Use atan2 to calculate signed angle to avoid uncertainty of rotation_difference at 180 degrees
    angle_src = math.atan2(src_vec.y, src_vec.x)
    angle_tgt = math.atan2(tgt_vec.y, tgt_vec.x)
    angle_diff = angle_tgt - angle_src

    rot_mat = Matrix.Rotation(angle_diff, 4, "Z")

    # Composite matrix calculation: translate to origin -> scale -> rotate -> translate to target start
    mat_to_origin = Matrix.Translation(-src_start)
    mat_to_target = Matrix.Translation(tgt_start)

    # Matrix multiplication order: execute from right to left
    return mat_to_target @ rot_mat @ scale_mat @ mat_to_origin


def parse_gene(gene: str):
    """
    Parse a gene string into list of (ComplexInt, transform) pairs.

    Args:
        gene (str): The gene string to parse.

    Returns:
        list[tuple[ComplexInteger, tuple[int, int]]]: A list of parsed elements.
    """
    # Split domain and numbers
    parts = gene.split()

    domain, *number_strings = parts
    assert len(number_strings) % 4 == 0, "Gene must have multiple of 4 numbers"

    # Convert to integers
    numbers = [int(n) for n in number_strings]

    # Process in groups of 4 and create pairs
    elements: list[tuple[ComplexInteger, tuple[int, int]]] = []
    for a, b, t1, t2 in zip(numbers[::4], numbers[1::4], numbers[2::4], numbers[3::4]):
        integer = ComplexInteger(a, b, domain)
        transform = (bool(t1), bool(t2))
        elements.append((integer, transform))

    return elements


class FractalGenerator:
    """Manages fractal generator elements and their transformations."""

    def __init__(self, source: str | list[tuple[ComplexInteger, tuple[int, int]]]):
        """
        Initialize the FractalGenerator.

        Args:
            source (str | list): A gene string or a list of elements.
        """
        if isinstance(source, str):
            self.elements = parse_gene(source)
        else:
            self.elements = source

        self.domain = self.elements[0][0].domain if self.elements else "G"
        self.integer = sum((elem[0] for elem in self.elements), ComplexInteger(domain=self.domain))
        self.max_level = 1

        if self.integer.norm != 0:
            self._init_level_points()
            self._init_matrices()

    @property
    def is_valid(self):
        """Check if the generator is valid (i.e., not a point)."""
        return self.integer.norm != 0 and len(self.elements) >= 2

    def _init_level_points(self):
        """Initialize the first two levels of points (Level 0 and Level 1)."""
        self.level_points = [
            [self.integer.coord],  # Level 0
            [i.coord for i in itertools.accumulate(elem[0] for elem in self.elements)],  # Level 1
        ]

    def _init_matrices(self):
        """Initialize transformation matrices list."""
        # Get all points from level 1
        points = self.level_points[1]
        # Base unit start and end points
        base_start = Vector()  # Origin
        base_end = self.integer.coord  # Total vector

        # Calculate transformation matrix for each generator element
        self.matrices: list[Matrix] = []
        for i, (point, elem) in enumerate(zip(points, self.elements)):
            # Current segment start and end points
            seg_start = Vector() if i == 0 else points[i - 1]
            seg_end = point

            # Determine mapping direction based on transform flag
            src_points = [base_start, base_end]
            tgt_points = [seg_start, seg_end]
            should_reverse = elem[1][0]
            if should_reverse:
                tgt_points = tgt_points[::-1]

            # Calculate and store transformation matrix
            matrix = calculate_transform_matrix(src_points + tgt_points)
            self.matrices.append(matrix)

    def update_level_points(self, level: int):
        """
        Update fractal point coordinates to specified level.

        Args:
            level (int): The target level to generate points for.
        """
        if level <= self.max_level:
            return

        for i in range(self.max_level + 1, level + 1):
            new_points = []  # for convenience the origin point (0, 0) is ignored
            for elem, matrix in zip(self.elements, self.matrices):
                points = self.level_points[i - 1]
                if elem[1][0]:
                    points = reversed([Vector()] + points[:-1])
                if elem[1][1]:
                    reflection_dir = self.integer.coord
                    points = [-p.reflect(reflection_dir) for p in points]

                # Apply transformation matrix and add to new points list
                new_points.extend(matrix @ point for point in points)

            self.level_points.append(new_points)

        self.max_level = level

    def __repr__(self):
        """Return a string representation of the FractalGenerator."""
        lines = [str(self.integer)]
        for elem in self.elements:
            lines.append(f"{str(elem[0]):<9} {int(elem[1][0]), int(elem[1][1])}")
        return "\n".join(lines) + "\n"


def get_initiator_matrices(points: list[Vector], generator: FractalGenerator, is_closed=False):
    """
    Calculate transformation matrices when an initiator is given.

    Args:
        points (list[Vector]): The points of the initiator curve.
        generator (FractalGenerator): The fractal generator instance.
        is_closed (bool): Whether the initiator curve is closed.

    Returns:
        list[Matrix]: A list of transformation matrices.
    """
    matrices: list[Matrix] = []

    points = [p.copy() for p in points]

    # Add start point as end point for closed splines
    if is_closed:
        points.append(points[0])

    # Calculate transformation matrix for each segment
    for i in range(1, len(points)):
        # Current segment start and end points
        seg_start = points[i - 1]
        seg_end = points[i]

        # Calculate transformation matrix mapping basic unit to current segment
        # fmt: off
        matrix = calculate_transform_matrix(
            [
                Vector(),                 # Source start
                generator.integer.coord,  # Source end
                seg_start,                # Target start
                seg_end,                  # Target end
            ]
        )
        # fmt: on
        matrices.append(matrix)

    return matrices


# ==============================================================================
# Blender Property Groups & UI
# ==============================================================================

active_generator: FractalGenerator | None = None


def on_active_curve_def_change(self, context):
    """
    Callback when the active curve definition changes.
    Updates the active generator based on the selected curve definition.

    Args:
        self: The property group instance.
        context: The Blender context.
    """
    global active_generator
    fractalfamily_props = context.window_manager.fractalfamily_props
    if fractalfamily_props.is_suppress_updates:
        return
    active_curve_def = fractalfamily_props.active_curve_def
    elements = []
    domain = active_curve_def.domain
    for item in active_curve_def.items:
        complex_integer = ComplexInteger(item.complex_integer[0], item.complex_integer[1], domain)
        transform_flags = item.transform_flags[0], item.transform_flags[1]
        elements.append((complex_integer, transform_flags))
    active_generator = FractalGenerator(elements)
    # print(active_generator)

    if active_generator.is_valid:
        active_generator.update_level_points(2)
        for i, points in enumerate(active_generator.level_points[:3]):
            name = f"__fractalfamily_preview_level_{i}__"
            try:
                curve = bpy.data.curves.get(name)
                if curve:
                    curve.splines.clear()
                    spline = curve.splines.new(type="POLY")
                    spline.use_cyclic_u = False
                    spline.points.add(count=len(points))
                    for j, point in enumerate(points):
                        spline.points[j + 1].co = *point, 1.0
            except AttributeError:
                pass


class GeneratorItem(bpy.types.PropertyGroup):
    """A single fractal generator item."""

    complex_integer: bpy.props.IntVectorProperty(
        name="Complex Integer",
        size=2,
        default=(0, 1),
        description="Complex integer on G or E domain.",
        update=on_active_curve_def_change,
    )
    transform_flags: bpy.props.BoolVectorProperty(
        name="Transform Flags",
        size=2,
        default=(False, False),
        description="Reverse flag, Mirror flag",
        update=on_active_curve_def_change,
    )


class GeneratorDefinition(bpy.types.PropertyGroup):
    """A curve definition, containing a list of generator items."""

    name: bpy.props.StringProperty(name="Name")
    domain: bpy.props.EnumProperty(
        name="Domain",
        items=[
            ("G", "Gaussian", "Gaussian domain"),
            ("E", "Eisenstein", "Eisenstein domain"),
        ],
        default="G",
        update=on_active_curve_def_change,
    )
    items: bpy.props.CollectionProperty(type=GeneratorItem)


class InitiatorCurveProp(bpy.types.PropertyGroup):
    """Property group for initiator curve settings."""

    curve: bpy.props.PointerProperty(
        type=bpy.types.Curve,
        name="Initiator Curve",
        description="Keep empty to use the segment from origin to the last accumulated coordinate.",
    )
    reverse: bpy.props.BoolProperty(
        name="Reverse",
        default=False,
        description="Use the reversed sequence of the initiator curve points.",
    )


def get_preset_items(self, context):
    """
    Callback to populate the enum items for selected_preset_name.

    Args:
        self: The property group instance.
        context: The Blender context.

    Returns:
        list[tuple]: A list of tuples (identifier, name, description) for the enum.
    """
    items = []
    for item in self.presets:
        items.append((item.name, item.name, ""))
    return items


def on_preset_name_changed(self, context):
    """
    Callback when the active preset name changes.
    Updates the curve definition items based on the selected preset.

    Args:
        self: The property group instance.
        context: The Blender context.
    """
    global active_generator
    name = self.selected_preset_name

    preset = self.presets.get(name)

    if not preset:
        return

    # Access the active curve definition
    active_curve_def = self.active_curve_def
    active_generator = FractalGenerator(preset.gene)
    self.items_active_index = -1

    # Suppress updates during batch modification
    self.is_suppress_updates = True
    try:
        # Update active_curve_def directly from preset_data
        active_curve_def.name = name
        active_curve_def.domain = active_generator.domain

        active_curve_def.items.clear()
        for element in active_generator.elements:
            item = active_curve_def.items.add()
            item.complex_integer = element[0].to_tuple()
            item.transform_flags = element[1]
    finally:
        self.is_suppress_updates = False

    # Manually trigger update once
    on_active_curve_def_change(self, context)


class PresetItem(bpy.types.PropertyGroup):
    """Property group for a preset name item."""

    name: bpy.props.StringProperty()
    gene: bpy.props.StringProperty()


def on_show_preview_changed(self, context):
    """
    Callback when the show_preview property changes.
    Updates the preview of the fractal curves.

    Args:
        self: The property group instance.
        context: The Blender context.
    """
    name = "__fractalfamily_preview__"
    collection = bpy.data.collections.get(name)
    if self.show_preview:
        collection = bpy.data.collections.get(name)
        if not collection:
            collection = bpy.data.collections.new(name)
            bpy.context.scene.collection.children.link(collection)
        collection.hide_viewport = False
        for i in range(3):
            level_name = f"__fractalfamily_preview_level_{i}__"
            curve = bpy.data.curves.get(level_name)
            obj = bpy.data.objects.get(level_name)
            if not curve:
                curve = bpy.data.curves.new(name=level_name, type="CURVE")
            if not obj:
                obj = bpy.data.objects.new(level_name, curve)
                collection.objects.link(obj)
            if i == 0:
                obj.hide_set(True)
            if i == 2:
                obj.select_set(True)
            if i == 0 or i == 1:
                obj.select_set(False)
        on_active_curve_def_change(self, context)
    else:
        if collection:
            collection.hide_viewport = True


class FractalFamilyProps(bpy.types.PropertyGroup):
    """Global property group for the Fractal Family add-on."""

    is_suppress_updates: bpy.props.BoolProperty(default=False)
    presets: bpy.props.CollectionProperty(type=PresetItem)
    selected_preset_name: bpy.props.EnumProperty(
        name="Preset",
        description="Select a preset to edit or create fractal curves",
        items=get_preset_items,
        update=on_preset_name_changed,
    )
    active_curve_def: bpy.props.PointerProperty(type=GeneratorDefinition)

    # Keep the active index for the UI list tracking
    items_active_index: bpy.props.IntProperty(default=-1)

    spline_type: bpy.props.EnumProperty(
        name="Spline Type",
        description="Spline type of the generated fractal curves",
        items=[("POLY", "Poly", ""), ("SMOOTH", "Smooth", "")],
        default="POLY",
    )

    level: bpy.props.IntProperty(
        name="Level of fractal curves",
        description="The level of fractal curves, from 1 to 20",
        default=4,
        min=1,
        max=20,
    )

    initiator_curve: bpy.props.PointerProperty(type=InitiatorCurveProp)

    show_preview: bpy.props.BoolProperty(
        name="Show Preview",
        default=False,
        update=on_show_preview_changed,
        description="Show preview of the fractal curves",
    )
    active_curve: bpy.props.PointerProperty(type=bpy.types.Curve)


class CurrentFractalGeneratorItemList(bpy.types.UIList):
    """UI List for displaying and editing generator items."""

    bl_idname = "FRACTALFAMILY_UL_CurrentFractalGeneratorItemList"

    def draw_filter(self, context, layout):
        """Disable the filter UI for this list."""
        pass

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index, flt_flag):
        """Draw a single item in the list."""
        reverse_flag, mirror_flag = item.transform_flags

        col = layout.column()
        row = col.row(align=True)
        row.label(text=f"# {index + 1:2d}")
        row.prop(item, "complex_integer", index=0, text="")
        row.prop(item, "complex_integer", index=1, text="")

        row.separator()
        icon_reverse = "UV_SYNC_SELECT" if reverse_flag else "PROP_OFF"
        row.prop(item, "transform_flags", index=0, text="", icon=icon_reverse, emboss=False)

        icon_mirror = "MOD_MIRROR" if mirror_flag else "PROP_OFF"
        row.prop(item, "transform_flags", index=1, text="", icon=icon_mirror, emboss=False)


class FRACTALFAMILY_OT_list_add(bpy.types.Operator):
    """Add a new item to the list"""

    bl_idname = "fractalfamily.list_add"
    bl_label = "Add Item"

    def execute(self, context):
        props = context.window_manager.fractalfamily_props
        items = props.active_curve_def.items
        items.add()
        props.items_active_index = len(items) - 1
        on_active_curve_def_change(self, context)
        return {"FINISHED"}


class FRACTALFAMILY_OT_list_remove(bpy.types.Operator):
    """Remove the selected item from the list"""

    bl_idname = "fractalfamily.list_remove"
    bl_label = "Remove Item"

    @classmethod
    def poll(cls, context):
        props = context.window_manager.fractalfamily_props
        return props.active_curve_def.items and props.items_active_index >= 0

    def execute(self, context):
        props = context.window_manager.fractalfamily_props
        items = props.active_curve_def.items
        index = props.items_active_index
        items.remove(index)
        if index >= len(items):
            props.items_active_index = max(0, len(items) - 1)
        on_active_curve_def_change(self, context)
        return {"FINISHED"}


class FRACTALFAMILY_OT_list_move(bpy.types.Operator):
    """Move the selected item up or down"""

    bl_idname = "fractalfamily.list_move"
    bl_label = "Move Item"

    direction: bpy.props.EnumProperty(items=(("UP", "Up", ""), ("DOWN", "Down", "")))

    @classmethod
    def poll(cls, context):
        props = context.window_manager.fractalfamily_props
        return props.active_curve_def.items and props.items_active_index >= 0

    def execute(self, context):
        props = context.window_manager.fractalfamily_props
        items = props.active_curve_def.items
        index = props.items_active_index

        neighbor = index + (-1 if self.direction == "UP" else 1)
        if 0 <= neighbor < len(items):
            items.move(index, neighbor)
            props.items_active_index = neighbor
            on_active_curve_def_change(self, context)

        return {"FINISHED"}


class MainPanel(bpy.types.Panel):
    """Main panel for the Fractal Family add-on."""

    bl_idname = "FRACTALFAMILY_PT_main"
    bl_label = "Fractal Family"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Edit"

    def draw(self, context):
        """Draw the panel UI."""
        assert self.layout is not None
        fractalfamily_props = context.window_manager.fractalfamily_props
        active_curve_def = fractalfamily_props.active_curve_def

        row = self.layout.row()
        row.prop(fractalfamily_props, "selected_preset_name")
        box = self.layout.box()
        row = box.row(align=True)
        row.label(text="Domain:")
        row.prop_enum(active_curve_def, "domain", "G")
        row.prop_enum(active_curve_def, "domain", "E")
        row = box.row()
        row.label(text="Generator Items:")
        row.prop(fractalfamily_props, "show_preview", toggle=True)
        row = box.row()
        row.template_list(
            "FRACTALFAMILY_UL_CurrentFractalGeneratorItemList",
            "FRACTALFAMILY_GENERATOR_ITEM_LIST",
            fractalfamily_props.active_curve_def,
            "items",
            fractalfamily_props,
            "items_active_index",
        )

        col = row.column(align=True)
        col.operator("fractalfamily.list_add", icon="ADD", text="")
        col.operator("fractalfamily.list_remove", icon="REMOVE", text="")
        col.separator()
        col.operator("fractalfamily.list_move", icon="TRIA_UP", text="").direction = "UP"
        col.operator("fractalfamily.list_move", icon="TRIA_DOWN", text="").direction = "DOWN"

        if not active_generator:
            return
        if len(active_generator.elements) < 2:
            self.layout.label(text="At least two generator items are required.", icon="ERROR")
        elif active_generator.integer.norm == 0:
            self.layout.label(text="Generator integer norm must not be zero.", icon="ERROR")
        else:
            box = self.layout.box()
            row = box.row()
            row.prop(fractalfamily_props, "level", text="")
            split = row.split(factor=0.5, align=True)
            split.prop_enum(fractalfamily_props, "spline_type", "POLY")
            split.prop_enum(fractalfamily_props, "spline_type", "SMOOTH")
            row = box.row()
            row.prop(fractalfamily_props.initiator_curve, "curve", text="", placeholder="Initiator Curve")
            row.prop(fractalfamily_props.initiator_curve, "reverse", text="", icon="ARROW_LEFTRIGHT")
            row = box.row(align=True)
            row.operator(
                "object.fractalfamily_create_teragon_curves",
                text="Create Each Level",
            ).mode = "EACH_LEVEL"
            row.operator(
                "object.fractalfamily_create_teragon_curves",
                text="Create Last Level",
            ).mode = "LAST_LEVEL"
            row = box.row()
            row.operator(
                "object.fractalfamily_create_teragon_curves",
                text="Create Curve with Shape Keys",
                icon="SHADERFX",
            ).mode = "SHAPE_KEYS"
            if fractalfamily_props.active_curve and fractalfamily_props.active_curve.shape_keys:
                row = box.row()
                row.prop(fractalfamily_props.active_curve.shape_keys, "eval_time", text="Evaluation Time")


@persistent
def load_default_presets(dummy=None):
    """Load default curve presets into the property group."""
    # print("try load default presets")
    try:
        wm = bpy.context.window_manager
    except AttributeError:
        wm = None

    if wm is None and bpy.data.window_managers:
        wm = bpy.data.window_managers[0]

    if wm is None or not hasattr(wm, "fractalfamily_props"):
        return 0.1

    presets = wm.fractalfamily_props.presets
    presets.clear()

    first_name = None
    for info in default_curvedefs:
        name = f"{info['family']} {info['name']}"
        new_item = presets.add()
        new_item.name = name
        new_item.gene = info["gene"]
        if first_name is None:
            first_name = name

    if first_name:
        if not wm.fractalfamily_props.selected_preset_name:
            wm.fractalfamily_props.selected_preset_name = first_name

        on_preset_name_changed(wm.fractalfamily_props, bpy.context)
    return None


def create_curve_poly(points: list[Vector], name: str = "Curve", num_segments: int = 1, is_closed: bool = False):
    """
    Create a poly curve from a list of points.

    Args:
        points (list[Vector]): List of points.
        name (str): Name of the curve.
        num_segments (int): Number of segments to subdivide between points (linear interpolation).
        is_closed (bool): Whether the curve is closed.

    Returns:
        bpy.types.Object: The created curve object.
    """
    new_points: list[Vector] = []

    if num_segments < 1:
        num_segments = 1

    if is_closed:
        for i in range(len(points)):
            p1 = points[i]
            p2 = points[(i + 1) % len(points)]
            for j in range(num_segments):
                t = j / num_segments
                new_points.append(p1.lerp(p2, t))
    else:
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            for j in range(num_segments):
                t = j / num_segments
                new_points.append(p1.lerp(p2, t))
        new_points.append(points[-1])

    curve = bpy.data.curves.new(name=name, type="CURVE")
    spline = curve.splines.new("BEZIER")
    bezier_points = spline.bezier_points
    bezier_points.add(len(new_points) - 1)

    points_unpacked = list(itertools.chain.from_iterable(co.to_tuple() for co in new_points))
    bezier_points.foreach_set("co", points_unpacked)

    # Set handle types to VECTOR for poly lines
    for point in bezier_points:
        point.handle_left_type = "VECTOR"
        point.handle_right_type = "VECTOR"

    spline.use_cyclic_u = is_closed
    return curve


def create_curve_smooth(points: list[Vector], name: str = "Curve", num_segments: int = 1, is_closed: bool = False):
    """
    Create a smooth curve from a list of points.

    Args:
        points (list[Vector]): List of points.
        name (str): Name of the curve.
        num_segments (int): Number of subdivisions.
        is_closed (bool): Whether the curve is closed.

    Returns:
        bpy.types.Object: The created curve object.
    """
    curve = bpy.data.curves.new(name=name, type="CURVE")
    spline = curve.splines.new("BEZIER")
    spline.use_cyclic_u = is_closed
    bezier_points = spline.bezier_points
    bezier_points.add(len(points) - 1)

    for i, point in enumerate(points):
        bezier_points[i].co = point
        bezier_points[i].handle_left_type = "AUTO"
        bezier_points[i].handle_right_type = "AUTO"

    subdivide_curve(curve, num_segments)
    return curve


class CreateTeragonCurvesOperator(bpy.types.Operator):
    """Operator to create Fractal Curves based on the current configuration."""

    bl_idname = "object.fractalfamily_create_teragon_curves"
    bl_label = "Create Teragon Curves"
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(
        name="Mode",
        description="Mode to create the Teragon Fractal Curves",
        items=[
            ("EACH_LEVEL", "Each Level", "Create Fractal Curves for each level"),
            ("LAST_LEVEL", "Last Level", "Create Fractal Curve for the last level"),
            ("SHAPE_KEYS", "Shape Keys", "Create Fractal Curve with Shape Keys"),
        ],
        default="EACH_LEVEL",
    )

    def execute(self, context):
        """Execute the operator."""
        global active_generator
        fractalfamily_props = context.window_manager.fractalfamily_props

        subdivision = len(active_generator.elements)
        is_closed = False
        level = fractalfamily_props.level
        active_generator.update_level_points(level)
        spline_type = fractalfamily_props.spline_type

        initiator_curve = fractalfamily_props.initiator_curve.curve
        initiator_points = [Vector(), active_generator.integer.coord]

        if initiator_curve:
            spline = initiator_curve.splines.active
            if spline.use_cyclic_u:
                is_closed = True
            if spline.type == "BEZIER" and len(spline.bezier_points) > 1:
                initiator_points = [p.co for p in spline.bezier_points]
            elif len(spline.points) > 1:
                initiator_points = [p.co.to_3d() for p in spline.points]

            if fractalfamily_props.initiator_curve.reverse:
                initiator_points.reverse()

        initiator_matrices = get_initiator_matrices(initiator_points, active_generator, is_closed)

        level_teragon_points = []

        for i, points in enumerate(active_generator.level_points):
            teragon_points = [initiator_points[0]]
            for matrix in initiator_matrices:
                teragon_points.extend(matrix @ point for point in points)

            if is_closed:
                teragon_points.pop()

            level_teragon_points.append(teragon_points)

        if self.mode == "EACH_LEVEL":
            for i, teragon_points in enumerate(level_teragon_points):
                num_segments = subdivision ** (level - i)
                name = "Teragon" if i == 0 else f"Teragon {i}"

                if spline_type == "POLY":
                    curve = create_curve_poly(teragon_points, name, num_segments, is_closed)
                else:
                    curve = create_curve_smooth(teragon_points, name, num_segments, is_closed)
                obj = bpy.data.objects.new(name, curve)
                bpy.context.collection.objects.link(obj)
                obj.select_set(True)

                if i == 0:
                    context.view_layer.objects.active = obj

        elif self.mode == "LAST_LEVEL":
            teragon_points = level_teragon_points[level]
            num_segments = 1
            name = "Teragon"

            if spline_type == "POLY":
                curve = create_curve_poly(teragon_points, name, num_segments, is_closed)
            else:
                curve = create_curve_smooth(teragon_points, name, num_segments, is_closed)

            obj = bpy.data.objects.new(name, curve)
            bpy.context.collection.objects.link(obj)
            obj.select_set(True)
            context.view_layer.objects.active = obj

        elif self.mode == "SHAPE_KEYS":
            curves: list[bpy.types.Curve] = []
            for i, teragon_points in enumerate(level_teragon_points):
                num_segments = subdivision ** (level - i)
                name = "Teragon" if i == 0 else f"Teragon {i}"

                if spline_type == "POLY":
                    curve = create_curve_poly(teragon_points, name, num_segments, is_closed)
                else:
                    curve = create_curve_smooth(teragon_points, name, num_segments, is_closed)
                curves.append(curve)

            obj = bpy.data.objects.new("Teragon", curves[0])
            bpy.context.collection.objects.link(obj)
            obj.select_set(True)
            context.view_layer.objects.active = obj

            for i, curve in enumerate(curves):
                key = obj.shape_key_add(name=f"Level {i}")
                if i == 0 and curve.shape_keys:
                    curve.shape_keys.use_relative = False
                    fractalfamily_props.active_curve = curve
                for j, point in enumerate(curve.splines[0].bezier_points):
                    key.data[j].co = point.co
                    key.data[j].handle_left = point.handle_left
                    key.data[j].handle_right = point.handle_right
        fractalfamily_props.show_preview = False
        return {"FINISHED"}


def register():
    """Register the add-on."""
    bpy.types.WindowManager.fractalfamily_props = bpy.props.PointerProperty(type=FractalFamilyProps)

    # Load default presets
    # Use a timer to ensure context is ready
    bpy.app.handlers.load_post.append(load_default_presets)
    bpy.app.timers.register(load_default_presets, first_interval=0.1)


def unregister():
    """Unregister the add-on."""
    if load_default_presets in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_default_presets)
    del bpy.types.WindowManager.fractalfamily_props
