# WorkBenchMark task generation

Generator v2 fixes the task-generation and static-verification contracts. The
original `tasks/` dataset is retained as version 1 for traceability. It used a
32 mm stud pitch and different stack constraints; it must not be silently
interpreted as version 2, or mixed with newly generated evaluation results.

## Generate and verify

Requires Python 3.10+ and PyYAML. From the repository root:

```sh
python3 -m pip install -r requirements.txt
python3 scripts/generator.py --task_class all --num_samples 100 --output_dir versions/latest/tasks
python3 scripts/verifier.py --benchmark_root versions/latest/tasks
python3 -m unittest discover -s tests -v
```

`--num_samples` is the number **per class**: the command produces 400 instances,
each containing `final_product.yaml`, `scene_init.yaml`, and `metadata.yaml`.
Tier 3 and Tier 4 each use the following default distribution:
**80% with 3–5 bricks, 15% with 6–8, and 5% with 9–12**. Each 100-instance
run has counts `3:27, 4:27, 5:26, 6:5, 7:5, 8:5, 9:2, 10:1, 11:1, 12:1`.
The deterministic schedule interleaves groups, repeats every 100 accepted
instances, and retains its quotas when an attempt is retried. Every complete
20-instance segment has 16 small, 3 medium and 1 large task; shorter runs use
a prefix of this schedule. Direct API generation without a fixed count samples
the same 80/15/5 group probabilities. `--num_blocks` overrides the distribution.
Tier 2 allows 2–5 bricks and prioritizes short stacks: 85% with 2–3 and 15% with 4–5. Every 100-instance scheduled run has 43 two-brick, 42 three-brick, 8 four-brick and 7 five-brick tasks; each twenty-instance cycle preserves 85/15. Direct API calls without a fixed count sample the same group probabilities. Tier 1 always contains 2 bricks.

For a single class or a fixed count:

```sh
python3 scripts/generator.py --task_class simple_shape_assembly --num_samples 20 --num_blocks 12 --start_seed 42 --output_dir shape_examples
python3 scripts/verifier.py --instance_dir shape_examples/simple_shape_assembly/simple_shape_assembly_001
```

Seeds use offsets 0, 1000, 2000, 3000 for Tiers 1–4. The exact accepted seed and
brick count are stored in each metadata file. Reproduction uses
`generator.generate_instance_data(task_class, instance_idx, seed,
min_distance_cm=3.0, n_blocks=num_blocks)` with those values. There is no random
global state or iteration over unordered sets when selecting candidates.

Attempts are bounded (`--max_attempts`, default 20 × requested instances per
class), and unrecoverable errors return a nonzero exit status. Existing instances
are refused unless `--overwrite` is supplied. Generate to a fresh directory when
changing versions or experiment settings.

## Geometry and tier rules

- Positions are metres; rotations are radians. Pose origin is the nominal XY
  footprint centre and the brick body's bottom plane, not its 3D bounding-box
  centre. Layer zero lies on the assembly region's configured Z plane.
- Shared `scripts/geometry.py` defines 16 mm stud pitch, matching the 16-unit stud
  spacing in the supplied STL files when imported as millimetres. Nominal
  footprints are 32×32 mm and 64×32 mm; physical meshes have small body gaps.
- Import STL meshes at scale 0.001 on all axes, recentered in XY at nominal
  centres `(16,16)` and `(32,16)` in original mesh units. Their bottom Z is zero.
  Do not scale metres again or use the original corner origin as the task centre.
- The **20 mm engaged layer pitch is retained from the paper's YAML convention**.
  It is not the mesh's 23.75 mm overall height including studs. Validate actual
  insertion/engagement offsets against your simulator before physics experiments.
- Pick and assembly rectangles (0.40×0.28 m, 0.32×0.28 m) are working subregions;
  they are not specifications for full 24×24 physical base plates.
- Tier 1: 2 bricks, fixed type and yaw, identical XY centres, consecutive layers.
- Tier 2: 2–5 bricks (mostly 2–3), fixed type and identical XY centres, one brick on every
  consecutive layer. Each layer independently selects yaw 0 or 90 degrees:
  parallel or perpendicular footprints, with no lateral offset. Colors may vary.
  This version's rule supersedes the paper's fixed-yaw Tier 2 wording;
  the paper text must be updated before reporting this distribution as the paper's.
- Tier 3: 3–12 bricks, multiple ground supports connected by upper bridges, no
  footprint outside the ground layer's overall bounding box.
- Tier 4: 3–12 bricks, at least one upper brick's **XY centre on or outside
  the ground layer's overall bounding rectangle**. Equality is accepted.
  A protruding footprint with its centre strictly inside does not meet this rule.
  This centre condition replaces the earlier
  footprint-overhang interpretation. The boundary encloses all ground footprints,
  not just their centres, and is not the edge of the assembly plate.
- All classes: correct scene–goal inventory, plate bounds, stud-grid alignment,
  no same-layer overlap, at least 50% footprint support for every upper brick,
  and initial parts flat with at least 30 mm footprint-to-footprint clearance.
  Applying 50% to Tier 4 is a conservative v2 policy; the paper only gives that
  numerical threshold explicitly for Tier 3.

Tier 3/4 now use **one straight row, parallel footprints and at most three
occupied layers**, recorded as `shape_policy: simple_three_layer_row_v1`.
These are version-specific generation limits, not additional definitions from the
paper. The verifier checks this metadata and its structural claims. Tier 3 uses
supports linked by a bridge or staggered bricks. Tier 4 positions its outermost
top brick's centre exactly on a ground-envelope edge, with full support from the
long brick immediately below. The simplest case has a base, long brick and a
shifted top brick. Higher counts widen the row instead of adding tall
towers, branches or crossing beams. Global quarter-turn rotation, translation,
colours vary with the seed; Tier 4's top row stays at the boundary to guarantee
the centre condition. Generated centres are inside or on the ground envelope;
the verifier also permits outside centres when the other static constraints pass.
This remains a static proxy, not balance simulation.
Initial parts use bounded continuous rejection
sampling with a shuffled, jittered packing fallback when random packing fails.

Tier 2 records `stack_yaw_policy: independent_0_90_v1` in metadata to distinguish
the revised seed distribution from the earlier fixed-yaw v2 dataset. Its positions
are computed from one common centre and a square placement envelope, so rotating
a 4x2 footprint never shifts the centre or puts it outside the plate. Parallel
equal-size bricks have 100% nominal support; centred perpendicular 4x2 bricks
have 50%. A random stack may be all parallel; quarter turns are allowed, not forced.
Yaw angles equivalent modulo 180 degrees describe the same undirected footprint;
the generator emits only 0/90 and the schema rejects non-quarter-turn angles.

Tier 4 records `center_boundary_policy: upper_center_on_or_outside_ground_bbox_v1`.
The signed margin is `max(x_min-cx, cx-x_max, y_min-cy, cy-y_max)` in metres:
negative means inside, zero means boundary, positive means outside. At least one
upper centre must have margin >= -1e-8 (numerical tolerance). Earlier Tier 4 tasks
and pictures used the weaker footprint condition and are superseded; those
intermediate previews have been removed from the repository. Original remote `tasks/` is
retained as historical data and is not certified under this clarified rule.

## What validation certifies

The verifier checks schemas before using geometry, rejects NaN/infinity, malformed
poses and duplicate YAML keys, and validates class/ID against their directories.
It checks the geometry configuration rather than guessing the units of old tasks.

The gripper test uses empty 8 mm side strips on both sides of at least one axis
of a brick, against **same-layer** neighbours. Each layer must have an accessible
brick. A top-layer-first removal order is recorded in reverse as
`metadata.static_assembly_order`, providing a build-order witness for this proxy.
`verified: true` is scoped by
`validation_scope: static_grid_and_side_strip_proxy`.

This is not robot reachability, full finger-height/trajectory collision checking,
contact physics, press stability, or a real ABD planner. `planner_checked` remains
false; `--use_planner` fails explicitly until a real planner is connected. Calibrate
the clearance to your gripper and validate all insertion steps in the simulator
before claiming physical feasibility.

Perpendicular centred Tier 2 long bricks can extend beyond the ground brick's
rectangle. The ground-envelope overhang distinction applies to Tier 3/4; it does
not override Tier 2's explicitly allowed centre-aligned quarter-turn stacks.

## Evaluation boundary

`metrics.py` and `run_eval.py` now import the shared dimensions. Their environment
and policy adapters are still placeholders. This generation fix does not supply
the simulator/baseline or add the missing paper metrics; those require separate
implementation. Preserve the original paper results and rerun evaluation on the
new dataset before reporting v2 performance.


## Current image gallery

Use `scripts/render_gallery.py` to build a fresh gallery. The renderer defaults to 12 featured examples per tier and preserves centre inspections for all 100 Tier 4 instances. Output is grouped by tier and task instance. Each featured instance has a target, initial-to-target pair, layer plan, and four-panel inspection; Tier 2 and Tier 4 include their respective centre checks.

```sh
python3 scripts/render_gallery.py --output /tmp/benchmark_gallery_new
```

The current gallery is `versions/latest/images/index.html`. Historical generation and pictures remain under `versions/initial/`; root `tasks/` is the original remote archive.


## Geometric inspection annotations

See [the Chinese tier reading guide](tier_definitions.md). Every current image uses ground-envelope midpoint G as the assembly reference; all layer plans share G. This is a geometric reference, not a centre of mass. Nominal ground boundaries are purple; the reference axis is magenta; C identifiers mark true brick XY centres (at body mid-height in 3D). Qualifying Tier 4 upper centres are orange. Initial parts use their plate midpoint P and are not subject to assembly centre alignment. Rendering verifies transformed mesh XY centres before drawing overlays. Fresh previews are rendered from YAML without old raster caches; structure_axis_audit.json records the reference and brick centres for every component view.

Two-brick Tier 2 samples may visually overlap Tier 1 when their independently sampled yaws happen to match. Independent 0/90 yaw remains permitted in Tier 2; fixed common yaw remains required in Tier 1. The count distribution belongs to the current benchmark contract; the original paper text and its published results remain separate.
