# Phase 2 coarse lifting policy

Batch 2.3 introduces lifting policy `0.1`, independently of the annotation,
construction-config, annotation-review, grammar, execution, renderer, demo, and
package versions. It converts supplied 2D evidence into deterministic
non-metric observations. It does not construct a grammar or render primitives.

## Coordinate mapping

SceneGrammarKit world coordinates are right-handed: `x` is horizontal, `y` is
upward, and increasing `z` is farther from the viewer. Root bounds and all
depth-zone intervals come from `ConstructionConfig`.

For normalized image coordinates `(u, v)`:

```text
x = root_x_min + u * (root_x_max - root_x_min)
y = root_y_min + (1 - v) * (root_y_max - root_y_min)
```

The `1 - v` term is required because image `v` increases downward while world
`y` increases upward. For a normalized rectangle:

```text
world_x_min = map_x(u_min)
world_x_max = map_x(u_max)
world_y_min = map_y(v_max)
world_y_max = map_y(v_min)
```

These equations work for translated roots and non-unit extents.

## Region depth

Every region uses the complete configured interval for its supplied depth-zone
label:

```text
world_z_min = configured_zone_z_min
world_z_max = configured_zone_z_max
```

This interval is a derived proxy convention. It is not observed thickness or a
physical dimension.

The supplied region role maps to a non-rendering purpose:

- `structural_region` -> `structural`
- `terminal_region` -> `terminal_candidate`
- `open_space` -> `open_space`

## Instance depth

Instances use their supplied shape bottom edge:

```text
bottom_v = shape.bounding_rectangle.v_max
zone_extent = zone_z_max - zone_z_min
raw_z_center = zone_z_min + (1 - bottom_v) * zone_extent
depth_extent = zone_extent * 0.05
```

The final center is shifted, when necessary, so a positive interval of exactly
5% of the zone extent remains fully inside the zone. It is never clipped to
zero thickness. Lower annotations receive nearer proxy anchors; higher
annotations receive farther anchors. This is a frozen normalized heuristic,
not monocular depth inference.

Repeat membership does not affect instance depth. Repeat grouping, count, and
spacing policies belong to later batches.

## Polygon evidence

Ordered polygon points, signed area, absolute area, bounding rectangle, and
centroid remain in the supplied observation evidence. World proxy bounds use
only the polygon bounding rectangle and record:

```text
proxy_approximation = image_polygon_bounding_box
```

The implementation performs no triangulation, simplification, repair,
extrusion, or polygon-derived mesh construction.

## Provenance

Each observation contains three immutable provenance partitions:

- `supplied`: annotation ID, semantic class, shape, depth zone, role, terminal
  geometry, parent, repeat membership and axis, split hint, order hint, and
  attributes;
- `configuration`: root bounds, selected depth-zone interval, projection model,
  and canonical construction-config hash;
- `derived`: world bounds, world centroid, depth policy, approximation, and
  lifting-policy version.

Stable IDs are `region:<region_id>` and `instance:<instance_id>`. Regions retain
annotation order, followed by instances in annotation order.

Source-image bytes may be decoded and hashed for provenance. The lifted scene
always records `source_pixels_used_for_geometric_inference=false`.

## Diagnostics

Warnings are deterministic and non-fatal:

- `image_verification_skipped`
- `polygon_bounding_box_proxy`
- `region_outside_declared_parent`
- `instance_outside_declared_parent`
- `overlapping_structural_regions`
- `empty_instance_terminal_geometry`
- `missing_repeat_member_order_hint`

They report approximations or supplied spatial inconsistencies without adding
an optimization or correction stage.

## Outputs and CLI

The integrated output contains:

```text
annotation.json
construction_config.json
lifted_observations.json
lifted_observations.txt
lifting_report.json
```

JSON uses UTF-8 direct Unicode, sorted keys, compact separators, finite numbers,
preserved ordered lists, and no final newline. Text has exactly one final
newline. Persistence is same-directory atomic, protects nonempty outputs unless
overwrite is explicit, preserves unrelated files during overwrite, cleans
temporary files, and writes the success report last.

Run:

```text
python -m scene_grammar_kit lift-assisted-input annotation.json \
  --config construction.json --out output_directory
```

`--skip-image-verification` explicitly records an unverified status, emits a
warning, and does not invent an image hash.

## Explicit nonclaims

The lifted observations are not metric depth, calibrated camera geometry,
physical object dimensions, a split hierarchy, split boundaries, inferred
repeat count, repeat spacing, a grammar, executable geometry, or a
reconstructed mesh. Source pixels are not analyzed for geometry.
