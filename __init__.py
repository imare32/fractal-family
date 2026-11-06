"""Fractal Family: fractal curves from complex-integer genes, edited in a viewport HUD.

A **gene** is a sequence of complex integers plus two transform flags per segment
(reverse / mirror); it defines a substitution rule that turns a segment into a polyline.
Repeating the substitution produces the fractal. The G domain is the square lattice
(Gaussian integers), the E domain is the triangular lattice (Eisenstein integers).

Layering (math layer never imports ``bpy``)::

    lattice     -- complex integers / gene parsing / lattice snapping / level points
    hud_layout  -- HUD primitives and hit regions (pure functions)
    presets     -- built-in genes
    palette     -- colour constants and sRGB -> linear helpers

Blender layer (imported lazily from :func:`register`)::

    props       -- ``scene.fractalfamily`` settings, design read-back on objects
    preview     -- viewport preview, ``POST_VIEW`` immediate mode (no data-blocks)
    hud         -- viewport HUD, ``POST_PIXEL`` panel, fonts, session state
    curves      -- curve assembly (poly / smooth / shape-key preserving subdivision)
    build       -- generation entry point
    ops         -- generate / scene setup / copy-paste / HUD modal
    ui          -- ``View3D > Sidebar > Fractal``
"""

bl_info = {
    "name": "Fractal Family",
    "author": "imare32",
    "description": "Create fractal curves with ease using complex integer lattices.",
    "blender": (4, 2, 0),
    "version": (2, 0, 0),
    "location": "3D Viewport > Sidebar > Fractal",
    "warning": "",
    "category": "Generic",
}

#: English msgid -> zh_HANS.  ``*`` covers RNA names/descriptions, enum items and the
#: strings passed through :func:`i18n.t`; ``Operator`` covers ``bl_label``.
translation_dict = {
    "zh_HANS": {
        # --- add-on ------------------------------------------------------
        ("*", "Fractal Family"): "分形家族",
        ("*", "Create fractal curves with ease using complex integer lattices."): "使用复整数格子轻松创建分形曲线。",

        # --- panel sections ----------------------------------------------
        ("*", "Gene"): "基因",
        ("*", "Level & Initiator"): "等级与初始折线",
        ("*", "Generate"): "生成",
        ("*", "Viewport Preview"): "视口预览",
        ("*", "Status"): "状态",

        # --- panel buttons / hints ---------------------------------------
        ("*", "HUD"): "HUD",
        ("*", "How to use the HUD"): "HUD 使用说明",
        ("*", "Drag a node to move it on the lattice — it always snaps to integer points"):
            "拖动节点在点阵上移动，总是吸附到整数格点",
        ("*", "Click R / M on a segment to toggle its reverse / mirror flag"):
            "点线段上的 R / M 切换反向 / 镜像标记",
        ("*", "Wheel changes the level · Shift+wheel zooms · F fits the view"):
            "滚轮改等级 · Shift+滚轮缩放 · F 重新取景",
        ("*", "Tab or Q switches the domain · A adds a segment · X removes the last one"):
            "Tab 或 Q 切换点阵域 · A 加一段 · X 删除最后一段",
        ("*", "Drag the title bar to move the panel"): "拖标题栏可以移动面板",
        ("*", "Esc, right click or × closes the HUD"): "Esc、右键或 × 关闭 HUD",
        ("*", "Click anywhere to close this help"): "点击任意位置关闭说明",
        ("*", "Preset"): "预设",
        ("*", "Copy Gene"): "复制基因",
        ("*", "Paste Gene"): "粘贴基因",
        ("*", "Invalid gene: at least two segments and a non-zero total vector"):
            "基因无效：至少要两段、总向量不为零",

        # --- 基因说明（标题右侧的 ? 的悬停提示） ----------------------------
        ("*", "What Is a Gene?"): "什么是基因？",
        ("*", "A gene is a short list of integer segments: each one says where the "
              "next copy of the curve goes. Applied again and again, it grows into "
              "the fractal."):
            "基因就是一小串整数段：每一段说明曲线的下一份副本放在哪里。"
            "把它反复套用，就长出分形。",
        ("*", "What Is the Initiator?"): "什么是初始形状？",
        ("*", "The initiator is the shape the gene is first applied to: level 0. A "
              "straight line grows an open fractal, while a polygon closes it — that "
              "is how a Koch snowflake or a Gosper island comes out in one click."):
            "初始形状是基因第一次替换所作用的那个图形，也就是第 0 级。直线长出开放的分形，"
            "多边形则把它闭合——Koch 雪花、闭合的 Gosper 岛就是这么一键生成的。",
        ("*", "Editing"): "编辑",
        ("*", "Preview"): "预览",
        ("*", "Colour Ramp"): "配色",
        ("*", "Output Range"): "输出范围",
        ("*", "Join Levels"): "合并为一个对象",
        ("*", "Range From"): "起始等级",
        ("*", "Range To"): "结束等级",
        ("*", "Generate Curve"): "生成曲线",
        ("*", "Generate Shape Keys"): "生成形态键",
        ("*", "Shape Key Time"): "形态键时间",
        ("*", "Scene Setup"): "场景预设",
        ("*", "Preview draw failed: {error}"): "预览绘制失败：{error}",
        ("*", "Level {level} needs about {count:,} points (limit {limit:,}); "
              "the highest level that fits is {max}"):
            "第 {level} 级约需 {count:,} 点（上限 {limit:,}），最高可到第 {max} 级",

        # --- initiator ----------------------------------------------------
        ("*", "Initiator"): "初始形状",
        ("*", "Line"): "直线",
        ("*", "Triangle"): "正三角形",
        ("*", "Square"): "正方形",
        ("*", "Pentagon"): "正五边形",
        ("*", "Hexagon"): "正六边形",
        ("*", "Octagon"): "正八边形",
        ("*", "{sides}-gon"): "{sides} 边",
        ("*", "Curve"): "曲线",
        ("*", "No curve selected: currently a straight line"): "还没选曲线：当前等于直线",
        ("*", "Custom Curve"): "自定义曲线",
        ("*", "Initiator Curve"): "初始曲线",
        ("*", "Reverse"): "反向",
        ("*", "Reverse Initiator Direction"): "反向初始折线方向",

        # --- properties ---------------------------------------------------
        ("*", "Domain"): "域",
        ("*", "Active Segment"): "当前段",
        ("*", "Level"): "等级",
        ("*", "Spline"): "样条",
        ("*", "Pending"): "待生成",
        ("*", "Points"): "点数",
        ("*", "Generated Level"): "生成等级",
        ("*", "Time"): "耗时",
        ("*", "Error"): "错误",
        ("*", "Preview Colour"): "预览颜色",
        ("*", "First component of the complex integer (real part in G, coefficient of omega in E)"):
            "复整数第一分量（G 域是实部，E 域是 ω 的系数）",
        ("*", "Second component of the complex integer"): "复整数第二分量",
        ("*", "Use the previous level backwards for this segment (R)"):
            "这一段放入的上一级曲线首尾反向（R）",
        ("*", "Mirror the previous level for this segment (M)"):
            "这一段放入的上一级曲线镜面翻转（M）",

        # --- enum items ---------------------------------------------------
        ("*", "Gaussian G"): "高斯 G",
        ("*", "Eisenstein E"): "艾森斯坦 E",
        ("*", "Square lattice: a + bi"): "方点阵：a + bi",
        ("*", "Triangular lattice: a + b*omega"): "三角点阵：a + bω",
        ("*", "Level Colour"): "等级配色",
        ("*", "Single Colour"): "单色",
        ("*", "Each level has its own fixed colour; the HUD hint uses the same one"):
            "每一级有自己固定的颜色，HUD 的提示线用同一个色号",
        ("*", "Use the preview colour for every level"): "所有等级都用预览颜色",
        # ``Poly`` / ``Bézier`` need no entry here: they are Blender's own names for the two
        # spline types and every language pack already translates them.
        ("*", "Straight segments between the points"): "点与点之间用直线段连接",
        ("*", "Bézier auto handles, smooth between the points"):
            "贝塞尔自动控制柄，点与点之间平滑过渡",
        ("*", "Up"): "上移",
        ("*", "Down"): "下移",

        # --- status sentences --------------------------------------------
        ("*", "Diverging: {ratio:.2f}× larger every level"): "发散：每级放大 {ratio:.2f}×",
        ("*", "Non-contracting: the extent grows with the level"):
            "非收缩：等级越高范围越大",
        ("*", "Contraction {ratio:.2f} (weak, grows at high levels)"):
            "收缩 {ratio:.2f}（偏弱，高级别会明显长大）",
        ("*", "Contraction {ratio:.2f}"): "收缩 {ratio:.2f}",
        ("*", "The clipboard is empty"): "剪贴板是空的",
        ("*", "Paste failed: {error}"): "粘贴失败：{error}",
        ("*", "Imported {family}"): "已导入：{family}",
        ("*", "Nothing to frame: select a curve, or generate one first"):
            "没有可取景的内容：先选一条曲线，或先生成一条",
        ("*", "Content size is zero"): "内容尺寸为零",
        ("*", "Generation failed: {error}"): "生成失败：{error}",
        ("*", "Generation cancelled"): "已取消生成",
        ("*", "Generating level {level} / {high} · {percent}%"):
            "正在生成：第 {level} / {high} 级 · {percent}%",
        ("*", "Points done · preparing the viewport"):
            "点已写完 · 正在准备视口",
        ("*", "{count:,} points"): "{count:,} 点",
        ("*", "ESC cancels"): "按 ESC 可取消",
        ("*", "a gene needs at least two segments"): "基因至少要两段",
        ("*", "the gene has a zero-length segment (adjacent nodes coincide)"):
            "基因里有零长度段（相邻节点重合）",
        ("*", "invalid gene: total vector is zero (nothing to expand into)"):
            "基因无效：总向量为零（分形无处展开）",
        ("*", "gene is empty"): "基因是空的",
        ("*", "Levels {low}-{high} · {splines} splines · {points} points · {ms:.0f} ms"):
            "等级 {low}-{high} · {splines} 条样条 · {points} 点 · {ms:.0f} ms",
        ("*", "Levels {low}-{high} · {count} objects · {points} points · {ms:.0f} ms"):
            "等级 {low}-{high} · {count} 个对象 · {points} 点 · {ms:.0f} ms",
        ("*", "Levels {low}-{high} · {keys} shape keys · {points} points · {ms:.0f} ms"):
            "等级 {low}-{high} · {keys} 个形态键 · {points} 点 · {ms:.0f} ms",
        ("*", "Orthographic top view · frame {scale:.2f} · 2048×2048 · Standard view"):
            "正交俯视 · 取景 {scale:.2f} · 2048×2048 · Standard 色彩变换",

        # --- HUD (drawn with blf, translated via i18n.t) ------------------
        ("*", "Fractal Gene"): "分形基因",
        ("*", "+ Seg"): "加段",
        ("*", "- Seg"): "删段",
        ("*", "Fit"): "适应",
        ("*", "Drag · R/M flags · wheel level · Tab/Esc on panel"):
            "拖节点 · R/M 切标记 · 滚轮换层 · Tab/Esc",

        # --- operator labels ---------------------------------------------
        ("Operator", "Generate Fractal Curves"): "生成分形曲线",
        ("Operator", "Scene Setup"): "场景预设",
        ("Operator", "Add Segment"): "添加一段",
        ("Operator", "Remove Segment"): "删除这一段",
        ("Operator", "Move Segment"): "移动这一段",
        ("Operator", "Copy Gene"): "复制基因",
        ("Operator", "Paste Gene"): "粘贴基因",
        ("Operator", "Switch Lattice Domain"): "切换点阵域",
        ("Operator", "HUD Gene Editor"): "HUD 编辑基因",
        ("Operator", "Dismiss"): "知道了",
        ("Operator", "What Is a Gene?"): "什么是基因？",
        ("Operator", "What Is the Initiator?"): "什么是初始形状？",
        ("Operator", "Cancel"): "取消",

        # --- operator tooltips -------------------------------------------
        # Context-less, unlike the labels above: Blender's own catalogue keeps operator
        # *names* in the "Operator" context and every *tooltip* in the default one, so a
        # ``bl_description`` has to be registered under ``"*"`` to be found.
        ("*", "Build the curve for the current gene. A level too heavy for this "
              "machine is written at the highest level that fits, and the panel "
              "says which one was used"):
            "生成当前基因的曲线。本机吃不下的等级会按能容纳的最高等级生成，面板会说明实际用了哪一级",
        ("*", "Hide this notice"): "隐藏这条提示",
        ("*", "Check the requested level before writing anything. A level over this "
              "machine's budget asks whether to write the level that fits or to "
              "insist on the requested one"):
            "写入前先检查等级：超出本机预算时询问是生成能容纳的等级，还是坚持原等级",
        ("*", "Cancel this build without generating anything"):
            "取消本次操作，不生成任何东西",
        ("*", "Frame the selected curve with an orthographic top-view camera, "
              "a 2048×2048 render and the Standard view transform"):
            "用正交俯视摄像机、2048×2048 分辨率与 Standard 色彩变换框住选中的曲线",
        ("*", "Add a segment at the end, starting in the direction of the last one"):
            "在末尾加一段，方向沿用最后一段",
        ("*", "Remove the selected segment. A gene needs at least two"):
            "删除选中的这一段。基因至少需要两段",
        ("*", "Move the selected segment one place up or down"):
            "把选中的这一段上移或下移一位",
        ("*", "Switch between the Gaussian (square) and Eisenstein (triangular) "
              "lattice: the same two integers point in different directions"):
            "在高斯（正方）与艾森斯坦（三角）点阵之间切换：同一对整数在两个点阵里指向不同方向",
        ("*", 'Copy this gene as text, for example "G 1 0 0 0 0 1 1 0"'):
            "把当前基因复制为文本，例如「G 1 0 0 0 0 1 1 0」",
        ("*", "Read a gene from the clipboard and make it the current gene"):
            "从剪贴板读取基因，并设为当前基因",
        ("*", "Open the in-viewport gene editor: drag nodes, click R/M to toggle "
              "flags, wheel to change the level. Esc or × closes it, and the rest "
              "of the viewport keeps working as usual"):
            "在 3D 视口里打开基因编辑器：拖动节点、点 R/M 切换标记、滚轮换层。"
            "按 Esc 或点 × 关闭，视口其余部分照常可用",

        # --- 本机预算 / 退化提示 ------------------------------------------
        ("*", "{count:,} points · {seconds} · {size}"):
            "{count:,} 点 · {seconds} · {size}",
        ("*", "Level {level} · {cost}"): "第 {level} 级 · {cost}",
        ("*", "Available memory {size} · up to {limit:,} points"):
            "可用内存 {size} · 上限 {limit:,} 点",
        ("*", "Available memory {size} · speed {speed:.2f}× reference · up to "
              "{limit:,} points"):
            "可用内存 {size} · 速度 {speed:.2f}× 参考机 · 上限 {limit:,} 点",
        ("*", "Speed calibration runs on the first Generate"): "首次生成时会测一次本机速度",
        ("*", "Not enough memory for this level"): "该等级内存不足",
        ("*", "Not enough memory for level {level}: it needs about {size} and {avail} is "
              "available. The viewport preview shows it instead"):
            "第 {level} 级内存不足：约需 {size}，当前可用 {avail}。已改用视口预览显示",
        ("*", "Generated level {actual} instead of {requested} (budget for this machine)"):
            "已生成第 {actual} 级（请求第 {requested} 级，受本机预算限制）",

        # --- 面板文案（2026-11-05 精简后新写的短句）--------------------------
        ("*", "Changed"): "已修改",
        ("*", "Up to date"): "已生成",
        ("*", "Keep"): "保留",
        ("*", "Performance warning"): "性能警告",
        ("*", "Writes level {limit}, not {level}"): "将写入第 {limit} 级，不是第 {level} 级",
        ("*", "Shape keys ≤ level {limit}"): "形态键 ≤ 第 {limit} 级",
        ("*", "Preview stops at level {limit}"): "预览止于第 {limit} 级",
        ("*", "Wrote level {actual}, not {requested}"): "已写入第 {actual} 级（请求第 {requested} 级）",
        ("*", "Wrote level {actual} over the budget"): "已按第 {actual} 级写入（超出预算）",
        ("*", "Level {level} anyway"): "仍然生成第 {level} 级",
        ("*", "Last: L{levels} · {points:,} points · {ms:.0f} ms"):
            "上次：第 {levels} 级 · {points:,} 点 · {ms:.0f} 毫秒",
        ("*", "{size} free · up to {limit:,} points"):
            "{size} 可用 · 上限 {limit:,} 点",

        # --- 生成前的选择（超出预算时先问，不再静默降级） ----------------------
        ("*", "Over budget"): "超出预算",
        ("*", "Settings locked · Cancel to edit"): "设置已锁定 · 取消后可改",
        ("*", "Cancel"): "取消",
        ("*", "Would write level {limit}, not {level}"):
            "将写入第 {limit} 级，而不是第 {level} 级",
        ("*", "Generate level {level}"): "生成第 {level} 级",
        ("*", "Level {level} · {size}"): "第 {level} 级 · {size}",
        ("*", "About {seconds} · level {level} fits the budget"):
            "约 {seconds} · 第 {level} 级在预算内",
        ("*", "Not enough memory"): "内存不足",
        ("*", "Level {level} needs {size}, {avail} free"):
            "第 {level} 级需要 {size}，当前可用 {avail}",
        ("*", "Generating it anyway is not offered"):
            "该等级会卡死机器，因此不提供「仍然生成」",
        ("*", "Build would take too long"): "生成耗时过长",
        ("*", "About {minutes} min · generating anyway is not offered"):
            "约需 {minutes} 分钟，不提供「仍然生成」",
        ("*", "This level cannot be generated"): "该等级无法生成",
        ("*", "Level {level} needs about {size}, but only {avail} is free. "
              "Generating it would freeze this machine, so it was not written"):
            "第 {level} 级约需 {size}，当前只有 {avail} 可用。"
            "强制生成会让机器卡死，因此没有写入。",
        ("*", "Level {level} would take about {minutes} minutes to build. "
              "It was not written"):
            "第 {level} 级预计需要约 {minutes} 分钟，因此没有写入。",
    }
}


def _classes():
    """RNA classes to register, in dependency order (property groups first)."""
    from . import budget, ops, props, ui

    return (
        # Preferences first: the panel's budget dropdown is a proxy onto it, so the
        # property has to exist before anything reads it.
        budget.FRACTALFAMILY_AP_preferences,
        props.GeneratorItem,
        props.GenFractalFamilySettings,
        ui.FRACTALFAMILY_UL_items,
        ops.FRACTALFAMILY_OT_generate,
        ops.FRACTALFAMILY_OT_setup_scene,
        ops.FRACTALFAMILY_OT_item_add,
        ops.FRACTALFAMILY_OT_item_remove,
        ops.FRACTALFAMILY_OT_item_move,
        ops.FRACTALFAMILY_OT_copy_gene,
        ops.FRACTALFAMILY_OT_paste_gene,
        ops.FRACTALFAMILY_OT_set_domain,
        ops.FRACTALFAMILY_OT_hud,
        ops.FRACTALFAMILY_OT_clear_notice,
        ops.FRACTALFAMILY_OT_clear_request,
        ops.FRACTALFAMILY_OT_gene_help,
        ops.FRACTALFAMILY_OT_initiator_help,
        ops.FRACTALFAMILY_OT_request_generate,
        ui.FRACTALFAMILY_PT_panel,
    )


def register():
    import bpy

    from . import hud, preview, props

    for cls in _classes():
        bpy.utils.register_class(cls)
    # The pointer must be attached after GenFractalFamilySettings is registered.
    props.register()
    # Two draw handlers: 3D preview (POST_VIEW) and HUD (POST_PIXEL).
    preview.install()
    hud.install()
    # Fill a default gene on first enable (needs a usable scene context).
    props.install_bootstrap()
    bpy.app.translations.register(__name__, translation_dict)


def unregister():
    import bpy

    from . import hud, preview, props

    # Remove handlers / timers first: they touch RNA classes and would be left dangling
    # once the classes are unregistered.
    props.remove_bootstrap()
    hud.remove()
    preview.remove()
    props.unregister()
    for cls in reversed(_classes()):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    bpy.app.translations.unregister(__name__)
