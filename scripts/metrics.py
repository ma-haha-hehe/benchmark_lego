from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional

import yaml


# =========================================================
# 常量
# =========================================================

STUD = 0.032
BRICK_H = 0.020


# =========================================================
# 数据结构
# =========================================================

@dataclass
class Brick:
    name: str
    type: str
    color: str
    pos: List[float]       # [x, y, z]
    rotation: List[float]  # [roll, pitch, yaw]


@dataclass
class EvalMetrics:
    method: str
    instance_id: str
    task_class: str
    seed: int

    success: int
    execution_time_sec: float
    planning_time_sec: float

    total_blocks: int
    completed_blocks: int
    progress_ratio: float

    num_env_steps: int
    failed_grasp_attempts: int

    failure_type: str
    notes: str = ""


CSV_FIELDS = [
    "method",
    "instance_id",
    "task_class",
    "seed",
    "success",
    "execution_time_sec",
    "planning_time_sec",
    "total_blocks",
    "completed_blocks",
    "progress_ratio",
    "num_env_steps",
    "failed_grasp_attempts",
    "failure_type",
    "notes",
]


# =========================================================
# Brick 工具
# =========================================================

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


def yaw_deg_from_rad(yaw_rad: float) -> int:
    return int(round(math.degrees(yaw_rad))) % 180


def dims_xy(brick_type: str, yaw_rad: float) -> Tuple[float, float]:
    yaw_deg = yaw_deg_from_rad(yaw_rad)

    if brick_type == "brick_2x2":
        dx, dy = 2 * STUD, 2 * STUD
    elif brick_type == "brick_4x2":
        dx, dy = 4 * STUD, 2 * STUD
    else:
        raise ValueError(f"Unknown brick type: {brick_type}")

    if yaw_deg == 90:
        dx, dy = dy, dx
    return dx, dy


# =========================================================
# pose matching
# =========================================================

def same_type_and_color(a: Brick, b: Brick) -> bool:
    return a.type == b.type and a.color == b.color


def pose_distance(a: Brick, b: Brick) -> float:
    dx = a.pos[0] - b.pos[0]
    dy = a.pos[1] - b.pos[1]
    dz = a.pos[2] - b.pos[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def yaw_difference_deg(a: Brick, b: Brick) -> int:
    ya = yaw_deg_from_rad(a.rotation[2])
    yb = yaw_deg_from_rad(b.rotation[2])
    return min((ya - yb) % 180, (yb - ya) % 180)


def pose_close(
    a: Brick,
    b: Brick,
    pos_tol: float = 0.015,
    yaw_tol_deg: int = 10,
) -> bool:
    if not same_type_and_color(a, b):
        return False

    if pose_distance(a, b) > pos_tol:
        return False

    if yaw_difference_deg(a, b) > yaw_tol_deg:
        return False

    return True


# =========================================================
# 进度计算
# =========================================================

def greedy_match_completed_blocks(
    goal_bricks: List[Brick],
    current_bricks: List[Brick],
    pos_tol: float = 0.015,
    yaw_tol_deg: int = 10,
) -> int:
    """
    贪心匹配：
    统计当前 world state 里已经匹配到多少个 goal bricks
    """
    used = set()
    completed = 0

    for g in goal_bricks:
        found = False
        for idx, c in enumerate(current_bricks):
            if idx in used:
                continue
            if pose_close(g, c, pos_tol=pos_tol, yaw_tol_deg=yaw_tol_deg):
                used.add(idx)
                completed += 1
                found = True
                break
        if not found:
            continue

    return completed


def compute_progress_ratio(completed_blocks: int, total_blocks: int) -> float:
    if total_blocks <= 0:
        return 0.0
    return completed_blocks / total_blocks


def is_success(completed_blocks: int, total_blocks: int) -> bool:
    return total_blocks > 0 and completed_blocks == total_blocks


# =========================================================
# failure type
# =========================================================

def classify_failure_type(
    success: bool,
    completed_blocks: int,
    total_blocks: int,
    failed_grasp_attempts: int,
    notes: str = "",
) -> str:
    """
    粗粒度 failure 分类。
    """
    if success:
        return "none"

    notes_lower = notes.lower() if isinstance(notes, str) else ""

    if "perception" in notes_lower:
        return "perception"

    if "transport" in notes_lower:
        return "transport"

    if "collision" in notes_lower:
        return "collision"

    if "insertion" in notes_lower:
        return "insertion"

    if failed_grasp_attempts > 0 and completed_blocks == 0:
        return "grasp"

    if completed_blocks == 0:
        return "perception_or_grasp"

    if 0 < completed_blocks < total_blocks:
        return "partial_assembly"

    return "unknown"


# =========================================================
# EvalMetrics 构建
# =========================================================

def build_eval_metrics(
    method: str,
    instance_id: str,
    task_class: str,
    seed: int,
    execution_time_sec: float,
    planning_time_sec: float,
    total_blocks: int,
    completed_blocks: int,
    num_env_steps: int,
    failed_grasp_attempts: int,
    notes: str = "",
) -> EvalMetrics:
    success_flag = is_success(completed_blocks, total_blocks)
    progress_ratio = compute_progress_ratio(completed_blocks, total_blocks)
    failure_type = classify_failure_type(
        success=success_flag,
        completed_blocks=completed_blocks,
        total_blocks=total_blocks,
        failed_grasp_attempts=failed_grasp_attempts,
        notes=notes,
    )

    return EvalMetrics(
        method=method,
        instance_id=instance_id,
        task_class=task_class,
        seed=seed,
        success=int(success_flag),
        execution_time_sec=round(float(execution_time_sec), 4),
        planning_time_sec=round(float(planning_time_sec), 4),
        total_blocks=int(total_blocks),
        completed_blocks=int(completed_blocks),
        progress_ratio=round(float(progress_ratio), 4),
        num_env_steps=int(num_env_steps),
        failed_grasp_attempts=int(failed_grasp_attempts),
        failure_type=failure_type,
        notes=notes or "",
    )


# =========================================================
# CSV 写入 / 读取
# =========================================================

def append_metrics_to_csv(csv_path: str, metrics: EvalMetrics):
    file_exists = os.path.exists(csv_path)

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(asdict(metrics))


def load_metrics_csv(csv_path: str) -> List[EvalMetrics]:
    results: List[EvalMetrics] = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            results.append(
                EvalMetrics(
                    method=row["method"],
                    instance_id=row["instance_id"],
                    task_class=row["task_class"],
                    seed=int(row["seed"]),
                    success=int(row["success"]),
                    execution_time_sec=float(row["execution_time_sec"]),
                    planning_time_sec=float(row["planning_time_sec"]),
                    total_blocks=int(row["total_blocks"]),
                    completed_blocks=int(row["completed_blocks"]),
                    progress_ratio=float(row["progress_ratio"]),
                    num_env_steps=int(row["num_env_steps"]),
                    failed_grasp_attempts=int(row["failed_grasp_attempts"]),
                    failure_type=row["failure_type"],
                    notes=row.get("notes", ""),
                )
            )
    return results


# =========================================================
# 汇总统计
# =========================================================

def mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def summarize_metrics(metrics_list: List[EvalMetrics]) -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    返回三层结构：
    summary[method][task_class] = {
        num_instances,
        success_rate,
        avg_execution_time_sec,
        avg_planning_time_sec,
        avg_progress_ratio,
        avg_completed_blocks,
        avg_total_blocks,
        avg_num_env_steps,
        avg_failed_grasp_attempts,
    }

    还会额外生成 task_class = "overall"
    """
    grouped: Dict[str, Dict[str, List[EvalMetrics]]] = {}

    for m in metrics_list:
        grouped.setdefault(m.method, {})
        grouped[m.method].setdefault(m.task_class, []).append(m)
        grouped[m.method].setdefault("overall", []).append(m)

    summary: Dict[str, Dict[str, Dict[str, float]]] = {}

    for method, task_map in grouped.items():
        summary[method] = {}
        for task_class, rows in task_map.items():
            summary[method][task_class] = {
                "num_instances": len(rows),
                "success_rate": mean([r.success for r in rows]),
                "avg_execution_time_sec": mean([r.execution_time_sec for r in rows]),
                "avg_planning_time_sec": mean([r.planning_time_sec for r in rows]),
                "avg_progress_ratio": mean([r.progress_ratio for r in rows]),
                "avg_completed_blocks": mean([r.completed_blocks for r in rows]),
                "avg_total_blocks": mean([r.total_blocks for r in rows]),
                "avg_num_env_steps": mean([r.num_env_steps for r in rows]),
                "avg_failed_grasp_attempts": mean([r.failed_grasp_attempts for r in rows]),
            }

    return summary


def print_summary_table(summary: Dict[str, Dict[str, Dict[str, float]]]):
    for method, task_map in summary.items():
        print(f"\n=== Method: {method} ===")
        for task_class, stats in task_map.items():
            print(
                f"{task_class:28s} | "
                f"N={int(stats['num_instances']):3d} | "
                f"success={stats['success_rate']*100:6.2f}% | "
                f"time={stats['avg_execution_time_sec']:7.2f}s | "
                f"plan={stats['avg_planning_time_sec']:7.2f}s | "
                f"progress={stats['avg_progress_ratio']*100:6.2f}% | "
                f"grasp_fail={stats['avg_failed_grasp_attempts']:6.2f}"
            )


# =========================================================
# 直接从 yaml 计算 completed blocks 的帮助函数
# =========================================================

def load_goal_bricks_from_yaml(final_product_yaml_path: str) -> List[Brick]:
    with open(final_product_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return parse_bricks(data["blocks"])


def compute_completed_blocks_from_world_state(
    goal_bricks: List[Brick],
    current_world_state: List[Brick],
    pos_tol: float = 0.015,
    yaw_tol_deg: int = 10,
) -> Tuple[int, float]:
    completed = greedy_match_completed_blocks(
        goal_bricks=goal_bricks,
        current_bricks=current_world_state,
        pos_tol=pos_tol,
        yaw_tol_deg=yaw_tol_deg,
    )
    ratio = compute_progress_ratio(completed, len(goal_bricks))
    return completed, ratio