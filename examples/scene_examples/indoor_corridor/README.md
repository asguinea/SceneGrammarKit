# Indoor Corridor

## Purpose

This secondary grammar-only example demonstrates a central passage, explicit
side-wall structure, vertical floor/usable/ceiling organization, repeated
doors along depth, and a terminal end wall.

## Grammar hierarchy

- `corridor_depth_zones` separates the main corridor and end wall along `z`.
- `corridor_vertical_layers` separates floor, usable wall area, and ceiling.
- `usable_width_layout` separates left wall, passage, and right wall.
- `left_wall_layout` and `right_wall_layout` retain wall backing beside doors.
- `left_doors` and `right_doors` repeat door proxies along `z`.

Semantic classes are `ceiling`, `corridor`, `door`, `ground`, and `wall`.

## Reproduction

```bash
python -m scene_grammar_kit build-scene-example \
  examples/scene_examples/indoor_corridor/scene_manifest.json \
  --out runs/batch_1_7_demo/indoor_corridor

python -m scene_grammar_kit edit split-weight \
  examples/scene_examples/indoor_corridor/grammar.json \
  --split-id usable_width_layout \
  --child-id corridor_passage --weight 10 \
  --out runs/corridor_wider

python -m scene_grammar_kit render \
  examples/scene_examples/indoor_corridor/grammar.json \
  --output runs/corridor_primary.png --camera isometric \
  --width 1200 --height 800
```

The builder writes canonical source, inspection, execution, GLB, isometric,
top-view, and complete corridor-width edit artifacts.

## Limitations

The corridor is an open-box semantic proxy. Doors are solid panels, no textures
or perspective camera are modeled, and the scene is hand-authored rather than
automatically inferred.
