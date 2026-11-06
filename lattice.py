"""分形基因的纯算法层：复整数、基因解析、点阵吸附、Teragon 展开。

本模块**不 import bpy**（也不 import mathutils），只用 numpy 与纯 Python，因此可以脱离
Blender 直接跑：批量扫基因、和参考实现对拍、给 HUD 算布局都走这里。

术语（沿用 Jeffrey Ventrella 的 fractal curves 记法）：

* **基因**（gene）＝ 一串复整数 + 每段两个变换标记（``reverse`` / ``mirror``）。它描述
  "把一条线段换成折线"的替换规则，也就是分形的 DNA；
* **域**：G = 高斯整数（方点阵，``a + bi``），E = 艾森斯坦整数（三角点阵，``a + bω``）；
* **等级**（level）：替换次数。等级 0 是初始折线（initiator），等级 1 是基因本身，
  再往上每级把每段换成整条上一级曲线；
* **Teragon**：把等级 n 的点列铺到初始折线（initiator）上得到的最终折线。

坐标一律是 **XY 平面的二维点**（``numpy`` 的 ``(n, 2)`` 数组），转角只有绕 Z 的旋转 +
等比缩放 —— 所以整套变换用 :class:`Affine2D`（2×2 矩阵 + 平移）就够，不需要 4×4。
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "DOMAINS",
    "SQRT_3_OVER_2",
    "Affine2D",
    "ComplexInteger",
    "FractalGenerator",
    "cumulative_points",
    "domain_label",
    "elements_of_nodes",
    "estimate_points",
    "format_gene",
    "gene_family",
    "lattice_basis",
    "lattice_from_xy",
    "moved_node",
    "nodes_of",
    "parse_gene",
    "polygon_initiator",
    "snap_to_lattice",
    "teragon",
    "teragon_iter",
    "total_vector",
]

#: 三角点阵的 b 方向的高（√3 / 2）。
SQRT_3_OVER_2 = math.sqrt(3.0) / 2.0

#: 支持的域：G（高斯 / 方点阵）、E（艾森斯坦 / 三角点阵）。
DOMAINS = ("G", "E")

#: 基因最多允许几段。段数既进指数（点数 = ``段数 ^ 等级``），又是 HUD 里一个一个画出来的
#: 节点：从剪贴板粘进来一条几千段的基因会让面板和地图一起卡住。
MAX_GENE_SEGMENTS = 256

#: 域的显示名（面板与 HUD 用）。
_DOMAIN_NAMES = {"G": "Gaussian G · square lattice", "E": "Eisenstein E · triangular lattice"}


def domain_label(domain: str) -> str:
    """域的显示名。"""
    return _DOMAIN_NAMES.get(domain, domain)


class ComplexInteger:
    """G 域或 E 域上的复整数。

    :param a: 第一分量（G 域的实部 / E 域的 ``ω`` 系数的一倍）。
    :param b: 第二分量。
    :param domain: ``"G"`` 或 ``"E"``。
    """

    __slots__ = ("a", "b", "domain")

    def __init__(self, a: int = 0, b: int = 0, domain: str = "G"):
        self.a = int(a)
        self.b = int(b)
        self.domain = domain if domain in DOMAINS else "G"

    # --- 坐标 ---------------------------------------------------------------

    @property
    def coord(self) -> np.ndarray:
        """映射到平面上的二维坐标（``(2,)`` 数组）。

        G 域是 ``(a, b)``；E 域是 ``(a - b/2, b · √3/2)``（即 ``a + bω``，``ω = e^{2πi/3}``
        的实部为 -1/2 那一支）。
        """
        if self.domain == "G":
            return np.array([float(self.a), float(self.b)])
        return np.array([self.a - self.b * 0.5, self.b * SQRT_3_OVER_2])

    @property
    def norm(self) -> int:
        """域范数：G 域是 ``a² + b²``，E 域是 ``a² - ab + b²``（为 0 表示原点）。"""
        if self.domain == "G":
            return self.a * self.a + self.b * self.b
        return self.a * self.a - self.a * self.b + self.b * self.b

    # --- 杂项 ---------------------------------------------------------------

    def to_tuple(self) -> tuple[int, int]:
        """``(a, b)``，写进 RNA 的 ``IntVectorProperty`` / 存盘用。"""
        return self.a, self.b

    def __add__(self, other: ComplexInteger) -> ComplexInteger:
        return ComplexInteger(self.a + other.a, self.b + other.b, self.domain)

    def __eq__(self, other) -> bool:
        if not isinstance(other, ComplexInteger):
            return NotImplemented
        return (self.a, self.b, self.domain) == (other.a, other.b, other.domain)

    def __hash__(self) -> int:
        return hash((self.a, self.b, self.domain))

    def __repr__(self) -> str:
        return f"{self.domain}{self.a, self.b}"


def lattice_basis(domain: str) -> np.ndarray:
    """点阵基矢：``(2, 2)``，第 0 列是 ``a`` 方向，第 1 列是 ``b`` 方向。

    HUD 拖节点时用它与它的逆矩阵在"像素 ↔ 整数"之间换算。
    """
    if domain == "E":
        return np.array([[1.0, -0.5], [0.0, SQRT_3_OVER_2]])
    return np.eye(2)


def lattice_from_xy(domain: str, x: float, y: float) -> tuple[float, float]:
    """平面坐标 → 未取整的 ``(a, b)``（:func:`snap_to_lattice` 的前半段）。"""
    if domain == "E":
        b = y / SQRT_3_OVER_2
        return x + b * 0.5, b
    return x, y


def snap_to_lattice(domain: str, x: float, y: float) -> tuple[int, int]:
    """平面坐标 → 最近的整数格点 ``(a, b)``（HUD 拖动时的吸附）。"""
    a, b = lattice_from_xy(domain, x, y)
    return round(a), round(b)  # round(float) 已经是 int，不必再套一层


# ---------------------------------------------------------------------------
# 基因：解析与格式化
# ---------------------------------------------------------------------------


def parse_gene(gene: str) -> tuple[str, list[tuple[ComplexInteger, tuple[bool, bool]]]]:
    """解析基因字符串，返回 ``(域名, [(复整数, (reverse, mirror)), ...])``。

    格式与参考实现一致：``"G 1 0 0 0 0 1 1 0"`` —— 一个域字母 + 每 4 个整数一段
    （``a b reverse mirror``）。
    """
    parts = gene.split()
    if not parts:
        raise ValueError("gene is empty")
    domain = parts[0].upper()
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain {domain!r} (supported: {DOMAINS})")
    numbers = [int(text) for text in parts[1:]]
    if not numbers or len(numbers) % 4:
        raise ValueError(f"gene must contain a multiple of 4 integers, got {len(numbers)}")
    # Every element multiplies the point count, and the HUD draws one node per element: a
    # pasted gene with thousands of segments would make the panel and the map unusable.
    if len(numbers) // 4 > MAX_GENE_SEGMENTS:
        raise ValueError(
            f"gene has {len(numbers) // 4} segments; the limit is {MAX_GENE_SEGMENTS}"
        )
    elements = []
    for index in range(0, len(numbers), 4):
        a, b, reverse, mirror = numbers[index : index + 4]
        elements.append((ComplexInteger(a, b, domain), (bool(reverse), bool(mirror))))
    return domain, elements


def format_gene(domain: str, elements) -> str:
    """基因 → 字符串（与 :func:`parse_gene` 互逆，面板与 HUD 上显示的就是它）。"""
    numbers = [domain]
    for element, (reverse, mirror) in elements:
        numbers += [str(element.a), str(element.b), str(int(bool(reverse))), str(int(bool(mirror)))]
    return " ".join(numbers)


def total_vector(elements) -> ComplexInteger:
    """基因的总向量（各段复整数之和）；空基因返回原点。"""
    domain = elements[0][0].domain if elements else "G"
    total = ComplexInteger(domain=domain)
    for element, _flags in elements:
        total = total + element
    return total


def gene_family(domain: str, elements) -> str:
    """家族名，形如 ``G(2, 1)``：域 + 总向量（基因各段的复整数和）。

    参考实现用它给预设分组，本插件也拿它当 HUD 标题。
    """
    total = total_vector(elements)
    return f"{domain}({total.a}, {total.b})"


# ---------------------------------------------------------------------------
# 基因 ↔ 节点（HUD 里拖的就是节点）
# ---------------------------------------------------------------------------


def cumulative_points(elements) -> list[tuple[int, int]]:
    """基因各段首尾相接的**终点**列表（不含原点）。

    等级 1 就是这条折线（隐含起点是原点），HUD 的网格区画的是它。
    """
    points = []
    a = b = 0
    for element, _flags in elements:
        a += element.a
        b += element.b
        points.append((a, b))
    return points


def nodes_of(elements) -> list[tuple[int, int]]:
    """含原点的节点列表（长度 = 段数 + 1）。"""
    return [(0, 0), *cumulative_points(elements)]


def elements_of_nodes(nodes, flags=None):
    """节点列表 → 基因（相邻节点之差），:func:`nodes_of` 的逆。

    :param nodes: 含原点的节点列表。
    :param flags: 每段的 ``(reverse, mirror)``；缺省全 False。
    :raises ValueError: 相邻两点重合（零长度段在分形里没有意义）。
    """
    domain = "G"
    elements = []
    for index in range(1, len(nodes)):
        a = nodes[index][0] - nodes[index - 1][0]
        b = nodes[index][1] - nodes[index - 1][1]
        if a == 0 and b == 0:
            raise ValueError(f"segment {index} has zero length")
        reverse, mirror = flags[index - 1] if flags and index - 1 < len(flags) else (False, False)
        elements.append((ComplexInteger(a, b, domain), (bool(reverse), bool(mirror))))
    return elements


def moved_node(elements, index: int, position: tuple[int, int]):
    """把第 ``index`` 个节点（含原点，``index ≥ 1``）挪到 ``position``，返回新基因。

    节点的移动会同时改**相邻两段**的复整数（末节点只改最后一段 —— 总向量因此可以自由
    变化，初始折线自动跟着走）。挪出零长度段时返回 ``None``（HUD 上表现为"拖不过去"）。
    """
    nodes = nodes_of(elements)
    if not 1 <= index < len(nodes):
        return None
    nodes[index] = (int(position[0]), int(position[1]))
    flags = [flags for _element, flags in elements]
    try:
        moved = elements_of_nodes(nodes, flags)
    except ValueError:
        return None
    domain = elements[0][0].domain if elements else "G"
    return [(ComplexInteger(e.a, e.b, domain), f) for e, f in moved]


# ---------------------------------------------------------------------------
# 仿射变换（只有旋转 + 等比缩放 + 平移）
# ---------------------------------------------------------------------------


class Affine2D:
    """XY 平面上的仿射变换：``p ↦ p · Rᵀ + t``。

    分形的替换只用到"把单位线段对齐到目标线段"，所以转角永远绕 Z 轴，缩放是等比的 ——
    2×2 的 ``R`` 加一个平移就够，比 4×4 矩阵快，也不必 import mathutils。
    """

    __slots__ = ("matrix", "offset")

    def __init__(self, matrix=None, offset=None):
        self.matrix = np.eye(2) if matrix is None else np.asarray(matrix, dtype=float)
        self.offset = np.zeros(2) if offset is None else np.asarray(offset, dtype=float)

    @classmethod
    def from_segments(cls, src_start, src_end, tgt_start, tgt_end) -> Affine2D:
        """把 ``src_start → src_end`` 对齐到 ``tgt_start → tgt_end``。"""
        src = np.asarray(src_end, dtype=float) - np.asarray(src_start, dtype=float)
        tgt = np.asarray(tgt_end, dtype=float) - np.asarray(tgt_start, dtype=float)
        src_length = float(np.hypot(*src))
        if src_length < 1e-12:
            raise ValueError("source segment has zero length, cannot build a transform")
        scale = float(np.hypot(*tgt)) / src_length
        angle = math.atan2(tgt[1], tgt[0]) - math.atan2(src[1], src[0])
        cos, sin = math.cos(angle) * scale, math.sin(angle) * scale
        matrix = np.array([[cos, -sin], [sin, cos]])
        offset = np.asarray(tgt_start, dtype=float) - matrix @ np.asarray(src_start, dtype=float)
        return cls(matrix, offset)

    def apply(self, points: np.ndarray) -> np.ndarray:
        """批量变换：``(n, 2)`` → ``(n, 2)``。"""
        array = np.asarray(points, dtype=float)
        if array.size == 0:
            return array.reshape(0, 2)
        return array.reshape(-1, 2) @ self.matrix.T + self.offset

    def __repr__(self) -> str:
        return f"Affine2D({self.matrix.tolist()}, {self.offset.tolist()})"


def _reflect(points: np.ndarray, normal: np.ndarray) -> np.ndarray:
    """关于"过原点、以 ``normal`` 为法向的平面"做镜面反射（与 mathutils 的
    ``Vector.reflect()`` 同义：``v - 2·(v·n̂)n̂``）。

    注意它与"关于以 ``normal`` 为**方向**的直线做镜像"差一个负号 —— 分形里两个都会用到
    （参考实现对结果又取了一次负），实现时别把这个负号漏掉，否则 E 域带 mirror 标记的
    预设会整体翻到另一侧。
    """
    length_squared = float(normal @ normal)
    if length_squared < 1e-12:
        return points
    projection = np.outer(points @ normal, normal) / length_squared
    return points - 2.0 * projection


# ---------------------------------------------------------------------------
# 生成器：等级点列与 Teragon
# ---------------------------------------------------------------------------


class FractalGenerator:
    """一条基因 + 它的等级点列与替换矩阵。

    :param elements: ``[(ComplexInteger, (reverse, mirror)), ...]``。
    :raises ValueError: 基因少于两段、或总向量为零（分形无从展开）。
    """

    def __init__(self, elements):
        self.elements = [(ComplexInteger(e.a, e.b, e.domain), tuple(bool(f) for f in flags))
                         for e, flags in elements]
        if not self.elements:
            raise ValueError("a gene needs at least one segment")
        self.domain = self.elements[0][0].domain
        total = ComplexInteger(domain=self.domain)
        for element, _flags in self.elements:
            total = total + element
        self.integer = total
        self._levels: list[np.ndarray] = []
        if self.is_valid:
            self.matrices = self._build_matrices()

    # --- 基本属性 -----------------------------------------------------------

    @property
    def is_valid(self) -> bool:
        """能否展开：至少两段、且总向量不为零。"""
        return self.integer.norm != 0 and len(self.elements) >= 2

    @property
    def segment_count(self) -> int:
        return len(self.elements)

    def flags(self) -> list[tuple[bool, bool]]:
        """每段的 ``(reverse, mirror)``。"""
        return [flags for _element, flags in self.elements]

    # --- 点列 ---------------------------------------------------------------

    def _build_matrices(self) -> list[Affine2D]:
        """每段一份变换矩阵：把单位线段 ``0 → 总向量`` 铺到该段上。

        **端点必须换成平面坐标再说**：E 域的点阵不是正交的，``(a, b)`` 与 ``(x, y)``
        之间差一个斜变换，直接在整数上算矩阵会让整条曲线错位（G 域恰好看不出问题）。
        """
        origin = np.zeros(2)
        total = self.integer.coord
        ends = [ComplexInteger(a, b, self.domain).coord for a, b in cumulative_points(self.elements)]
        matrices = []
        for index, (_element, (reverse, _mirror)) in enumerate(self.elements):
            start = origin if index == 0 else ends[index - 1]
            end = ends[index]
            if reverse:
                start, end = end, start
            matrices.append(Affine2D.from_segments(origin, total, start, end))
        return matrices

    def level_points(self, level: int) -> list[np.ndarray]:
        """等级 ``0..level`` 的点列（每级一个 ``(n, 2)`` 数组，**不含**隐含起点）。

        与参考实现逐点一致：等级 0 是总向量的终点，等级 1 是基因各段的终点，
        再往上是"每段替换成上一级"的累积结果。
        """
        if not self.is_valid:
            raise ValueError("invalid gene (fewer than two segments or zero total vector)")
        level = max(0, int(level))
        if not self._levels:
            self._levels.append(self.integer.coord.reshape(1, 2))
        while len(self._levels) <= level:
            self._levels.append(self._substitute(self._levels[-1]))
        return self._levels[: level + 1]

    def _segment_points(self, previous: np.ndarray, index: int) -> np.ndarray:
        """上一级点列在第 ``index`` 段上的那一份（已做 reverse / mirror 处理）。"""
        matrix = self.matrices[index]
        _element, (reverse, mirror) = self.elements[index]
        points = previous
        if reverse:
            # 与参考实现逐字一致：反转后的点列丢掉末点、末尾补原点
            points = np.vstack([np.zeros((1, 2)), points[:-1]])[::-1]
        if mirror:
            points = -_reflect(points, self.integer.coord)
        return matrix.apply(points)

    def _substitute(self, previous: np.ndarray) -> np.ndarray:
        """把上一级点列按基因的每一段各复制一份，首尾相接。

        输出**预分配**后按段写入，而不是收集 ``chunks`` 再 ``vstack``：后者在最高级上
        等于把整级点列再复制一遍，而这一级本来就占了生成峰值内存的一半。
        """
        previous = np.asarray(previous, dtype=float).reshape(-1, 2)
        count = len(previous)
        out = np.empty((len(self.matrices) * count, 2), dtype=float)
        for index in range(len(self.matrices)):
            out[index * count:(index + 1) * count] = self._segment_points(previous, index)
        return out

    def iter_levels(self, top: int):
        """等级 ``0..top`` 的点列，**逐级产出**，不保留已经产出的级别。

        与 :meth:`level_points` 的唯一区别是内存：``level_points`` 把每一级都留在
        ``_levels`` 缓存里（总和约为最高级的 1.1–2 倍），百万点级别下那是生成峰值内存的
        一大半。生成路径用它，预览与标定仍用缓存版（它们只到 12 万点）。

        产出的是**可变数组**，调用方可以放心持有：下一级是新算的，不会覆盖它。
        """
        if not self.is_valid:
            raise ValueError("invalid gene (fewer than two segments or zero total vector)")
        current = self.integer.coord.reshape(1, 2)
        yield 0, current
        for level in range(1, max(0, int(top)) + 1):
            current = self._substitute(current)
            yield level, current

    def estimate_points(self, level: int, initiator_segments: int = 1) -> int:
        """等级 ``level`` 展开后的大致顶点数（面板上用来提示"这一级有多重"）。"""
        return int(initiator_segments) * (len(self.elements) ** max(0, int(level))) + 1

    @property
    def contraction(self) -> float:
        """每级的缩放比上界 ``max(|e_i|) / |总向量|``。

        这是 Teragon 的**自相似比**：每一段被换成一份"缩到该段长度"的上一级曲线，
        缩放系数就是 ``|e_i| / |T|``。三个区间的含义完全不同：

        * ``< 1``：收缩，正常分形 —— 等级越高越细腻，**范围基本不变**；
        * ``= 1``：非收缩 —— 长度每级 × 段数，**范围随等级长大**（E 域里很容易撞上，
          因为 ``1, ω, 1+ω`` 这些向量的平面长度都是 1）；
        * ``> 1``：发散 —— 每级放大 ``contraction`` 倍，等级一高坐标就爆掉。
        """
        total = float(np.hypot(*self.integer.coord))
        if total <= 0.0:
            return 0.0
        longest = max(float(np.hypot(*element.coord)) for element, _flags in self.elements)
        return longest / total

    def __repr__(self) -> str:
        return f"FractalGenerator({format_gene(self.domain, self.elements)})"


def estimate_points(elements, level: int, initiator_segments: int = 1) -> int:
    """:meth:`FractalGenerator.estimate_points` 的函数版（不必建对象）。"""
    if not elements:
        return 1
    return int(initiator_segments) * (len(elements) ** max(0, int(level))) + 1


# ---------------------------------------------------------------------------
# Teragon：把等级点列铺到初始折线上
# ---------------------------------------------------------------------------


def polygon_initiator(sides: int, integer: ComplexInteger, reverse: bool = False) -> np.ndarray:
    """正 ``sides`` 边形的初始折线：**边长 = |总向量|**，第一条边从原点沿总向量方向。

    Koch 雪花这类闭合分形需要一条首尾相接的初始折线。自己建曲线时既要凑正多边形、又要把
    边长对齐到 ``|总向量|``（差一点就在接缝处错位），所以这里直接算出来。

    边长必须是 ``|总向量|``：Teragon 的每一段替换都是把"单位线段 ``0 → 总向量``"铺到初始
    折线的一段上，只有边长相等时接缝才严丝合缝。

    **绕行方向取顺时针**（多边形的实体落在第一条边的右侧）：左弯的基因（Koch 曲线是典型）
    于是朝**外**长，选个正三角形就是常见的雪花；要看朝里长的版本把 ``reverse`` 打开
    （反向读点序，圆弧的凹凸跟着翻）。

    :param sides: 边数（少于 3 按 3 算）。
    :param integer: 基因的总向量（决定边长与第一条边的方向）。
    :param reverse: 反向遍历顶点（形状不变，起点换到末顶点）。
    """
    sides = max(3, int(sides))
    total = np.asarray(integer.coord, dtype=float)
    side = float(np.hypot(total[0], total[1]))
    heading = math.atan2(total[1], total[0])
    step = -2.0 * math.pi / sides
    points = np.zeros((sides, 2))
    for index in range(1, sides):
        angle = heading + (index - 1) * step
        points[index] = points[index - 1] + side * np.array([math.cos(angle), math.sin(angle)])
    if reverse:
        points = points[::-1].copy()
    return points


def initiator_affines(initiator_points, integer: ComplexInteger, closed: bool = False) -> list[Affine2D]:
    """初始折线每一段一份矩阵：把单位线段 ``0 → 总向量`` 铺到该段上。

    :param initiator_points: 初始折线的顶点（``(n, 2)`` 或点列表）。
    :param integer: 基因的总向量（决定"单位线段"有多长、朝哪）。
    :param closed: 初始折线是否闭合（闭合时补上末点 → 首点那一段）。
    """
    points = np.asarray(initiator_points, dtype=float).reshape(-1, 2)
    if closed and len(points) > 1:
        points = np.vstack([points, points[:1]])
    origin = np.zeros(2)
    total = integer.coord
    return [
        Affine2D.from_segments(origin, total, points[index - 1], points[index])
        for index in range(1, len(points))
    ]


def teragon_iter(
    generator: FractalGenerator,
    level: int,
    initiator_points=None,
    closed: bool = False,
):
    """展开成 Teragon，**逐级产出** ``(等级, 折线)``，不保留整条等级链。

    与 :func:`teragon` 的区别只在内存与调用方：生成百万点的曲线时，一路保留 ``0..N``
    全部折线是峰值内存的一半，而实际需要的往往只是其中几级。产出一级就可以写进曲线再
    丢掉，于是峰值只剩「当前一级 + 曲线本身」。

    :param generator: 基因。
    :param level: 最高等级。
    :param initiator_points: 初始折线；``None`` = 从原点到总向量的一条直线。
    :param closed: 初始折线是否闭合。
    """
    if initiator_points is None:
        initiator_points = np.array([[0.0, 0.0], generator.integer.coord])
    points = np.asarray(initiator_points, dtype=float).reshape(-1, 2)
    affines = initiator_affines(points, generator.integer, closed)
    for index, row in generator.iter_levels(level):
        count = len(row)
        if count == 0:
            yield index, np.array(points[:1], dtype=float)
            continue
        # 预分配 + 按段写入（理由同 ``_substitute``：省掉一次整级拷贝）。
        line = np.empty((len(affines) * count + 1, 2), dtype=float)
        line[0] = points[0]
        for slot, affine in enumerate(affines):
            line[1 + slot * count:1 + (slot + 1) * count] = affine.apply(row)
        if closed and len(line) > 1:
            line = line[:-1]
        yield index, line


def teragon(
    generator: FractalGenerator,
    level: int,
    initiator_points=None,
    closed: bool = False,
) -> list[np.ndarray]:
    """展开成 Teragon：返回等级 ``0..level`` 的折线（每级一个 ``(n, 2)`` 数组）。

    保留整条等级链，方便调用方按等级取用（预览、标定、对拍）。生成路径用
    :func:`teragon_iter`，它不会同时持有所有级别。

    :param generator: 基因。
    :param level: 最高等级。
    :param initiator_points: 初始折线；``None`` = 从原点到总向量的一条直线。
    :param closed: 初始折线是否闭合。
    """
    return [line for _index, line in teragon_iter(generator, level, initiator_points, closed)]
