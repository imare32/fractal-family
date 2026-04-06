bl_info = {
    "name": "Fractal Family",
    "author": "imare32",
    "description": "Create fractal curves with ease using complex integer lattices.",
    "blender": (4, 2, 0),
    "version": (1, 1, 5),
    "location": "3D Viewport > Sidebar > Edit",
    "warning": "",
    "category": "Generic",
}

import bpy
from . import auto_load

translation_dict = {
    "zh_HANS": {
        ("*", "Fractal Family"): "分形家族",
        ("*", "Create fractal curves with ease using complex integer lattices."): "使用复整数格子轻松创建分形曲线。",
        ("*", "Complex Integer"): "复整数",
        ("*", "Complex integer on G or E domain."): "G 域或 E 域上的复整数。",
        ("*", "Transform Flags"): "变换标记",
        ("*", "Reverse flag, Mirror flag"): "反转标记，镜像标记",
        ("*", "Name"): "名称",
        ("*", "Domain"): "域",
        ("*", "Domain:"): "域:",
        ("*", "Gaussian"): "高斯",
        ("*", "Gaussian domain"): "高斯域",
        ("*", "Eisenstein"): "艾森斯坦",
        ("*", "Eisenstein domain"): "艾森斯坦域",
        ("*", "Initiator Curve"): "初始曲线",
        ("*", "Keep empty to use the segment from origin to the last accumulated coordinate."): "保持为空以使用从原点到最后累积坐标的线段。",
        ("*", "Reverse"): "反转",
        ("*", "Use the reversed sequence of the initiator curve points."): "使用初始曲线点的反转序列。",
        ("*", "Preset"): "预设",
        ("*", "Select a preset to edit or create fractal curves"): "选择一个预设以编辑或创建分形曲线",
        ("*", "Spline Type"): "样条类型",
        ("*", "Spline type of the generated fractal curves"): "生成的分形曲线的样条类型",
        ("*", "Poly"): "多段线",
        ("*", "Smooth"): "平滑",
        ("*", "Level of fractal curves"): "分形曲线的层级",
        ("*", "The level of fractal curves, from 1 to 20"): "分形曲线的层级，从 1 到 20",
        ("*", "Show Preview"): "显示预览",
        ("*", "Show preview of the fractal curves"): "显示分形曲线的预览",
        ("*", "Add Item"): "添加项",
        ("Operator", "Add Item"): "添加项",
        ("*", "Remove Item"): "移除项",
        ("Operator", "Remove Item"): "移除项",
        ("*", "Move Item"): "移动项",
        ("Operator", "Move Item"): "移动项",
        ("*", "Up"): "上移",
        ("*", "Down"): "下移",
        ("*", "Generator Items:"): "生成器项:",
        ("*", "At least two generator items are required."): "至少需要两个生成器项。",
        ("*", "Generator integer norm must not be zero."): "生成器整数范数不能为零。",
        ("*", "Create Each Level"): "创建每一级",
        ("Operator", "Create Each Level"): "创建每一级",
        ("*", "Create Last Level"): "创建最后一级",
        ("Operator", "Create Last Level"): "创建最后一级",
        ("*", "Create Curve with Shape Keys"): "创建带有形态键的曲线",
        ("Operator", "Create Curve with Shape Keys"): "创建带有形态键的曲线",
        ("*", "Evaluation Time"): "评估时间",
        ("*", "Create Teragon Curves"): "创建 Teragon 曲线",
        ("Operator", "Create Teragon Curves"): "创建 Teragon 曲线",
        ("*", "Mode"): "模式",
        ("*", "Mode to create the Teragon Fractal Curves"): "创建 Teragon 分形曲线的模式",
        ("*", "Create Fractal Curves for each level"): "为每一级创建分形曲线",
        ("*", "Create Fractal Curve for the last level"): "为最后一级创建分形曲线",
        ("*", "Create Fractal Curve with Shape Keys"): "创建带有形态键的分形曲线",
        ("*", "Each Level"): "每一级",
        ("*", "Last Level"): "最后一级",
        ("*", "Shape Keys"): "形态键",
    }
}

auto_load.init()


def register():
    auto_load.register()
    bpy.app.translations.register(__name__, translation_dict)


def unregister():
    bpy.app.translations.unregister(__name__)
    auto_load.unregister()
