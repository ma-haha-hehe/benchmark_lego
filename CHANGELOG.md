# Changelog

## Task generation v2

### Geometry and validation

- Share the nominal 16 mm stud pitch, 20 mm layer pitch, metre/radian units,
  and brick-bottom pose convention across generation, validation and rendering.
- Validate inventory, plate bounds, grid alignment, support, connectivity,
  initial clearance and a static disassembly-order witness.
- Reject duplicate YAML keys, nonfinite or malformed poses, overlapping parts,
  unsupported structures, inconsistent metadata and legacy geometry.
- Bound generation retries, provide a packing fallback and refuse overwrites
  unless explicitly enabled. Empty or invalid verification runs fail.

### Tier definitions and distributions

- Tier 1 contains two equal-type bricks with a common XY centre and fixed yaw.
- Tier 2 contains 2–5 equal-type bricks with exactly coincident XY centres and
  independently selected 0/90 degree yaw. Each 100-task set contains 43, 42, 8
  and 7 tasks with 2, 3, 4 and 5 bricks respectively.
- Tiers 3 and 4 use straight, parallel layouts with at most three layers.
  Each tier contains 80% 3–5-brick, 15% 6–8-brick and 5% 9–12-brick tasks.
- Tier 3 keeps every upper footprint inside the overall ground-layer envelope.
- Tier 4 requires at least one upper brick's XY centre on or outside that
  envelope. A protruding footprint with its centre inside is insufficient.

### Dataset and inspection

- Store the current 400 tasks in `versions/latest/tasks/`, with 100 per tier.
  Every instance includes a target, initial scene and reproducibility metadata.
- Preserve the first generated dataset and previews under `versions/initial/`.
  Keep root `tasks/` as the original historical dataset.
- Provide a paper-style gallery with 12 featured examples per tier, multiple
  views, paired initial/target layouts and all 100 Tier 4 centre checks.
- Annotate the common ground-envelope reference axis, boundaries and actual
  brick centres. The geometric reference is not a centre of mass.
- Include task verification, source hashes, image/source correspondence and
  transformed-mesh centre audits.

### Verification scope

The regression suite contains 35 tests, including 240 Tier 2 yaw/type/edge
subcases. The 400 current tasks pass static verification and reproduce from
their recorded seeds and block counts. Image and geometry checks do not certify
contact physics, robot reachability, balance or successful physical execution.

This dataset revision changes the task distribution and requires new evaluation.
It does not revise or reproduce the original paper's reported performance.
