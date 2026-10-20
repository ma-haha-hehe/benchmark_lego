"""Independent task/schema validation for generator v2's static grid model."""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from geometry import (Brick, BRICK_H, EPS, GENERATOR_VERSION, MIN_CLEARANCE_M,
                      MIN_SUPPORT_RATIO, STUD, TASK_CLASSES, VALID_COLORS,
                      TIER2_YAW_POLICY, SHAPE_POLICY, TIER4_CENTER_POLICY,
                      VALID_TYPES, geometry_config, grasp_axis,
                      has_external_overhang, has_upper_center_on_or_outside_ground_boundary,
                      layer, overlap_area, rect_distance,
                      static_disassembly_order, support_ratio, within_plate)


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key, value in node.value:
        name = loader.construct_object(key, deep=deep)
        if name in result:
            raise ValueError(f'Duplicate YAML key: {name}')
        result[name] = loader.construct_object(value, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_yaml(path):
    with open(path, encoding='utf-8') as stream:
        value = yaml.load(stream, Loader=UniqueKeyLoader)
    if not isinstance(value, dict):
        raise ValueError(f'{path}: expected a YAML mapping')
    return value


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _vector(value, count):
    return isinstance(value, list) and len(value) == count and all(_number(v) for v in value)


def parse_bricks(blocks):
    return [Brick(b['name'], b['type'], b['color'], list(b['pos']), list(b['rotation'])) for b in blocks]


def _blocks_schema(value, label):
    errors = []
    if not isinstance(value, list) or not value:
        return [f'{label}: blocks must be a nonempty list']
    names = set()
    for index, b in enumerate(value):
        prefix = f'{label}[{index}]'
        if not isinstance(b, dict):
            errors.append(f'{prefix}: brick must be a mapping')
            continue
        name = b.get('name')
        if not isinstance(name, str) or not name:
            errors.append(f'{prefix}: name must be a nonempty string')
        elif name in names:
            errors.append(f'{prefix}: duplicate name {name}')
        else:
            names.add(name)
        if not isinstance(b.get('type'), str) or b['type'] not in VALID_TYPES:
            errors.append(f'{prefix}: invalid type')
        if not isinstance(b.get('color'), str) or b['color'] not in VALID_COLORS:
            errors.append(f'{prefix}: invalid color')
        if not _vector(b.get('pos'), 3):
            errors.append(f'{prefix}: pos must contain 3 finite numbers')
        if not _vector(b.get('rotation'), 3):
            errors.append(f'{prefix}: rotation must contain 3 finite numbers')
        else:
            roll, pitch, yaw = b['rotation']
            if abs(roll) > EPS or abs(pitch) > EPS:
                errors.append(f'{prefix}: roll and pitch must be zero')
            if abs(yaw/(math.pi/2)-round(yaw/(math.pi/2))) > 5e-5:
                errors.append(f'{prefix}: yaw must be a multiple of pi/2 radians')
    return errors


def _plate_schema(plate, label):
    if not isinstance(plate, dict) or not _vector(plate.get('center'), 3) or not _vector(plate.get('size'), 2):
        return [f'{label}: expected center[3] and size[2] with finite numbers']
    if any(v <= 0 for v in plate['size']):
        return [f'{label}: plate dimensions must be positive']
    return []


def verify_goal_connected(bricks):
    if not bricks:
        return ['Goal is empty']
    seen = {0}
    pending = [0]
    while pending:
        i = pending.pop()
        for j, b in enumerate(bricks):
            if j not in seen and abs(abs(bricks[i].pos[2]-b.pos[2])-BRICK_H) <= EPS and overlap_area(bricks[i], b) > EPS*EPS:
                seen.add(j)
                pending.append(j)
    return [] if len(seen) == len(bricks) else ['Goal is not connected by vertical stud connections']


def verify_goal_geometry(bricks, assembly_plate, task_class):
    errors = []
    layers = defaultdict(list)
    base_z = assembly_plate['center'][2]
    ox = assembly_plate['center'][0] - assembly_plate['size'][0]/2
    oy = assembly_plate['center'][1] - assembly_plate['size'][1]/2
    for b in bricks:
        if not within_plate(b, assembly_plate):
            errors.append(f'{b.name}: outside assembly plate')
        z = (b.pos[2]-base_z)/BRICK_H
        if z < -EPS or abs(z-round(z)) > 1e-6:
            errors.append(f'{b.name}: invalid/non-grid layer')
        x1, _, y1, _ = b.bbox_xy()
        if any(abs(v-round(v)) > 1e-6 for v in [(x1-ox)/STUD, (y1-oy)/STUD]):
            errors.append(f'{b.name}: off stud grid')
        layers[layer(b, base_z)].append(b)
    if errors:
        return errors
    for level, group in layers.items():
        for i, a in enumerate(group):
            for b in group[i+1:]:
                if overlap_area(a, b) > EPS*EPS:
                    errors.append(f'Same-layer collision: {a.name} / {b.name}')
    if errors:
        return errors
    for level, group in layers.items():
        for b in group:
            if level > 0:
                ratio = support_ratio(b, layers.get(level-1, []))
                if ratio < MIN_SUPPORT_RATIO-EPS:
                    errors.append(f'{b.name}: support ratio {ratio:.3f} below {MIN_SUPPORT_RATIO}')
        if not any(grasp_axis(b, group) for b in group):
            errors.append(f'Layer {level}: no static side-strip gripper access')
    errors.extend(verify_goal_connected(bricks))
    if task_class not in TASK_CLASSES:
        errors.append(f'Unknown task class: {task_class}')
        return errors
    n = len(bricks)
    if task_class == 'two_brick_stack' and n != 2:
        errors.append('Tier 1 requires exactly 2 bricks')
    if task_class == 'simple_multi_brick_stack' and not 2 <= n <= 5:
        errors.append('Tier 2 requires 2-5 bricks')
    if task_class in TASK_CLASSES[2:] and not 3 <= n <= 12:
        errors.append('Tier 3/4 require 3-12 bricks')
    if task_class in TASK_CLASSES[:2]:
        anchor = bricks[0]
        if any(b.type != anchor.type for b in bricks):
            errors.append('Stack must use a fixed brick type')
        if task_class == 'two_brick_stack' and any(b.yaw_deg() != anchor.yaw_deg() for b in bricks):
            errors.append('Stack must use a fixed yaw')
        if any(abs(b.pos[j]-anchor.pos[j]) > EPS for b in bricks for j in [0, 1]):
            errors.append('Stack must be centre-aligned')
        if set(layers) != set(range(n)) or any(len(group) != 1 for group in layers.values()):
            errors.append('Stack must have one brick on each consecutive layer starting at zero')
    elif task_class == 'simple_shape_assembly':
        if len(layers[0]) < 2:
            errors.append('Tier 3 requires multiple ground columns')
        if has_external_overhang(bricks, base_z):
            errors.append('Tier 3 must remain inside the ground-layer bounding box')
    elif not has_upper_center_on_or_outside_ground_boundary(bricks, base_z):
        errors.append('Tier 4 requires an upper brick centre on or outside the ground-layer bounding box')
    return errors


def verify_instance_data(final_product, scene_init, metadata, expected_id=None, expected_class=None, use_planner=False):
    errors = []
    if not all(isinstance(v, dict) for v in [final_product, scene_init, metadata]):
        return False, ['Task files must contain mappings']
    errors.extend(_blocks_schema(final_product.get('blocks'), 'goal'))
    errors.extend(_blocks_schema(scene_init.get('blocks'), 'scene'))
    for name in ['parts_plate', 'assembly_plate']:
        errors.extend(_plate_schema(scene_init.get(name), name))
    if errors:
        return False, errors
    if scene_init.get('geometry') != geometry_config():
        errors.append('Missing/incompatible geometry configuration; regenerate legacy tasks with generator v2')
    clearance = scene_init.get('min_distance_m')
    if not _number(clearance) or clearance < MIN_CLEARANCE_M:
        errors.append('Initial clearance must be at least 0.03 m')
    task_class = metadata.get('task_class')
    if not isinstance(task_class, str) or task_class not in TASK_CLASSES:
        errors.append('Invalid metadata task_class')
    if not isinstance(metadata.get('instance_id'), str) or not metadata.get('instance_id'):
        errors.append('Invalid metadata instance_id')
    if expected_id is not None and metadata.get('instance_id') != expected_id:
        errors.append('metadata instance_id does not match directory')
    if expected_class is not None and task_class != expected_class:
        errors.append('metadata task_class does not match directory')
    if not isinstance(metadata.get('seed'), int) or isinstance(metadata.get('seed'), bool):
        errors.append('metadata seed must be an integer')
    if not isinstance(metadata.get('num_blocks'), int) or isinstance(metadata.get('num_blocks'), bool) or metadata.get('num_blocks') != len(final_product.get('blocks', [])):
        errors.append('metadata num_blocks is invalid')
    if metadata.get('generator_version') != GENERATOR_VERSION:
        errors.append('metadata generator_version must be 2')
    if task_class == 'simple_multi_brick_stack' and metadata.get('stack_yaw_policy') != TIER2_YAW_POLICY:
        errors.append('Tier 2 stack_yaw_policy is missing/incompatible; regenerate Tier 2 tasks')
    if task_class in TASK_CLASSES[2:] and metadata.get('shape_policy') != SHAPE_POLICY:
        errors.append('Tier 3/4 shape_policy is missing/incompatible; regenerate Tier 3/4 tasks')
    if task_class == 'balanced_order_sensitive' and metadata.get('center_boundary_policy') != TIER4_CENTER_POLICY:
        errors.append('Tier 4 center_boundary_policy is missing/incompatible; regenerate Tier 4 tasks')
    if metadata.get('verified') is not True or metadata.get('validation_scope') != 'static_grid_and_side_strip_proxy':
        errors.append('metadata must identify successful static validation and its scope')
    if metadata.get('planner_checked') is not False:
        errors.append('No physics/robot planner is connected; planner_checked must be false')
    if use_planner:
        errors.append('Robot/physics planner validation is unavailable')
    if errors:
        return False, errors
    goals = parse_bricks(final_product['blocks'])
    scene = parse_bricks(scene_init['blocks'])
    errors.extend(verify_goal_geometry(goals, scene_init['assembly_plate'], task_class))
    if task_class in TASK_CLASSES[2:]:
        levels = {layer(b, scene_init['assembly_plate']['center'][2]) for b in goals}
        yaws = {b.yaw_deg() for b in goals}
        if len(levels) > 3 or any(z > 2 for z in levels):
            errors.append('simple_three_layer_row_v1 allows at most three layers')
        if len(yaws) != 1:
            errors.append('simple_three_layer_row_v1 requires parallel brick footprints')
        else:
            cross_axis = 1 if next(iter(yaws)) == 0 else 0
            if any(abs(b.pos[cross_axis]-goals[0].pos[cross_axis]) > EPS for b in goals):
                errors.append('simple_three_layer_row_v1 requires one straight row')
    pick = scene_init['parts_plate']
    asm = scene_init['assembly_plate']
    if abs(pick['center'][0]-asm['center'][0]) < (pick['size'][0]+asm['size'][0])/2-EPS and abs(pick['center'][1]-asm['center'][1]) < (pick['size'][1]+asm['size'][1])/2-EPS:
        errors.append('Pick and assembly regions must be disjoint')
    for b in scene:
        if not within_plate(b, pick):
            errors.append(f'{b.name}: outside parts plate')
        if abs(b.pos[2]-pick['center'][2]) > EPS:
            errors.append(f'{b.name}: initial scene must be flat')
    for i, a in enumerate(scene):
        for b in scene[i+1:]:
            if rect_distance(a, b) < clearance-EPS:
                errors.append(f'Initial clearance violation: {a.name} / {b.name}')
    goal_map = {b.name: (b.type, b.color) for b in goals}
    scene_map = {b.name: (b.type, b.color) for b in scene}
    if goal_map != scene_map:
        errors.append('Scene and goal names/types/colors differ')
    try:
        order = list(reversed(static_disassembly_order(goals, asm['center'][2])))
        if metadata.get('static_assembly_order') != order:
            errors.append('metadata static_assembly_order does not match the static witness')
    except ValueError as e:
        errors.append(str(e))
    return not errors, errors


def verify_instance_dir(instance_dir, use_planner=False):
    directory = Path(instance_dir)
    try:
        data = [load_yaml(directory/name) for name in ['final_product.yaml', 'scene_init.yaml', 'metadata.yaml']]
        return verify_instance_data(*data, expected_id=directory.name, expected_class=directory.parent.name, use_planner=use_planner)
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as e:
        return False, [f'Cannot validate instance: {e}']


def verify_benchmark_root(root_dir, use_planner=False):
    directories = sorted(p for p in Path(root_dir).glob('*/*') if p.is_dir())
    passed = 0
    for directory in directories:
        ok, errors = verify_instance_dir(directory, use_planner)
        passed += int(ok)
        print(f'[{"PASS" if ok else "FAIL"}] {directory}')
        for error in errors:
            print(f'  - {error}')
    return passed, len(directories)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--instance_dir')
    target.add_argument('--benchmark_root')
    parser.add_argument('--use_planner', action='store_true')
    args = parser.parse_args()
    if args.instance_dir:
        ok, errors = verify_instance_dir(args.instance_dir, args.use_planner)
        print(f'[{"PASS" if ok else "FAIL"}] {args.instance_dir}')
        for error in errors:
            print(f'  - {error}')
        return 0 if ok else 1
    passed, total = verify_benchmark_root(args.benchmark_root, args.use_planner)
    print(f'Summary: {passed}/{total} instances passed.')
    return 0 if total > 0 and passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
