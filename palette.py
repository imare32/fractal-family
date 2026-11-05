"""Colour constants and sRGB -> linear helpers (single source for the add-on).

Two rules:

* colour values are written as sRGB hex;
* anything handed to Blender as a *colour attribute* (world background, materials,
  ``vertex_color``) must be converted to linear first, otherwise it renders washed out —
  use :func:`hex_to_linear`.

The HUD is the exception: it is drawn as a 2D overlay with no colour management, so its
colours (and the theme in :mod:`hud_layout`) stay in sRGB.
"""

from __future__ import annotations

__all__ = [
    "AMBER",
    "AZURITE",
    "BACKGROUND",
    "CINNABAR",
    "INK",
    "LEVEL_COLOURS",
    "MOSS",
    "OCHRE",
    "PALETTE",
    "PAPER",
    "SILK",
    "hex_to_linear",
    "hex_to_rgb",
    "level_colour",
    "srgb_to_linear",
]

INK = "#2B2B2B"  # 墨玄
CINNABAR = "#C85A4B"  # 朱砂
AZURITE = "#3E5C6B"  # 石青
OCHRE = "#C49A45"  # 赭石
AMBER = "#E8B362"  # 琥珀 —— 明亮暖金，浅画布上的默认主线色
MOSS = "#5A7052"  # 苔绿
SILK = "#F4F0EA"  # 绢白

#: 画布底色 —— 作品统一用它，避免每个后端各写一个白。
BACKGROUND = "#E4D9D0"

#: 更浅的一档画布：接近纸白、几乎无色偏。线稿（细线 + 暖金）在它上面反差最大；
#: 用来画"填色块"的图案就别用它 —— 绢白的本体压上去会看不出边界。
PAPER = "#F9F7F3"

#: 常量名 → 色值，给需要遍历色板的场合用（导出色卡、做一个配色面板）。
PALETTE = {
    "INK": INK,
    "CINNABAR": CINNABAR,
    "AZURITE": AZURITE,
    "OCHRE": OCHRE,
    "AMBER": AMBER,
    "MOSS": MOSS,
    "SILK": SILK,
    "BACKGROUND": BACKGROUND,
    "PAPER": PAPER,
}


#: Fixed colour per level (index 0 = level 1).  Shared by the viewport preview and the HUD
#: hint so both show the current level in the same hue.  One colour per level also means a
#: level keeps its identity when the level count changes.
LEVEL_COLOURS = (
    CINNABAR,   # level 1
    "#4FA8D8",  # level 2  azure
    "#45C96B",  # level 3  green
    "#EE9A2E",  # level 4  orange
    "#D46BC8",  # level 5  magenta
    "#EFDC55",  # level 6  yellow
)


def level_colour(index: int) -> str:
    """Hex colour for a level number (1-based, clamped to :data:`LEVEL_COLOURS`)."""
    slot = max(1, int(index)) - 1
    return LEVEL_COLOURS[min(slot, len(LEVEL_COLOURS) - 1)]


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    """``"#RRGGBB"`` → sRGB 0..1 三元组（``#`` 可省，大小写不限）。"""
    text = value.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected #RRGGBB, got {value!r}")
    return tuple(int(text[index : index + 2], 16) / 255.0 for index in (0, 2, 4))


def srgb_to_linear(component: float) -> float:
    """单个 sRGB 分量 → 线性（Blender 的颜色属性按线性存储）。"""
    if component <= 0.04045:
        return component / 12.92
    return ((component + 0.055) / 1.055) ** 2.4


def hex_to_linear(value: str) -> tuple[float, float, float]:
    """``"#RRGGBB"`` → 线性 0..1 三元组，可直接写进 Blender 的颜色属性。"""
    return tuple(srgb_to_linear(component) for component in hex_to_rgb(value))
