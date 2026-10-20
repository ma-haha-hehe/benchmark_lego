"""Generate bounded, reproducible WorkBenchMark v2 tasks (static validation)."""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import tempfile
from pathlib import Path

import yaml

from geometry import (Brick, BRICK_H, EPS, GENERATOR_VERSION, MIN_CLEARANCE_M,
                      STUD, TASK_CLASSES, VALID_COLORS,
                      TIER2_YAW_POLICY, SHAPE_POLICY, TIER4_CENTER_POLICY,
                      geometry_config, grid_size, rect_distance,
                      static_disassembly_order, within_plate)
from verifier import verify_instance_data

BrickSpec = SceneBrick = Brick
COLORS = sorted(VALID_COLORS)
DEFAULT_PARTS_PLATE_CENTER = (0.0, -0.16, 0.0)
DEFAULT_ASSEMBLY_PLATE_CENTER = (0.0, 0.16, 0.0)
# Working regions on the physical plates, not claims about full plate dimensions.
PARTS_PLATE_SIZE = (0.40, 0.28)
ASSEMBLY_PLATE_SIZE = (0.32, 0.28)


class GenerationError(RuntimeError):
    """A bounded random construction failed; another seed may be attempted."""


def yaw_to_rotation(yaw_deg):
    return [0.0, 0.0, round(math.radians(yaw_deg % 360), 8)]


def make_brick_name(brick_type, index):
    return f'{"4x2" if brick_type == "brick_4x2" else "2x2"}_brick_{index}'


def type_to_grid_size(brick_type, yaw_deg):
    return grid_size(brick_type, yaw_deg)


def plate_grid_capacity(plate_size):
    return tuple(math.floor(v/STUD + EPS) for v in plate_size)


def footprint_cells(gx, gy, brick_type, yaw_deg):
    sx, sy = grid_size(brick_type, yaw_deg)
    return [(gx+dx, gy+dy) for dx in range(sx) for dy in range(sy)]


def grid_to_metric(gx, gy, gz, plate_center, plate_size, brick_type, yaw_deg):
    sx, sy = grid_size(brick_type, yaw_deg)
    return [round(plate_center[0]-plate_size[0]/2+(gx+sx/2)*STUD, 6),
            round(plate_center[1]-plate_size[1]/2+(gy+sy/2)*STUD, 6),
            round(plate_center[2]+gz*BRICK_H, 6)]


def _blocks(placements, rng):
    return [Brick(make_brick_name(bt, i), bt, rng.choice(COLORS),
                  grid_to_metric(x, y, z, DEFAULT_ASSEMBLY_PLATE_CENTER,
                                 ASSEMBLY_PLATE_SIZE, bt, yaw), yaw_to_rotation(yaw))
            for i, (x, y, z, bt, yaw) in enumerate(placements, 1)]


def _check_count(n, minimum, maximum):
    if not isinstance(n, int) or isinstance(n, bool) or not minimum <= n <= maximum:
        raise ValueError(f'Number of bricks must be in [{minimum}, {maximum}]')


def _stack(rng, n, independent_yaw=False):
    bt = rng.choice(['brick_2x2', 'brick_4x2'])
    if independent_yaw:
        yaws = [rng.choice([0, 90]) for _ in range(n)]
        # Place a square envelope first, then recenter each rotated footprint.
        # Reusing its lower-left grid corner would shift a 4x2 brick's centre.
        envelope = max(grid_size(bt, 0))
        width, height = plate_grid_capacity(ASSEMBLY_PLATE_SIZE)
        gx, gy = rng.randint(0, width-envelope), rng.randint(0, height-envelope)
        placements = []
        for z, yaw in enumerate(yaws):
            sx, sy = grid_size(bt, yaw)
            placements.append((gx+(envelope-sx)//2, gy+(envelope-sy)//2, z, bt, yaw))
        return _blocks(placements, rng)
    yaw = rng.choice([0, 90])
    sx, sy = grid_size(bt, yaw)
    width, height = plate_grid_capacity(ASSEMBLY_PLATE_SIZE)
    gx, gy = rng.randint(0, width-sx), rng.randint(0, height-sy)
    return _blocks([(gx, gy, z, bt, yaw) for z in range(n)], rng)


def generate_two_brick_stack(rng):
    return _stack(rng, 2)


def generate_simple_multi_brick_stack(rng, n_blocks):
    _check_count(n_blocks, 2, 5)
    return _stack(rng, n_blocks, independent_yaw=True)


def _rotate_and_position(placements, rng, padding):
    """Rotate entire grid construction, then translate without losing alignment."""
    turns = rng.randrange(4)
    transformed = []
    for x, y, z, bt, yaw in placements:
        for _ in range(turns):
            sx, sy = grid_size(bt, yaw)
            x, y, yaw = -y-sy, x, (yaw+90) % 360
        transformed.append((x, y, z, bt, yaw))
    cells = [c for x,y,_,bt,yaw in transformed for c in footprint_cells(x,y,bt,yaw)]
    min_x, min_y = min(x for x,y in cells), min(y for x,y in cells)
    width = max(x for x,y in cells)-min_x+1
    height = max(y for x,y in cells)-min_y+1
    gw, gh = plate_grid_capacity(ASSEMBLY_PLATE_SIZE)
    ox = rng.randint(padding, gw-width-padding)-min_x
    oy = rng.randint(padding, gh-height-padding)-min_y
    return [(x+ox,y+oy,z,bt,yaw) for x,y,z,bt,yaw in transformed]


def _simple_row(rng, n, overhang=False):
    """A single straight row, at most three layers, with no relative yaw changes.

    Staggered second-layer bricks connect adjacent ground supports. A contiguous
    top row adds the remaining bricks. Tier 4 puts the outermost top brick's
    centre on the ground envelope edge, with 100% support from the beam below.
    This is stronger than merely extending a footprint. Global rotation/translation,
    the top-row position and colours vary, without growing branches or towers.
    """
    if overhang and n == 3:
        placements = [(0,0,0,'brick_2x2',0), (-1,0,1,'brick_4x2',0),
                      (1,0,2,'brick_2x2',0)]
    elif n <= 5:
        second = 2 if overhang else 3
        placements = [(0,0,0,'brick_2x2',0), (second,0,0,'brick_2x2',0),
                      (1,0,1,'brick_4x2',0)]
        top_positions = [1,3]
        if n == 4:
            top_positions = [3] if overhang else [rng.choice(top_positions)]
        elif n == 3:
            top_positions = []
        placements += [(x,0,2,'brick_2x2',0) for x in top_positions]
    else:
        supports = math.ceil((n+1)/3)
        placements = [(2*i,0,0,'brick_2x2',0) for i in range(supports)]
        placements += [(2*i+1,0,1,
                        'brick_4x2' if overhang and i == supports-2 else 'brick_2x2',0)
                       for i in range(supports-1)]
        remaining = n-len(placements)
        start = supports-remaining if overhang else rng.randint(0, supports-remaining)
        placements += [(2*i+int(overhang),0,2,'brick_2x2',0) for i in range(start,start+remaining)]
    return _blocks(_rotate_and_position(placements, rng, 2), rng)


def generate_simple_shape_assembly(rng, n_blocks):
    _check_count(n_blocks, 3, 12)
    return _simple_row(rng, n_blocks)


def generate_balanced_order_sensitive(rng, n_blocks):
    _check_count(n_blocks, 3, 12)
    return _simple_row(rng, n_blocks, overhang=True)


def _sample_stack_count(rng):
    low, high = (2,3) if rng.randrange(100) < 85 else (4,5)
    return rng.randint(low, high)


def _sample_shape_count(rng):
    bucket = rng.randrange(100)
    low, high = (3,5) if bucket < 80 else ((6,8) if bucket < 95 else (9,12))
    return rng.randint(low, high)


def generate_goal_by_class(task_class, rng, n_blocks=None):
    if task_class == 'two_brick_stack':
        if n_blocks not in [None, 2]:
            raise ValueError('Tier 1 requires two bricks')
        return generate_two_brick_stack(rng)
    if task_class == 'simple_multi_brick_stack':
        return generate_simple_multi_brick_stack(rng, n_blocks if n_blocks is not None else _sample_stack_count(rng))
    if task_class == 'simple_shape_assembly':
        return generate_simple_shape_assembly(rng, n_blocks if n_blocks is not None else _sample_shape_count(rng))
    if task_class == 'balanced_order_sensitive':
        return generate_balanced_order_sensitive(rng, n_blocks if n_blocks is not None else _sample_shape_count(rng))
    raise ValueError(f'Unknown task class: {task_class}')


def sample_scene_init(goal_bricks, rng, min_distance_m,
                      parts_plate_center=DEFAULT_PARTS_PLATE_CENTER,
                      parts_plate_size=PARTS_PLATE_SIZE):
    if not math.isfinite(min_distance_m) or min_distance_m < MIN_CLEARANCE_M:
        raise ValueError('Initial clearance must be at least 0.03 m')
    plate = {'center': list(parts_plate_center), 'size': list(parts_plate_size)}
    # Bounded rejection sampling preserves continuous random scenes when packing succeeds.
    for _ in range(8):
        scene = []
        for goal in goal_bricks:
            for _ in range(300):
                yaw = rng.choice([0,90,180,270])
                sx, sy = grid_size(goal.type, yaw)
                x, y = parts_plate_center[:2]
                w, h = parts_plate_size
                if sx*STUD > w or sy*STUD > h:
                    continue
                candidate = Brick(goal.name,goal.type,goal.color,
                                  [round(rng.uniform(x-w/2+sx*STUD/2, x+w/2-sx*STUD/2),6),
                                   round(rng.uniform(y-h/2+sy*STUD/2, y+h/2-sy*STUD/2),6),
                                   parts_plate_center[2]], yaw_to_rotation(yaw))
                if within_plate(candidate,plate) and all(rect_distance(candidate,b) >= min_distance_m+2e-6 for b in scene):
                    scene.append(candidate)
                    break
            else:
                break
        if len(scene) == len(goal_bricks):
            return scene
    # Guaranteed finite fallback if conservative square slots fit the working region.
    side = max(max(grid_size(b.type,0))*STUD for b in goal_bricks)
    w, h = parts_plate_size
    packings = []
    for cols in range(1, len(goal_bricks)+1):
        rows = math.ceil(len(goal_bricks)/cols)
        extra_x = w-cols*side-(cols-1)*min_distance_m
        extra_y = h-rows*side-(rows-1)*min_distance_m
        if extra_x >= 1e-5 and extra_y >= 1e-5:
            packings.append((min(extra_x/cols,extra_y/rows),cols,rows))
    if not packings:
        raise GenerationError('Parts plate cannot fit the requested clearance; choose a feasible configuration')
    _, cols, rows = max(packings)
    jx = (w-cols*side-(cols-1)*min_distance_m)/(2*cols)
    jy = (h-rows*side-(rows-1)*min_distance_m)/(2*rows)
    slots = [(c,r) for r in range(rows) for c in range(cols)]
    rng.shuffle(slots)
    scene = []
    for goal, (c,r) in zip(goal_bricks, slots):
        x = parts_plate_center[0]-w/2+side/2+jx+c*(side+min_distance_m+2*jx)+rng.uniform(-jx*.8,jx*.8)
        y = parts_plate_center[1]-h/2+side/2+jy+r*(side+min_distance_m+2*jy)+rng.uniform(-jy*.8,jy*.8)
        scene.append(Brick(goal.name,goal.type,goal.color,[round(x,6),round(y,6),parts_plate_center[2]],
                           yaw_to_rotation(rng.choice([0,90,180,270]))))
    return scene


def _brick_dict(b):
    return {'name':b.name, 'type':b.type, 'color':b.color, 'pos':b.pos, 'rotation':b.rotation}


def build_final_product_yaml(goal_bricks):
    return {'blocks': [_brick_dict(b) for b in goal_bricks]}


def build_scene_init_yaml(scene_bricks, min_distance_m):
    return {'geometry': geometry_config(), 'min_distance_m': min_distance_m,
            'parts_plate': {'center':list(DEFAULT_PARTS_PLATE_CENTER),'size':list(PARTS_PLATE_SIZE)},
            'assembly_plate': {'center':list(DEFAULT_ASSEMBLY_PLATE_CENTER),'size':list(ASSEMBLY_PLATE_SIZE)},
            'blocks': [_brick_dict(b) for b in scene_bricks]}


def generate_instance_data(task_class, instance_idx, seed, min_distance_cm=3.0, use_planner=False, n_blocks=None):
    if use_planner:
        raise ValueError('No physics/robot planner is connected; --use_planner cannot certify tasks')
    if not math.isfinite(min_distance_cm) or min_distance_cm < 3.0:
        raise ValueError('min_distance_cm must be finite and at least 3.0')
    if not isinstance(seed,int) or isinstance(seed,bool):
        raise ValueError('seed must be an integer')
    if not isinstance(instance_idx,int) or isinstance(instance_idx,bool) or instance_idx < 1:
        raise ValueError('instance_idx must be positive')
    rng = random.Random(seed)
    goals = generate_goal_by_class(task_class,rng,n_blocks)
    initial = sample_scene_init(goals,rng,min_distance_cm/100)
    goal_yaml = build_final_product_yaml(goals)
    scene_yaml = build_scene_init_yaml(initial,min_distance_cm/100)
    metadata = {'instance_id':f'{task_class}_{instance_idx:03d}', 'task_class':task_class,
                'seed':seed, 'num_blocks':len(goals), 'generator_version':GENERATOR_VERSION,
                'verified':True, 'validation_scope':'static_grid_and_side_strip_proxy',
                'planner_checked':False,
                'static_assembly_order':list(reversed(static_disassembly_order(goals)))}
    if task_class == 'simple_multi_brick_stack':
        metadata['stack_yaw_policy'] = TIER2_YAW_POLICY
    elif task_class in TASK_CLASSES[2:]:
        metadata['shape_policy'] = SHAPE_POLICY
        if task_class == 'balanced_order_sensitive':
            metadata['center_boundary_policy'] = TIER4_CENTER_POLICY
    ok, errors = verify_instance_data(goal_yaml,scene_yaml,metadata)
    if not ok:
        raise GenerationError('; '.join(errors))
    return goal_yaml,scene_yaml,metadata


def generate_instance(output_root, task_class, instance_idx, seed, min_distance_cm, use_planner,
                      n_blocks=None, overwrite=False):
    directory = Path(output_root)/task_class/f'{task_class}_{instance_idx:03d}'
    if directory.exists() and not overwrite:
        raise FileExistsError(f'{directory} exists; use a fresh output directory or --overwrite')
    data = generate_instance_data(task_class,instance_idx,seed,min_distance_cm,use_planner,n_blocks)
    directory.mkdir(parents=True,exist_ok=True)
    for filename,value in zip(['final_product.yaml','scene_init.yaml','metadata.yaml'],data):
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=directory,delete=False) as stream:
            yaml.safe_dump(value,stream,sort_keys=False,allow_unicode=True)
            temporary = stream.name
        os.replace(temporary,directory/filename)
    return data


def _scheduled_count(task_class, index):
    if task_class == 'two_brick_stack':
        return 2
    if task_class == 'simple_multi_brick_stack':
        # Every 20 accepted instances: 17 small stacks and 3 longer ones.
        # Across 100 tasks: 43 / 42 / 8 / 7 for counts 2 / 3 / 4 / 5.
        cycle, slot = divmod((index-1)%100, 20)
        if slot in (4,9,14):
            return 4+(3*cycle+slot//5)%2
        small_index = slot-sum(p<slot for p in (4,9,14))
        return 2+(17*cycle+small_index)%2
    # Every 20 accepted instances: 16 small, 3 medium, 1 large. Across 100,
    # cycle individual counts as 27/27/26, 5/5/5 and 2/1/1/1 respectively.
    # Use accepted instance index so retries cannot skew the quotas.
    cycle, slot = divmod((index-1)%100, 20)
    if slot == 19:
        return (9,9,10,11,12)[cycle%5]
    if slot in (4,9,14):
        return 6+slot//5
    small_index = slot-sum(p < slot for p in (4,9,14))
    return 3+(16*cycle+small_index)%3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task_class',required=True,choices=[*TASK_CLASSES,'all'])
    parser.add_argument('--num_samples',type=int,default=100,help='Instances per task class')
    parser.add_argument('--start_seed',type=int,default=0)
    parser.add_argument('--num_blocks',type=int,help='Fixed count; Tier 2 default: 85%% 2-3, 15%% 4-5; Tier 3/4 default: 80%% 3-5, 15%% 6-8, 5%% 9-12')
    parser.add_argument('--min_distance_cm',type=float,default=3.0)
    parser.add_argument('--max_attempts',type=int,help='Maximum total attempts per class (default 20 x samples)')
    parser.add_argument('--use_planner',action='store_true',help='Unavailable until a robot/physics planner is integrated')
    parser.add_argument('--output_dir',default='versions/latest/tasks')
    parser.add_argument('--overwrite',action='store_true')
    args = parser.parse_args()
    if args.num_samples <= 0 or not math.isfinite(args.min_distance_cm) or args.min_distance_cm < 3:
        parser.error('num_samples must be positive and min_distance_cm must be finite and >= 3')
    if args.use_planner:
        parser.error('No physics/robot planner is integrated; static validation is always performed')
    if args.task_class == 'all' and args.num_blocks is not None:
        parser.error('--num_blocks requires one task class')
    if args.num_blocks is not None:
        low, high = (2,2) if args.task_class == 'two_brick_stack' else ((2,5) if args.task_class == 'simple_multi_brick_stack' else (3,12))
        if not low <= args.num_blocks <= high:
            parser.error(f'num_blocks must be in [{low}, {high}] for this tier')
    maximum = args.max_attempts if args.max_attempts is not None else args.num_samples*20
    if maximum < args.num_samples:
        parser.error('max_attempts must be at least num_samples')
    classes = TASK_CLASSES if args.task_class == 'all' else [args.task_class]
    try:
        for task_class in classes:
            class_offset = TASK_CLASSES.index(task_class)*1000
            generated = 0
            for attempt in range(maximum):
                count = args.num_blocks if args.num_blocks is not None else _scheduled_count(task_class,generated+1)
                seed = args.start_seed+class_offset+attempt
                try:
                    data = generate_instance(args.output_dir,task_class,generated+1,seed,args.min_distance_cm,
                                             False,count,args.overwrite)
                except GenerationError as error:
                    print(f'[RETRY] seed={seed}: {error}',file=sys.stderr)
                    continue
                generated += 1
                print(f'[OK] {data[2]["instance_id"]}: {count} bricks, seed={seed}')
                if generated == args.num_samples:
                    break
            if generated != args.num_samples:
                raise GenerationError(f'{task_class}: generated {generated}/{args.num_samples} after {maximum} attempts')
    except (ValueError,OSError,GenerationError) as error:
        print(f'[ERROR] {error}',file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
