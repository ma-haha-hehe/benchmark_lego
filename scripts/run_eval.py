from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# 可选：如果你已经有 verifier.py
try:
    from verifier import verify_instance_dir
except Exception:
    verify_instance_dir = None


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
class InstanceSpec:
    instance_id: str
    task_class: str
    seed: int
    num_blocks: int
    planner_checked: bool
    verified: bool
    final_product: List[Brick]
    scene_init: List[Brick]
    min_distance_m: float
    parts_plate: Dict
    assembly_plate: Dict
    instance_dir: str


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


# =========================================================
# YAML 读取
# =========================================================

def load_yaml(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        raise ValueError(f"Empty yaml file: {path}")
    return data


def parse_bricks(blocks: List[Dict]) -> List[Brick]:
    out = []
    for b in blocks:
        out.append(
            Brick(
                name=b["name"],
                type=b["type"],
                color=b["color"],
                pos=list(b["pos"]),
                rotation=list(b["rotation"]),
            )
        )
    return out


def load_instance(instance_dir: str) -> InstanceSpec:
    final_product_path = os.path.join(instance_dir, "final_product.yaml")
    scene_init_path = os.path.join(instance_dir, "scene_init.yaml")
    metadata_path = os.path.join(instance_dir, "metadata.yaml")

    final_product = load_yaml(final_product_path)
    scene_init = load_yaml(scene_init_path)
    metadata = load_yaml(metadata_path)

    return InstanceSpec(
        instance_id=metadata["instance_id"],
        task_class=metadata["task_class"],
        seed=int(metadata["seed"]),
        num_blocks=int(metadata["num_blocks"]),
        planner_checked=bool(metadata["planner_checked"]),
        verified=bool(metadata["verified"]),
        final_product=parse_bricks(final_product["blocks"]),
        scene_init=parse_bricks(scene_init["blocks"]),
        min_distance_m=float(scene_init["min_distance_m"]),
        parts_plate=scene_init["parts_plate"],
        assembly_plate=scene_init["assembly_plate"],
        instance_dir=instance_dir,
    )


def collect_instance_dirs(
    benchmark_root: str,
    task_class: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[str]:
    root = Path(benchmark_root)
    if not root.exists():
        raise FileNotFoundError(f"benchmark root not found: {benchmark_root}")

    instance_dirs: List[str] = []

    if task_class is not None:
        class_dir = root / task_class
        if not class_dir.exists():
            raise FileNotFoundError(f"task class dir not found: {class_dir}")
        for child in sorted(class_dir.iterdir()):
            if child.is_dir():
                instance_dirs.append(str(child))
    else:
        for class_dir in sorted(root.iterdir()):
            if not class_dir.is_dir():
                continue
            for child in sorted(class_dir.iterdir()):
                if child.is_dir():
                    instance_dirs.append(str(child))

    if limit is not None:
        instance_dirs = instance_dirs[:limit]

    return instance_dirs


# =========================================================
# 目标判定与进度统计
# =========================================================

from geometry import STUD, BRICK_H


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


def same_type_and_color(a: Brick, b: Brick) -> bool:
    return a.type == b.type and a.color == b.color


def pose_close(a: Brick, b: Brick, pos_tol: float = 0.015, yaw_tol_deg: int = 10) -> bool:
    if not same_type_and_color(a, b):
        return False

    dx = a.pos[0] - b.pos[0]
    dy = a.pos[1] - b.pos[1]
    dz = a.pos[2] - b.pos[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist > pos_tol:
        return False

    ya = yaw_deg_from_rad(a.rotation[2])
    yb = yaw_deg_from_rad(b.rotation[2])
    diff = min((ya - yb) % 180, (yb - ya) % 180)
    if diff > yaw_tol_deg:
        return False

    return True


def greedy_match_completed_blocks(
    goal_bricks: List[Brick],
    current_bricks: List[Brick],
    pos_tol: float = 0.015,
    yaw_tol_deg: int = 10,
) -> int:
    """
    简单 greedy matching:
    统计当前场景里有多少 brick 已经和 goal 对齐。
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


def classify_failure_type(
    success: bool,
    completed_blocks: int,
    total_blocks: int,
    failed_grasp_attempts: int,
    notes: str = "",
) -> str:
    if success:
        return "none"

    if failed_grasp_attempts > 0 and completed_blocks == 0:
        return "grasp"

    if completed_blocks == 0:
        return "perception_or_grasp"

    if 0 < completed_blocks < total_blocks:
        if "insertion" in notes.lower():
            return "insertion"
        return "partial_assembly"

    return "unknown"


# =========================================================
# 环境适配器
# =========================================================

class BenchmarkEnvAdapter:
    """
    这是你要接你自己 LIBERO / MuJoCo / Panda 环境的地方。
    下面这些函数我都给你留好了。
    """

    def __init__(self, render: bool = False):
        self.render_enabled = render
        self.num_env_steps = 0
        self.failed_grasp_attempts = 0

    def reset_with_instance(self, spec: InstanceSpec):
        """
        TODO:
        这里读取 spec.scene_init，把初始积木摆到 parts_plate。
        同时清空 assembly plate。
        返回初始 observation（如果你需要）。
        """
        raise NotImplementedError

    def render(self):
        """
        TODO:
        如果你有 GUI / offscreen 渲染，可以在这里调用。
        """
        return None

    def get_current_world_state(self) -> List[Brick]:
        """
        TODO:
        返回当前场景中的积木状态，格式和 Brick 一致。
        这个很关键，用于统计 completed_blocks。
        """
        raise NotImplementedError

    def step_env(self, action) -> Tuple[Optional[dict], bool, dict]:
        """
        TODO:
        执行动作，返回:
          obs, done, info
        这里的 done 是“环境 episode 是否结束”，
        不是最终 benchmark success。
        """
        raise NotImplementedError

    def close(self):
        return None


# =========================================================
# 方法适配器
# =========================================================

class MethodRunner:
    """
    方法统一接口：
    - setup_instance: 可做规划、初始化
    - act: 每一步输出一个动作
    """

    def __init__(self, method_name: str):
        self.method_name = method_name
        self.planning_time_sec = 0.0
        self.notes = ""

    def setup_instance(self, spec: InstanceSpec, env: BenchmarkEnvAdapter):
        """
        TODO:
        这里做每个 instance 开始前的准备，比如：
        - Ours: 跑 planner，得到 assembly sequence
        - pi0: 初始化 policy client / prompt
        """
        return None

    def act(self, obs, spec: InstanceSpec, env: BenchmarkEnvAdapter):
        """
        TODO:
        返回一个动作。
        """
        raise NotImplementedError


class DryRunMethod(MethodRunner):
    """
    用于只测试 benchmark 读写和 logger，
    不接真实策略。
    """
    def __init__(self):
        super().__init__("dry_run")

    def act(self, obs, spec: InstanceSpec, env: BenchmarkEnvAdapter):
        return None


class OursMethod(MethodRunner):
    def __init__(self):
        super().__init__("ours")

    def setup_instance(self, spec: InstanceSpec, env: BenchmarkEnvAdapter):
        t0 = time.perf_counter()
        # TODO:
        # 这里接你的 planner
        # 例如:
        # self.plan = run_abd_planner(spec.final_product)
        # self.plan_cursor = 0
        self.planning_time_sec = time.perf_counter() - t0

    def act(self, obs, spec: InstanceSpec, env: BenchmarkEnvAdapter):
        # TODO:
        # 根据当前 plan / perception / execution state machine 输出 action
        raise NotImplementedError("Please connect your planner / execution pipeline here.")


class PiMethod(MethodRunner):
    def __init__(self):
        super().__init__("pi0")

    def setup_instance(self, spec: InstanceSpec, env: BenchmarkEnvAdapter):
        t0 = time.perf_counter()
        # pi / VLA 一般没有显式 planner
        # 这里保留 0 或很小值
        self.planning_time_sec = time.perf_counter() - t0

        # TODO:
        # 比如:
        # self.prompt = build_prompt_from_goal(spec.final_product)
        # self.policy_client = ...
        # 如果你要接 websocket policy server，这里初始化
        return None

    def act(self, obs, spec: InstanceSpec, env: BenchmarkEnvAdapter):
        # TODO:
        # 把 observation + prompt 喂给 pi policy
        raise NotImplementedError("Please connect your pi/VLA policy here.")


# =========================================================
# 单个 episode 评测
# =========================================================

def evaluate_one_instance(
    spec: InstanceSpec,
    env: BenchmarkEnvAdapter,
    method: MethodRunner,
    max_steps: int,
    pos_tol: float,
    yaw_tol_deg: int,
) -> EvalMetrics:
    obs = env.reset_with_instance(spec)

    # setup / planning
    method.setup_instance(spec, env)

    t0 = time.perf_counter()
    failure_notes = ""

    success = False
    completed_blocks = 0
    current_state: List[Brick] = []

    for step_idx in range(max_steps):
        env.num_env_steps += 1

        if env.render_enabled:
            env.render()

        action = method.act(obs, spec, env)
        obs, done, info = env.step_env(action)

        if info is None:
            info = {}

        # 你可以在 env.step_env 里记录 grasp failure 次数
        if "failed_grasp_attempts" in info:
            env.failed_grasp_attempts = int(info["failed_grasp_attempts"])

        if "notes" in info and isinstance(info["notes"], str):
            failure_notes = info["notes"]

        current_state = env.get_current_world_state()
        completed_blocks = greedy_match_completed_blocks(
            spec.final_product,
            current_state,
            pos_tol=pos_tol,
            yaw_tol_deg=yaw_tol_deg,
        )

        if completed_blocks == len(spec.final_product):
            success = True
            break

        if done:
            break

    execution_time_sec = time.perf_counter() - t0
    progress_ratio = completed_blocks / max(1, len(spec.final_product))

    failure_type = classify_failure_type(
        success=success,
        completed_blocks=completed_blocks,
        total_blocks=len(spec.final_product),
        failed_grasp_attempts=env.failed_grasp_attempts,
        notes=failure_notes or method.notes,
    )

    return EvalMetrics(
        method=method.method_name,
        instance_id=spec.instance_id,
        task_class=spec.task_class,
        seed=spec.seed,
        success=int(success),
        execution_time_sec=round(execution_time_sec, 4),
        planning_time_sec=round(method.planning_time_sec, 4),
        total_blocks=len(spec.final_product),
        completed_blocks=completed_blocks,
        progress_ratio=round(progress_ratio, 4),
        num_env_steps=env.num_env_steps,
        failed_grasp_attempts=env.failed_grasp_attempts,
        failure_type=failure_type,
        notes=(failure_notes or method.notes),
    )


# =========================================================
# CSV 输出
# =========================================================

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


def append_metrics_to_csv(csv_path: str, metrics: EvalMetrics):
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(asdict(metrics))


# =========================================================
# env / method 工厂
# =========================================================

def build_env(render: bool) -> BenchmarkEnvAdapter:
    """
    TODO:
    你在这里替换成你自己的环境类。
    例如:
        return LiberoLegoEnvAdapter(render=render)
    """
    return BenchmarkEnvAdapter(render=render)


def build_method(method_name: str) -> MethodRunner:
    if method_name == "dry_run":
        return DryRunMethod()
    elif method_name == "ours":
        return OursMethod()
    elif method_name == "pi0":
        return PiMethod()
    else:
        raise ValueError(f"Unknown method: {method_name}")


# =========================================================
# 主流程
# =========================================================

def run_eval(
    benchmark_root: str,
    output_csv: str,
    method_name: str,
    task_class: Optional[str],
    max_instances: Optional[int],
    max_steps: int,
    render: bool,
    use_verifier: bool,
    pos_tol: float,
    yaw_tol_deg: int,
):
    instance_dirs = collect_instance_dirs(
        benchmark_root=benchmark_root,
        task_class=task_class,
        limit=max_instances,
    )

    print(f"[INFO] Found {len(instance_dirs)} instance(s).")

    passed = 0
    failed = 0

    for instance_dir in instance_dirs:
        if use_verifier:
            if verify_instance_dir is None:
                raise RuntimeError("verifier.py is not available, but --use_verifier was set.")
            ok, errors = verify_instance_dir(instance_dir, use_planner=False)
            if not ok:
                print(f"[SKIP] verification failed: {instance_dir}")
                for e in errors:
                    print(f"  - {e}")
                failed += 1
                continue

        spec = load_instance(instance_dir)

        env = build_env(render=render)
        method = build_method(method_name)

        try:
            metrics = evaluate_one_instance(
                spec=spec,
                env=env,
                method=method,
                max_steps=max_steps,
                pos_tol=pos_tol,
                yaw_tol_deg=yaw_tol_deg,
            )
            append_metrics_to_csv(output_csv, metrics)

            status = "PASS" if metrics.success == 1 else "FAIL"
            print(
                f"[{status}] {spec.instance_id} | "
                f"completed={metrics.completed_blocks}/{metrics.total_blocks} | "
                f"time={metrics.execution_time_sec:.2f}s | "
                f"plan={metrics.planning_time_sec:.2f}s | "
                f"grasps_failed={metrics.failed_grasp_attempts}"
            )
            passed += 1

        except Exception as e:
            failed += 1
            print(f"[ERROR] {spec.instance_id}: {e}")

        finally:
            env.close()

    print(f"\n[SUMMARY] processed={passed + failed}, ok={passed}, failed_or_skipped={failed}")
    print(f"[SUMMARY] csv saved to: {output_csv}")


# =========================================================
# CLI
# =========================================================

def parse_args():
    parser = argparse.ArgumentParser(description="Run evaluation on LEGO Duplo benchmark instances")
    parser.add_argument("--benchmark_root", type=str, required=True, help="Path to benchmark root")
    parser.add_argument("--output_csv", type=str, default="eval_results.csv", help="CSV output path")
    parser.add_argument("--method", type=str, required=True, choices=["ours", "pi0", "dry_run"])
    parser.add_argument("--task_class", type=str, default=None, help="Optional task class filter")
    parser.add_argument("--max_instances", type=int, default=None, help="Optional max number of instances")
    parser.add_argument("--max_steps", type=int, default=200, help="Max env steps per instance")
    parser.add_argument("--render", action="store_true", help="Enable rendering")
    parser.add_argument("--use_verifier", action="store_true", help="Run verifier before evaluation")
    parser.add_argument("--pos_tol", type=float, default=0.015, help="Position tolerance for success check")
    parser.add_argument("--yaw_tol_deg", type=int, default=10, help="Yaw tolerance in degrees")
    return parser.parse_args()


def main():
    args = parse_args()
    run_eval(
        benchmark_root=args.benchmark_root,
        output_csv=args.output_csv,
        method_name=args.method,
        task_class=args.task_class,
        max_instances=args.max_instances,
        max_steps=args.max_steps,
        render=args.render,
        use_verifier=args.use_verifier,
        pos_tol=args.pos_tol,
        yaw_tol_deg=args.yaw_tol_deg,
    )


if __name__ == "__main__":
    main()
