from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple, Set, Optional

import yaml


# =========================
# 常量
# =========================

STUD = 0.032
BRICK_H = 0.020
VALID_TYPES = {"brick_2x2", "brick_4x2"}
VALID_COLORS = {"red", "blue", "yellow", "green"}


# =========================
# 数据结构
# =========================

@dataclass
class Brick:
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

    def bbox_xy(self) -> Tuple[float, float, float, float]:
        dx, dy = self.dims_xy()
        x, y = self.pos[0], self.pos[1]
        return (x - dx / 2.0, x + dx / 2.0, y - dy / 2.0, y + dy / 2.0)


# =========================
# YAML 读取
# =========================

def load_yaml(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        raise ValueError(f"Empty yaml file: {path}")
    return data


def parse_bricks(blocks: List[Dict]) -> List[Brick]:
    bricks = []
    for b in blocks:
        bricks.append(
            Brick(
                name=b["name"],
                type=b["type"],
                color=b["color"],
                pos=list(b["pos"]),
                rotation=list(b["rotation"]),
            )
        )
    return bricks


# =========================
# 基础几何工具
# =========================

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


def interval_overlap_len(a1: float, a2: float, b1: float, b2: float) -> float:
    return max(0.0, min(a2, b2) - max(a1, b1))


def bricks_touch_or_support(a: Brick, b: Brick, eps: float = 1e-6) -> bool:
    ax1, ax2, ay1, ay2 = a.bbox_xy()
    bx1, bx2, by1, by2 = b.bbox_xy()

    az = a.pos[2]
    bz = b.pos[2]

    overlap_x = interval_overlap_len(ax1, ax2, bx1, bx2)
    overlap_y = interval_overlap_len(ay1, ay2, by1, by2)

    # 同层 footprint 有正面积重叠
    if abs(az - bz) < eps:
        if overlap_x > eps and overlap_y > eps:
            return True

    # 上下层相差一个 brick height 且 footprint 有正面积重叠
    if abs(abs(az - bz) - BRICK_H) < eps:
        if overlap_x > eps and overlap_y > eps:
            return True

    return False


# =========================
# 验证函数
# =========================

def verify_blocks_basic(bricks: List[Brick]) -> List[str]:
    errors = []
    seen_names = set()

    for i, b in enumerate(bricks):
        if b.name in seen_names:
            errors.append(f"Duplicate brick name: {b.name}")
        seen_names.add(b.name)

        if b.type not in VALID_TYPES:
            errors.append(f"{b.name}: invalid type {b.type}")

        if b.color not in VALID_COLORS:
            errors.append(f"{b.name}: invalid color {b.color}")

        if len(b.pos) != 3:
            errors.append(f"{b.name}: pos must have length 3")

        if len(b.rotation) != 3:
            errors.append(f"{b.name}: rotation must have length 3")

    return errors


def verify_goal_within_plate(goal_bricks: List[Brick], assembly_plate: Dict) -> List[str]:
    errors = []
    center = tuple(assembly_plate["center"])
    size = tuple(assembly_plate["size"])

    for b in goal_bricks:
        if not within_plate_xy(
            center_xy=(b.pos[0], b.pos[1]),
            dims_xy=b.dims_xy(),
            plate_center=center,
            plate_size=size,
            margin=0.0,
        ):
            errors.append(f"{b.name}: outside assembly plate")

    return errors


def verify_scene_within_plate(scene_bricks: List[Brick], parts_plate: Dict) -> List[str]:
    errors = []
    center = tuple(parts_plate["center"])
    size = tuple(parts_plate["size"])

    for b in scene_bricks:
        if not within_plate_xy(
            center_xy=(b.pos[0], b.pos[1]),
            dims_xy=b.dims_xy(),
            plate_center=center,
            plate_size=size,
            margin=0.0,
        ):
            errors.append(f"{b.name}: outside parts plate")

    return errors


def verify_scene_min_distance(scene_bricks: List[Brick], min_distance_m: float) -> List[str]:
    errors = []
    for i in range(len(scene_bricks)):
        for j in range(i + 1, len(scene_bricks)):
            bi = scene_bricks[i]
            bj = scene_bricks[j]
            if not rect_gap_ok(
                (bi.pos[0], bi.pos[1]), bi.dims_xy(),
                (bj.pos[0], bj.pos[1]), bj.dims_xy(),
                min_distance_m,
            ):
                errors.append(
                    f"Initial scene clearance violation: {bi.name} vs {bj.name}"
                )
    return errors


def verify_goal_connected(goal_bricks: List[Brick]) -> List[str]:
    if not goal_bricks:
        return ["Goal structure is empty"]

    if len(goal_bricks) == 1:
        return []

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

    if len(visited) != len(goal_bricks):
        return [
            f"Goal structure is not connected: connected component size = {len(visited)}, total = {len(goal_bricks)}"
        ]
    return []


def verify_name_type_color_consistency(goal_bricks: List[Brick], scene_bricks: List[Brick]) -> List[str]:
    errors = []

    goal_map = {b.name: b for b in goal_bricks}
    scene_map = {b.name: b for b in scene_bricks}

    if set(goal_map.keys()) != set(scene_map.keys()):
        missing_in_scene = set(goal_map.keys()) - set(scene_map.keys())
        extra_in_scene = set(scene_map.keys()) - set(goal_map.keys())
        if missing_in_scene:
            errors.append(f"Missing in scene_init: {sorted(missing_in_scene)}")
        if extra_in_scene:
            errors.append(f"Extra in scene_init: {sorted(extra_in_scene)}")
        return errors

    for name in goal_map:
        g = goal_map[name]
        s = scene_map[name]
        if g.type != s.type:
            errors.append(f"{name}: type mismatch goal={g.type}, scene={s.type}")
        if g.color != s.color:
            errors.append(f"{name}: color mismatch goal={g.color}, scene={s.color}")

    return errors


def verify_metadata(metadata: Dict, goal_bricks: List[Brick], task_class: str) -> List[str]:
    errors = []

    if metadata.get("task_class") != task_class:
        errors.append(
            f"metadata task_class mismatch: metadata={metadata.get('task_class')} expected={task_class}"
        )

    if metadata.get("num_blocks") != len(goal_bricks):
        errors.append(
            f"metadata num_blocks mismatch: metadata={metadata.get('num_blocks')} actual={len(goal_bricks)}"
        )

    if metadata.get("verified") is not True:
        errors.append("metadata verified is not true")

    return errors


def planner_check_placeholder(goal_bricks: List[Brick]) -> List[str]:
    """
    这里预留给 Wenbo planner。
    现在默认通过。
    如果以后需要，可以改成返回错误列表。
    """
    _ = goal_bricks
    return []


# =========================
# 目录级验证
# =========================

def verify_instance_dir(instance_dir: str, use_planner: bool = False) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    final_product_path = os.path.join(instance_dir, "final_product.yaml")
    scene_init_path = os.path.join(instance_dir, "scene_init.yaml")
    metadata_path = os.path.join(instance_dir, "metadata.yaml")

    for p in [final_product_path, scene_init_path, metadata_path]:
        if not os.path.exists(p):
            errors.append(f"Missing file: {p}")

    if errors:
        return False, errors

    final_product = load_yaml(final_product_path)
    scene_init = load_yaml(scene_init_path)
    metadata = load_yaml(metadata_path)

    if "blocks" not in final_product:
        errors.append("final_product.yaml missing 'blocks'")
        return False, errors

    if "blocks" not in scene_init:
        errors.append("scene_init.yaml missing 'blocks'")
        return False, errors

    if "parts_plate" not in scene_init:
        errors.append("scene_init.yaml missing 'parts_plate'")
        return False, errors

    if "assembly_plate" not in scene_init:
        errors.append("scene_init.yaml missing 'assembly_plate'")
        return False, errors

    if "instance_id" not in metadata:
        errors.append("metadata.yaml missing 'instance_id'")
    if "task_class" not in metadata:
        errors.append("metadata.yaml missing 'task_class'")

    if errors:
        return False, errors

    goal_bricks = parse_bricks(final_product["blocks"])
    scene_bricks = parse_bricks(scene_init["blocks"])
    task_class = metadata["task_class"]

    # 基础检查
    errors.extend(verify_blocks_basic(goal_bricks))
    errors.extend(verify_blocks_basic(scene_bricks))

    # goal 检查
    errors.extend(verify_goal_within_plate(goal_bricks, scene_init["assembly_plate"]))
    errors.extend(verify_goal_connected(goal_bricks))

    # scene 检查
    min_distance_m = float(scene_init.get("min_distance_m", 0.0))
    errors.extend(verify_scene_within_plate(scene_bricks, scene_init["parts_plate"]))
    errors.extend(verify_scene_min_distance(scene_bricks, min_distance_m))

    # 一致性检查
    errors.extend(verify_name_type_color_consistency(goal_bricks, scene_bricks))
    errors.extend(verify_metadata(metadata, goal_bricks, task_class))

    # planner 检查（可选）
    if use_planner:
        errors.extend(planner_check_placeholder(goal_bricks))

    return len(errors) == 0, errors


def verify_benchmark_root(root_dir: str, use_planner: bool = False) -> Tuple[int, int]:
    """
    扫描 benchmark 根目录下所有 instance 目录
    """
    total = 0
    passed = 0

    for task_class in os.listdir(root_dir):
        task_class_dir = os.path.join(root_dir, task_class)
        if not os.path.isdir(task_class_dir):
            continue

        for instance_name in os.listdir(task_class_dir):
            instance_dir = os.path.join(task_class_dir, instance_name)
            if not os.path.isdir(instance_dir):
                continue

            total += 1
            ok, errors = verify_instance_dir(instance_dir, use_planner=use_planner)
            if ok:
                passed += 1
                print(f"[PASS] {instance_dir}")
            else:
                print(f"[FAIL] {instance_dir}")
                for e in errors:
                    print(f"  - {e}")

    return passed, total


# =========================
# CLI
# =========================

def parse_args():
    parser = argparse.ArgumentParser(description="Verifier for LEGO Duplo benchmark instances")
    parser.add_argument(
        "--instance_dir",
        type=str,
        default=None,
        help="Verify a single instance directory"
    )
    parser.add_argument(
        "--benchmark_root",
        type=str,
        default=None,
        help="Verify all instances under benchmark root"
    )
    parser.add_argument(
        "--use_planner",
        action="store_true",
        help="Enable optional planner validation"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.instance_dir is None and args.benchmark_root is None:
        raise ValueError("Please provide either --instance_dir or --benchmark_root")

    if args.instance_dir is not None:
        ok, errors = verify_instance_dir(args.instance_dir, use_planner=args.use_planner)
        if ok:
            print(f"[PASS] {args.instance_dir}")
        else:
            print(f"[FAIL] {args.instance_dir}")
            for e in errors:
                print(f"  - {e}")

    if args.benchmark_root is not None:
        passed, total = verify_benchmark_root(args.benchmark_root, use_planner=args.use_planner)
        print(f"\nSummary: {passed}/{total} instances passed.")


if __name__ == "__main__":
    main()