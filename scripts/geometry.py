"""Shared nominal stud geometry; metres, radians, XY centre and body-bottom Z.

STL coordinates are millimetres. Centre each mesh in XY and scale by 0.001;
the provided meshes have 16 mm stud pitch. BRICK_H is the engaged layer pitch,
not the bounding-box height including studs. This is a static grid model,
not a robot motion or contact-physics validator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

STUD = 0.016
BRICK_H = 0.020
MIN_SUPPORT_RATIO = 0.50
MIN_CLEARANCE_M = 0.03
GRIPPER_CLEARANCE_M = 0.008
GENERATOR_VERSION = 2
TIER2_YAW_POLICY = 'independent_0_90_v1'
SHAPE_POLICY = 'simple_three_layer_row_v1'
TIER4_CENTER_POLICY = 'upper_center_on_or_outside_ground_bbox_v1'
VALID_TYPES = {"brick_2x2", "brick_4x2"}
VALID_COLORS = {"red", "blue", "yellow", "green"}
TASK_CLASSES = ("two_brick_stack", "simple_multi_brick_stack",
                "simple_shape_assembly", "balanced_order_sensitive")
EPS = 1e-8


def grid_size(brick_type: str, yaw_deg: int) -> Tuple[int, int]:
    if brick_type not in VALID_TYPES:
        raise ValueError(f"Unknown brick type: {brick_type}")
    size = (4, 2) if brick_type == "brick_4x2" else (2, 2)
    return size[::-1] if yaw_deg % 180 == 90 else size


def yaw_degrees(yaw: float) -> int:
    return int(round(math.degrees(yaw))) % 360


def dims_xy(brick_type: str, yaw: float) -> Tuple[float, float]:
    sx, sy = grid_size(brick_type, yaw_degrees(yaw))
    return sx * STUD, sy * STUD


@dataclass
class Brick:
    name: str
    type: str
    color: str
    pos: List[float]
    rotation: List[float]

    def yaw_deg(self) -> int:
        return yaw_degrees(self.rotation[2]) % 180

    def dims_xy(self) -> Tuple[float, float]:
        return dims_xy(self.type, self.rotation[2])

    def bbox_xy(self) -> Tuple[float, float, float, float]:
        w, h = self.dims_xy()
        x, y = self.pos[:2]
        return x - w / 2, x + w / 2, y - h / 2, y + h / 2


def overlap_area(a: Brick, b: Brick) -> float:
    x1, x2, y1, y2 = a.bbox_xy()
    u1, u2, v1, v2 = b.bbox_xy()
    return max(0.0, min(x2, u2) - max(x1, u1)) * max(0.0, min(y2, v2) - max(y1, v1))


def within_plate(brick: Brick, plate: dict) -> bool:
    x1, x2, y1, y2 = brick.bbox_xy()
    x, y = plate['center'][:2]
    w, h = plate['size']
    return x1 >= x-w/2-EPS and x2 <= x+w/2+EPS and y1 >= y-h/2-EPS and y2 <= y+h/2+EPS


def rect_distance(a: Brick, b: Brick) -> float:
    """Euclidean minimum distance between axis-aligned footprints."""
    x1, x2, y1, y2 = a.bbox_xy()
    u1, u2, v1, v2 = b.bbox_xy()
    return math.hypot(max(0.0, x1-u2, u1-x2), max(0.0, y1-v2, v1-y2))


def layer(brick: Brick, base_z: float = 0.0) -> int:
    return int(round((brick.pos[2] - base_z) / BRICK_H))


def support_ratio(brick: Brick, below: List[Brick]) -> float:
    """Valid only after checking that below-layer footprints do not overlap."""
    w, h = brick.dims_xy()
    return sum(overlap_area(brick, other) for other in below) / (w*h)


def ground_bbox(bricks: List[Brick], base_z: float = 0.0):
    boxes = [b.bbox_xy() for b in bricks if layer(b, base_z) == 0]
    if not boxes:
        return None
    return min(b[0] for b in boxes), max(b[1] for b in boxes), min(b[2] for b in boxes), max(b[3] for b in boxes)


def has_external_overhang(bricks: List[Brick], base_z: float = 0.0) -> bool:
    bb = ground_bbox(bricks, base_z)
    if bb is None:
        return False
    for brick in bricks:
        if layer(brick, base_z) <= 0:
            continue
        x1, x2, y1, y2 = brick.bbox_xy()
        if x1 < bb[0]-EPS or x2 > bb[1]+EPS or y1 < bb[2]-EPS or y2 > bb[3]+EPS:
            return True
    return False


def center_boundary_margin(brick: Brick, ground_bounds) -> float:
    """Signed distance to the nearest ground-box edge; inside < 0, edge = 0.

    Outside is positive. This compares the brick's XY centre, not its footprint.
    """
    x1, x2, y1, y2 = ground_bounds
    x, y = brick.pos[:2]
    return max(x1-x, x-x2, y1-y, y-y2)


def has_upper_center_on_or_outside_ground_boundary(bricks: List[Brick], base_z: float = 0.0) -> bool:
    bounds = ground_bbox(bricks, base_z)
    return bounds is not None and any(
        layer(b, base_z) > 0 and center_boundary_margin(b, bounds) >= -EPS
        for b in bricks)


def grasp_axis(brick: Brick, same_layer: List[Brick], clearance: float = GRIPPER_CLEARANCE_M):
    """Static side-strip proxy. Ignores finger height, robot reach and trajectories."""
    x1, x2, y1, y2 = brick.bbox_xy()
    strips = [(x1-clearance, x1, y1, y2), (x2, x2+clearance, y1, y2),
              (x1, x2, y1-clearance, y1), (x1, x2, y2, y2+clearance)]
    free = [True] * 4
    for other in same_layer:
        if other is brick or other.name == brick.name:
            continue
        u1, u2, v1, v2 = other.bbox_xy()
        for i, (a1, a2, b1, b2) in enumerate(strips):
            if min(a2,u2)-max(a1,u1)>EPS and min(b2,v2)-max(b1,v1)>EPS:
                free[i] = False
    if free[0] and free[1]:
        return 'x'
    if free[2] and free[3]:
        return 'y'
    return None


def static_disassembly_order(bricks: List[Brick], base_z: float = 0.0) -> List[str]:
    """Top layer first, accessible sides; proves only the documented static proxy."""
    remaining = list(bricks)
    order = []
    while remaining:
        highest = max(layer(b, base_z) for b in remaining)
        top = [b for b in remaining if layer(b, base_z) == highest]
        accessible = [b for b in top if grasp_axis(b, top)]
        if not accessible:
            raise ValueError(f'No static gripper access on layer {highest}')
        selected = min(accessible, key=lambda b: b.name)
        order.append(selected.name)
        remaining.remove(selected)
    return order


def geometry_config() -> dict:
    return {'length_unit': 'm', 'rotation_unit': 'rad',
            'pose_origin': 'xy_center_body_bottom', 'stud_pitch_m': STUD,
            'engaged_layer_height_m': BRICK_H, 'min_support_ratio': MIN_SUPPORT_RATIO,
            'gripper_side_clearance_m': GRIPPER_CLEARANCE_M,
            'mesh_scale': [0.001, 0.001, 0.001], 'mesh_recenter_xy': True}
