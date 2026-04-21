from __future__ import annotations

import argparse
import math
import os
import random
from dataclasses import dataclass
from typing import List, Tuple, Dict, Set

import yaml


# =========================
# 基本常量
# =========================

STUD = 0.032       # LEGO Duplo stud pitch, m
BRICK_H = 0.020    # brick height, m

# 统一扩大后的 plate 设置
DEFAULT_PARTS_PLATE_CENTER = (0.0, -0.16, 0.0)
DEFAULT_ASSEMBLY_PLATE_CENTER = (0.0, 0.16, 0.0)

PARTS_PLATE_SIZE = (0.40, 0.28)      # width, height in m
ASSEMBLY_PLATE_SIZE = (0.32, 0.28)   # width, height in m

COLORS = ["red", "blue", "yellow", "green"]


# =========================
# 数据结构
# =========================

@dataclass
class BrickSpec:
    name: str
    type: str
    color: str
    pos: List[float]       # [x, y, z]
    rotation: List[float]  # [roll, pitch, yaw]

    def yaw_deg(self) -> int:
        return int(round(math.degrees(self.rotation[2]))) % 180

    def dims_xy(self) -> Tuple[float, float]:
        if self.type == "brick_2x2":
            dx, dy = 2 * STUD, 2 * STUD
        elif self.type == "brick_4x2":
            dx, dy = 4 * STUD, 2 * STUD
        else:
            raise ValueError(f"Unknown brick type: {self.type}")

        if self.yaw_deg() == 90:
            dx, dy = dy, dx
        return dx, dy

    def bbox_xy(self) -> Tuple[float, float, float, float]:
        dx, dy = self.dims_xy()
        x, y = self.pos[0], self.pos[1]
        return (x - dx / 2.0, x + dx / 2.0, y - dy / 2.0, y + dy / 2.0)


@dataclass
class SceneBrick:
    name: str
    type: str
    color: str
    pos: List[float]
    rotation: List[float]

    def yaw_deg(self) -> int:
        return int(round(math.degrees(self.rotation[2]))) % 180

    def dims_xy(self) -> Tuple[float, float]:
        if self.type == "brick_2x2":
            dx, dy = 2 * STUD, 2 * STUD
        elif self.type == "brick_4x2":
            dx, dy = 4 * STUD, 2 * STUD
        else:
            raise ValueError(f"Unknown brick type: {self.type}")

        if self.yaw_deg() == 90:
            dx, dy = dy, dx
        return dx, dy


# =========================
# 工具函数
# =========================

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_yaml(data: Dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True)


def yaw_to_rotation(yaw_deg: int) -> List[float]:
    return [0.0, 0.0, round(math.radians(yaw_deg), 4)]


def random_color(rng: random.Random) -> str:
    return rng.choice(COLORS)


def random_brick_type(rng: random.Random) -> str:
    return rng.choice(["brick_2x2", "brick_4x2"])


def random_yaw(rng: random.Random) -> int:
    return rng.choice([0, 90])


def make_brick_name(brick_type: str, idx: int) -> str:
    short = "2x2" if brick_type == "brick_2x2" else "4x2"
    return f"{short}_brick_{idx}"


def type_to_grid_size(brick_type: str, yaw_deg: int) -> Tuple[int, int]:
    if brick_type == "brick_2x2":
        sx, sy = 2, 2
    elif brick_type == "brick_4x2":
        sx, sy = 4, 2
    else:
        raise ValueError(f"Unknown brick type: {brick_type}")

    if yaw_deg % 180 == 90:
        sx, sy = sy, sx
    return sx, sy


def plate_grid_capacity(plate_size: Tuple[float, float]) -> Tuple[int, int]:
    return int(plate_size[0] / STUD), int(plate_size[1] / STUD)


def footprint_cells(gx: int, gy: int, brick_type: str, yaw_deg: int) -> List[Tuple[int, int]]:
    sx, sy = type_to_grid_size(brick_type, yaw_deg)
    return [(gx + dx, gy + dy) for dx in range(sx) for dy in range(sy)]


def add_to_occupied(
    gx: int,
    gy: int,
    gz: int,
    brick_type: str,
    yaw_deg: int,
    occupied: Dict[Tuple[int, int, int], str],
    brick_name: str
) -> None:
    for cx, cy in footprint_cells(gx, gy, brick_type, yaw_deg):
        occupied[(cx, cy, gz)] = brick_name


def has_support(
    gx: int,
    gy: int,
    gz: int,
    brick_type: str,
    yaw_deg: int,
    occupied: Dict[Tuple[int, int, int], str]
) -> bool:
    if gz == 0:
        return True

    below = 0
    for cx, cy in footprint_cells(gx, gy, brick_type, yaw_deg):
        if (cx, cy, gz - 1) in occupied:
            below += 1
    return below > 0


def placeable(
    gx: int,
    gy: int,
    gz: int,
    brick_type: str,
    yaw_deg: int,
    occupied: Dict[Tuple[int, int, int], str],
    grid_w: int,
    grid_h: int
) -> bool:
    sx, sy = type_to_grid_size(brick_type, yaw_deg)

    if gx < 0 or gy < 0 or gx + sx > grid_w or gy + sy > grid_h:
        return False

    for cx, cy in footprint_cells(gx, gy, brick_type, yaw_deg):
        if (cx, cy, gz) in occupied:
            return False

    if not has_support(gx, gy, gz, brick_type, yaw_deg, occupied):
        return False

    return True


def grid_to_metric(
    gx: int,
    gy: int,
    gz: int,
    plate_center: Tuple[float, float, float],
    plate_size: Tuple[float, float],
    brick_type: str,
    yaw_deg: int
) -> List[float]:
    sx, sy = type_to_grid_size(brick_type, yaw_deg)

    plate_min_x = plate_center[0] - plate_size[0] / 2.0
    plate_min_y = plate_center[1] - plate_size[1] / 2.0

    px = plate_min_x + (gx + sx / 2.0) * STUD
    py = plate_min_y + (gy + sy / 2.0) * STUD
    pz = plate_center[2] + gz * BRICK_H
    return [round(px, 4), round(py, 4), round(pz, 4)]


def within_plate_xy(
    center_xy: Tuple[float, float],
    dims_xy: Tuple[float, float],
    plate_center: Tuple[float, float, float],
    plate_size: Tuple[float, float],
    margin: float = 0.0,
) -> bool:
    x, y = center_xy
    dx, dy = dims_xy

    min_x = plate_center[0] - plate_size[0] / 2.0 + margin
    max_x = plate_center[0] + plate_size[0] / 2.0 - margin
    min_y = plate_center[1] - plate_size[1] / 2.0 + margin
    max_y = plate_center[1] + plate_size[1] / 2.0 - margin

    if x - dx / 2.0 < min_x:
        return False
    if x + dx / 2.0 > max_x:
        return False
    if y - dy / 2.0 < min_y:
        return False
    if y + dy / 2.0 > max_y:
        return False
    return True


def rect_gap_ok(
    a_center: Tuple[float, float],
    a_dims: Tuple[float, float],
    b_center: Tuple[float, float],
    b_dims: Tuple[float, float],
    min_gap: float
) -> bool:
    ax, ay = a_center
    bx, by = b_center
    aw, ah = a_dims
    bw, bh = b_dims

    a_half_w = aw / 2.0 + min_gap / 2.0
    a_half_h = ah / 2.0 + min_gap / 2.0
    b_half_w = bw / 2.0 + min_gap / 2.0
    b_half_h = bh / 2.0 + min_gap / 2.0

    overlap_x = abs(ax - bx) < (a_half_w + b_half_w)
    overlap_y = abs(ay - by) < (a_half_h + b_half_h)

    return not (overlap_x and overlap_y)


# =========================
# 目标结构连通性检查
# =========================

def interval_overlap_len(a1: float, a2: float, b1: float, b2: float) -> float:
    return max(0.0, min(a2, b2) - max(a1, b1))


def bricks_touch_or_support(a: BrickSpec, b: BrickSpec, eps: float = 1e-6) -> bool:
    ax1, ax2, ay1, ay2 = a.bbox_xy()
    bx1, bx2, by1, by2 = b.bbox_xy()

    az = a.pos[2]
    bz = b.pos[2]

    overlap_x = interval_overlap_len(ax1, ax2, bx1, bx2)
    overlap_y = interval_overlap_len(ay1, ay2, by1, by2)

    # 同层相邻/接触：要求平面 footprint 有正面积重叠
    if abs(az - bz) < eps:
        if overlap_x > eps and overlap_y > eps:
            return True

    # 上下层支撑：层高差一个 BRICK_H，且 footprint 有正面积重叠
    if abs(abs(az - bz) - BRICK_H) < eps:
        if overlap_x > eps and overlap_y > eps:
            return True

    return False


def verify_goal_connected(goal_bricks: List[BrickSpec]) -> bool:
    if not goal_bricks:
        return False
    if len(goal_bricks) == 1:
        return True

    graph: Dict[int, Set[int]] = {i: set() for i in range(len(goal_bricks))}
    for i in range(len(goal_bricks)):
        for j in range(i + 1, len(goal_bricks)):
            if bricks_touch_or_support(goal_bricks[i], goal_bricks[j]):
                graph[i].add(j)
                graph[j].add(i)

    visited = set()
    stack = [0]
    while stack:
        u = stack.pop()
        if u in visited:
            continue
        visited.add(u)
        stack.extend(graph[u] - visited)

    return len(visited) == len(goal_bricks)


# =========================
# 基础验证
# =========================

def verify_goal_basic(goal_bricks: List[BrickSpec]) -> bool:
    names = set()
    for b in goal_bricks:
        if b.name in names:
            return False
        names.add(b.name)
        if b.type not in ("brick_2x2", "brick_4x2"):
            return False
        if b.color not in COLORS:
            return False
    return True


def verify_goal_within_assembly_plate(goal_bricks: List[BrickSpec]) -> bool:
    for b in goal_bricks:
        if not within_plate_xy(
            center_xy=(b.pos[0], b.pos[1]),
            dims_xy=b.dims_xy(),
            plate_center=DEFAULT_ASSEMBLY_PLATE_CENTER,
            plate_size=ASSEMBLY_PLATE_SIZE,
            margin=0.0,
        ):
            return False
    return True


def verify_scene_init(scene_bricks: List[SceneBrick], min_distance_m: float) -> bool:
    for b in scene_bricks:
        if not within_plate_xy(
            center_xy=(b.pos[0], b.pos[1]),
            dims_xy=b.dims_xy(),
            plate_center=DEFAULT_PARTS_PLATE_CENTER,
            plate_size=PARTS_PLATE_SIZE,
            margin=0.0,
        ):
            return False

    for i in range(len(scene_bricks)):
        for j in range(i + 1, len(scene_bricks)):
            bi = scene_bricks[i]
            bj = scene_bricks[j]
            if not rect_gap_ok(
                (bi.pos[0], bi.pos[1]), bi.dims_xy(),
                (bj.pos[0], bj.pos[1]), bj.dims_xy(),
                min_distance_m
            ):
                return False
    return True


# =========================
# 四类任务生成
# =========================

def generate_two_brick_stack(rng: random.Random) -> List[BrickSpec]:
    plate = DEFAULT_ASSEMBLY_PLATE_CENTER
    plate_size = ASSEMBLY_PLATE_SIZE
    bricks: List[BrickSpec] = []

    base_type = random_brick_type(rng)
    top_type = random_brick_type(rng)
    base_yaw = random_yaw(rng)
    top_yaw = random_yaw(rng)

    gx, gy = 1, 1

    base = BrickSpec(
        name=make_brick_name(base_type, 1),
        type=base_type,
        color=random_color(rng),
        pos=grid_to_metric(gx, gy, 0, plate, plate_size, base_type, base_yaw),
        rotation=yaw_to_rotation(base_yaw),
    )

    top = BrickSpec(
        name=make_brick_name(top_type, 2),
        type=top_type,
        color=random_color(rng),
        pos=grid_to_metric(gx, gy, 1, plate, plate_size, top_type, top_yaw),
        rotation=yaw_to_rotation(top_yaw),
    )

    bricks.extend([base, top])
    return bricks


def generate_simple_multi_brick_stack(rng: random.Random, n_blocks: int) -> List[BrickSpec]:
    assert 3 <= n_blocks <= 5
    plate = DEFAULT_ASSEMBLY_PLATE_CENTER
    plate_size = ASSEMBLY_PLATE_SIZE
    bricks: List[BrickSpec] = []

    gx, gy = 1, 1
    for i in range(n_blocks):
        brick_type = random_brick_type(rng)
        yaw = random_yaw(rng)
        brick = BrickSpec(
            name=make_brick_name(brick_type, i + 1),
            type=brick_type,
            color=random_color(rng),
            pos=grid_to_metric(gx, gy, i, plate, plate_size, brick_type, yaw),
            rotation=yaw_to_rotation(yaw),
        )
        bricks.append(brick)
    return bricks


def generate_simple_shape_assembly(rng: random.Random, n_blocks: int) -> List[BrickSpec]:
    """
    生成更像“简单形状装配”的任务:
    - 大部分砖块在 ground layer (z=0)
    - 少量砖块可在 z=1
    - 整体连通
    - 比纯 stack 更强调平面形状
    """
    assert 3 <= n_blocks <= 12

    plate = DEFAULT_ASSEMBLY_PLATE_CENTER
    plate_size = ASSEMBLY_PLATE_SIZE
    grid_w, grid_h = plate_grid_capacity(plate_size)

    # 至少 70% 放在 ground layer
    n_ground = max(2, math.ceil(n_blocks * 0.7))
    n_upper = n_blocks - n_ground

    # 1) 先生成 ground layer 连通简单形状
    ground_layout = generate_connected_ground_layout(rng, n_ground, grid_w, grid_h)

    occupied: Dict[Tuple[int, int, int], str] = {}
    placements: List[Tuple[int, int, int, str, int]] = []

    # 填入 ground layer
    for idx, (gx, gy, brick_type, yaw) in enumerate(ground_layout, start=1):
        placements.append((gx, gy, 0, brick_type, yaw))
        add_to_occupied(gx, gy, 0, brick_type, yaw, occupied, make_brick_name(brick_type, idx))

    # 2) 再少量加上层块，但必须压在已有 ground 或上层结构上
    attempts = 0
    idx = len(placements) + 1

    while idx <= n_blocks and attempts < 3000:
        attempts += 1

        brick_type = random_brick_type(rng)
        yaw = random_yaw(rng)
        gz = 1   # 第三类只允许少量一层上叠，不往更高层长

        base_gx, base_gy, _, base_type, base_yaw = rng.choice(placements)
        gx = base_gx + rng.choice([-1, 0, 1])
        gy = base_gy + rng.choice([-1, 0, 1])

        if not placeable(gx, gy, gz, brick_type, yaw, occupied, grid_w, grid_h):
            continue

        tmp_pos = grid_to_metric(gx, gy, gz, plate, plate_size, brick_type, yaw)
        tmp_brick = BrickSpec(
            name=make_brick_name(brick_type, idx),
            type=brick_type,
            color=random_color(rng),
            pos=tmp_pos,
            rotation=yaw_to_rotation(yaw),
        )

        if not within_plate_xy(
            center_xy=(tmp_brick.pos[0], tmp_brick.pos[1]),
            dims_xy=tmp_brick.dims_xy(),
            plate_center=plate,
            plate_size=plate_size,
            margin=0.0,
        ):
            continue

        # 与已有结构连通
        connected = False
        for p_idx, (pgx, pgy, pgz, ptype, pyaw) in enumerate(placements, start=1):
            existing = BrickSpec(
                name=make_brick_name(ptype, p_idx),
                type=ptype,
                color="red",
                pos=grid_to_metric(pgx, pgy, pgz, plate, plate_size, ptype, pyaw),
                rotation=yaw_to_rotation(pyaw),
            )
            if bricks_touch_or_support(existing, tmp_brick):
                connected = True
                break

        if not connected:
            continue

        placements.append((gx, gy, gz, brick_type, yaw))
        add_to_occupied(gx, gy, gz, brick_type, yaw, occupied, tmp_brick.name)
        idx += 1

    if len(placements) != n_blocks:
        raise RuntimeError("Failed to generate connected simple_shape_assembly instance.")

    # 3) 转成 BrickSpec
    bricks: List[BrickSpec] = []
    for i, (gx, gy, gz, brick_type, yaw) in enumerate(placements, start=1):
        bricks.append(
            BrickSpec(
                name=make_brick_name(brick_type, i),
                type=brick_type,
                color=random_color(rng),
                pos=grid_to_metric(gx, gy, gz, plate, plate_size, brick_type, yaw),
                rotation=yaw_to_rotation(yaw),
            )
        )

    # 4) 最后兜底检查：必须连通
    if not verify_goal_connected(bricks):
        raise RuntimeError("Generated simple_shape_assembly is not connected.")

    return bricks

def generate_balanced_order_sensitive(rng: random.Random, n_blocks: int) -> List[BrickSpec]:
    """
    用一个连通骨架开始，然后只添加与现有结构连通的砖。
    """
    assert 3 <= n_blocks <= 12

    plate = DEFAULT_ASSEMBLY_PLATE_CENTER
    plate_size = ASSEMBLY_PLATE_SIZE
    grid_w, grid_h = plate_grid_capacity(plate_size)

    occupied: Dict[Tuple[int, int, int], str] = {}
    placements: List[Tuple[int, int, int, str, int]] = []

    skeleton = [
        ("brick_2x2", 0, 0, 1, 0),   # left support
        ("brick_2x2", 0, 4, 1, 0),   # right support
        ("brick_4x2", 0, 1, 1, 1),   # beam
    ]

    for idx, (brick_type, yaw, gx, gy, gz) in enumerate(skeleton, start=1):
        if not placeable(gx, gy, gz, brick_type, yaw, occupied, grid_w, grid_h):
            raise RuntimeError("Order-sensitive skeleton does not fit inside assembly plate.")

        pos = grid_to_metric(gx, gy, gz, plate, plate_size, brick_type, yaw)
        tmp = BrickSpec(
            name=make_brick_name(brick_type, idx),
            type=brick_type,
            color=random_color(rng),
            pos=pos,
            rotation=yaw_to_rotation(yaw),
        )
        if not within_plate_xy((tmp.pos[0], tmp.pos[1]), tmp.dims_xy(), plate, plate_size):
            raise RuntimeError("Order-sensitive skeleton exceeds assembly plate.")

        placements.append((gx, gy, gz, brick_type, yaw))
        add_to_occupied(gx, gy, gz, brick_type, yaw, occupied, tmp.name)

    idx = 4
    attempts = 0
    while idx <= n_blocks and attempts < 4000:
        attempts += 1

        brick_type = random_brick_type(rng)
        yaw = random_yaw(rng)

        base_cell = rng.choice(list(occupied.keys()))
        gx = base_cell[0] + rng.choice([-2, -1, 0, 1, 2])
        gy = base_cell[1] + rng.choice([-1, 0, 1, 2])
        gz = rng.choice([0, 1, 2])

        if not placeable(gx, gy, gz, brick_type, yaw, occupied, grid_w, grid_h):
            continue

        pos = grid_to_metric(gx, gy, gz, plate, plate_size, brick_type, yaw)
        tmp = BrickSpec(
            name=make_brick_name(brick_type, idx),
            type=brick_type,
            color=random_color(rng),
            pos=pos,
            rotation=yaw_to_rotation(yaw),
        )

        if not within_plate_xy((tmp.pos[0], tmp.pos[1]), tmp.dims_xy(), plate, plate_size):
            continue

        connected = False
        for p_idx, (pgx, pgy, pgz, ptype, pyaw) in enumerate(placements, start=1):
            existing = BrickSpec(
                name=make_brick_name(ptype, p_idx),
                type=ptype,
                color="red",
                pos=grid_to_metric(pgx, pgy, pgz, plate, plate_size, ptype, pyaw),
                rotation=yaw_to_rotation(pyaw),
            )
            if bricks_touch_or_support(existing, tmp):
                connected = True
                break

        if not connected:
            continue

        placements.append((gx, gy, gz, brick_type, yaw))
        add_to_occupied(gx, gy, gz, brick_type, yaw, occupied, tmp.name)
        idx += 1

    if len(placements) != n_blocks:
        raise RuntimeError("Failed to generate connected balanced_order_sensitive instance within assembly plate.")

    bricks: List[BrickSpec] = []
    for i, (gx, gy, gz, brick_type, yaw) in enumerate(placements, start=1):
        bricks.append(
            BrickSpec(
                name=make_brick_name(brick_type, i),
                type=brick_type,
                color=random_color(rng),
                pos=grid_to_metric(gx, gy, gz, plate, plate_size, brick_type, yaw),
                rotation=yaw_to_rotation(yaw),
            )
        )
    return bricks


# =========================
# 初始场景生成
# =========================

def sample_scene_init(
    goal_bricks: List[BrickSpec],
    rng: random.Random,
    min_distance_m: float,
    parts_plate_center: Tuple[float, float, float] = DEFAULT_PARTS_PLATE_CENTER,
    parts_plate_size: Tuple[float, float] = PARTS_PLATE_SIZE,
) -> List[SceneBrick]:
    scene_bricks: List[SceneBrick] = []

    half_w = parts_plate_size[0] / 2.0
    half_h = parts_plate_size[1] / 2.0

    for gb in goal_bricks:
        ok = False
        for _ in range(1000):
            yaw_deg = rng.choice([0, 90, 180, 270])
            cand = SceneBrick(
                name=gb.name,
                type=gb.type,
                color=gb.color,
                pos=[
                    round(rng.uniform(parts_plate_center[0] - half_w, parts_plate_center[0] + half_w), 4),
                    round(rng.uniform(parts_plate_center[1] - half_h, parts_plate_center[1] + half_h), 4),
                    round(parts_plate_center[2], 4),
                ],
                rotation=yaw_to_rotation(yaw_deg),
            )

            if not within_plate_xy(
                center_xy=(cand.pos[0], cand.pos[1]),
                dims_xy=cand.dims_xy(),
                plate_center=parts_plate_center,
                plate_size=parts_plate_size,
                margin=0.0,
            ):
                continue

            collision = False
            for sb in scene_bricks:
                if not rect_gap_ok(
                    (cand.pos[0], cand.pos[1]), cand.dims_xy(),
                    (sb.pos[0], sb.pos[1]), sb.dims_xy(),
                    min_distance_m
                ):
                    collision = True
                    break

            if collision:
                continue

            scene_bricks.append(cand)
            ok = True
            break

        if not ok:
            raise RuntimeError(
                f"Failed to sample valid initial arrangement for {gb.name}. "
                f"Try smaller min_distance or larger parts plate."
            )

    return scene_bricks


# =========================
# planner 占位
# =========================

def planner_check_placeholder(goal_bricks: List[BrickSpec]) -> bool:
    _ = goal_bricks
    return True


# =========================
# YAML 输出
# =========================

def build_final_product_yaml(goal_bricks: List[BrickSpec]) -> Dict:
    return {
        "blocks": [
            {
                "name": b.name,
                "type": b.type,
                "color": b.color,
                "pos": b.pos,
                "rotation": [round(v, 4) for v in b.rotation],
            }
            for b in goal_bricks
        ]
    }


def build_scene_init_yaml(scene_bricks: List[SceneBrick], min_distance_m: float) -> Dict:
    return {
        "min_distance_m": round(min_distance_m, 4),
        "parts_plate": {
            "center": list(DEFAULT_PARTS_PLATE_CENTER),
            "size": list(PARTS_PLATE_SIZE),
        },
        "assembly_plate": {
            "center": list(DEFAULT_ASSEMBLY_PLATE_CENTER),
            "size": list(ASSEMBLY_PLATE_SIZE),
        },
        "blocks": [
            {
                "name": b.name,
                "type": b.type,
                "color": b.color,
                "pos": b.pos,
                "rotation": [round(v, 4) for v in b.rotation],
            }
            for b in scene_bricks
        ]
    }


def build_metadata_yaml(
    instance_id: str,
    task_class: str,
    seed: int,
    num_blocks: int,
    verified: bool,
    planner_checked: bool,
) -> Dict:
    return {
        "instance_id": instance_id,
        "task_class": task_class,
        "seed": seed,
        "num_blocks": num_blocks,
        "verified": verified,
        "planner_checked": planner_checked,
    }


# =========================
# 总入口
# =========================

def generate_goal_by_class(task_class: str, rng: random.Random) -> List[BrickSpec]:
    if task_class == "two_brick_stack":
        return generate_two_brick_stack(rng)

    if task_class == "simple_multi_brick_stack":
        n = rng.randint(3, 5)
        return generate_simple_multi_brick_stack(rng, n)

    if task_class == "simple_shape_assembly":
        n = rng.randint(3, 12)
        return generate_simple_shape_assembly(rng, n)

    if task_class == "balanced_order_sensitive":
        n = rng.randint(3, 12)
        return generate_balanced_order_sensitive(rng, n)

    raise ValueError(f"Unknown task class: {task_class}")


def generate_instance(
    output_root: str,
    task_class: str,
    instance_idx: int,
    seed: int,
    min_distance_cm: float,
    use_planner: bool,
) -> None:
    rng = random.Random(seed)
    instance_id = f"{task_class}_{instance_idx:03d}"

    goal_bricks = generate_goal_by_class(task_class, rng)

    if not verify_goal_basic(goal_bricks):
        raise RuntimeError(f"Goal basic verification failed for {instance_id}")

    if not verify_goal_within_assembly_plate(goal_bricks):
        raise RuntimeError(f"Goal exceeds assembly plate for {instance_id}")

    if not verify_goal_connected(goal_bricks):
        raise RuntimeError(f"Goal is not connected for {instance_id}")

    if use_planner:
        if not planner_check_placeholder(goal_bricks):
            raise RuntimeError(f"Planner rejected {instance_id}")

    min_distance_m = min_distance_cm / 100.0
    scene_bricks = sample_scene_init(goal_bricks, rng, min_distance_m)

    if not verify_scene_init(scene_bricks, min_distance_m):
        raise RuntimeError(f"Scene init verification failed for {instance_id}")

    instance_dir = os.path.join(output_root, task_class, instance_id)
    ensure_dir(instance_dir)

    save_yaml(build_final_product_yaml(goal_bricks), os.path.join(instance_dir, "final_product.yaml"))
    save_yaml(build_scene_init_yaml(scene_bricks, min_distance_m), os.path.join(instance_dir, "scene_init.yaml"))
    save_yaml(
        build_metadata_yaml(
            instance_id=instance_id,
            task_class=task_class,
            seed=seed,
            num_blocks=len(goal_bricks),
            verified=True,
            planner_checked=use_planner,
        ),
        os.path.join(instance_dir, "metadata.yaml"),
    )

    print(f"[OK] Generated {instance_id} -> {instance_dir}")


# =========================
# CLI
# =========================

def parse_args():
    parser = argparse.ArgumentParser(description="LEGO Duplo benchmark generator")
    parser.add_argument(
        "--task_class",
        type=str,
        required=True,
        choices=[
            "two_brick_stack",
            "simple_multi_brick_stack",
            "simple_shape_assembly",
            "balanced_order_sensitive",
        ],
        help="Task class to generate",
    )
    parser.add_argument("--num_samples", type=int, default=10, help="Number of instances")
    parser.add_argument("--start_seed", type=int, default=0, help="Starting seed")
    parser.add_argument("--min_distance_cm", type=float, default=3.0, help="Minimum initial part clearance")
    parser.add_argument("--use_planner", action="store_true", help="Optional planner validation")
    parser.add_argument("--output_dir", type=str, default="benchmark", help="Output directory")
    return parser.parse_args()


def main():
    args = parse_args()
    ensure_dir(args.output_dir)

    generated = 0
    current_seed = args.start_seed

    while generated < args.num_samples:
        try:
            generate_instance(
                output_root=args.output_dir,
                task_class=args.task_class,
                instance_idx=generated + 1,
                seed=current_seed,
                min_distance_cm=args.min_distance_cm,
                use_planner=args.use_planner,
            )
            generated += 1
        except Exception as e:
            print(f"[SKIP] seed={current_seed}: {e}")
        current_seed += 1

def generate_connected_ground_layout(
    rng: random.Random,
    n_ground: int,
    grid_w: int,
    grid_h: int,
) -> List[Tuple[int, int, str, int]]:
    """
    生成一个 ground layer 上的连通简单形状。
    返回: [(gx, gy, brick_type, yaw), ...]
    特点:
    - 全部在 z=0
    - 连通
    - 更偏平面形状
    - 避免退化成单一竖直柱
    """
    assert n_ground >= 2

    placements: List[Tuple[int, int, str, int]] = []
    occupied_xy: Set[Tuple[int, int]] = set()

    # 第一个块放在中间偏左，留出扩展空间
    first_type = random_brick_type(rng)
    first_yaw = random_yaw(rng)
    sx, sy = type_to_grid_size(first_type, first_yaw)

    gx0 = max(0, min(1, grid_w // 2 - sx))
    gy0 = max(0, min(1, grid_h // 2 - sy))
    placements.append((gx0, gy0, first_type, first_yaw))
    for cx, cy in footprint_cells(gx0, gy0, first_type, first_yaw):
        occupied_xy.add((cx, cy))

    attempts = 0
    while len(placements) < n_ground and attempts < 3000:
        attempts += 1

        brick_type = random_brick_type(rng)
        yaw = random_yaw(rng)
        sx, sy = type_to_grid_size(brick_type, yaw)

        # 从已有块附近扩展，但更鼓励平面扩张
        base_gx, base_gy, _, _ = rng.choice(placements)

        # 平面形状更明显：在 x/y 方向偏移更常见，避免总是原地上叠
        gx = base_gx + rng.choice([-4, -2, -1, 0, 1, 2, 4])
        gy = base_gy + rng.choice([-4, -2, -1, 0, 1, 2, 4])

        # 边界检查
        if gx < 0 or gy < 0 or gx + sx > grid_w or gy + sy > grid_h:
            continue

        new_cells = footprint_cells(gx, gy, brick_type, yaw)

        # 不允许 ground layer 重叠
        if any((cx, cy) in occupied_xy for cx, cy in new_cells):
            continue

        # 至少和已有 ground 结构有接触或相邻
        # 用 4-neighborhood 的“贴边/相邻”来判断
        connected = False
        for cx, cy in new_cells:
            neighbors = [(cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)]
            if any(n in occupied_xy for n in neighbors):
                connected = True
                break
        if not connected:
            continue

        placements.append((gx, gy, brick_type, yaw))
        for cx, cy in new_cells:
            occupied_xy.add((cx, cy))

    if len(placements) != n_ground:
        raise RuntimeError("Failed to generate connected ground layout.")

    # 避免退化成“几乎都在同一列/同一行”
    xs = [gx for gx, _, _, _ in placements]
    ys = [gy for _, gy, _, _ in placements]
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        raise RuntimeError("Generated ground layout is too degenerate (not shape-like enough).")

    return placements


if __name__ == "__main__":
    main()