# Urban Street

## Purpose

This is the primary overview scene. It shows foreground, midground, and
background depth zones; a horizontal road/sidewalk split; vertical road layers;
repeated parked cars and lamp posts; and a background facade.

## Grammar hierarchy

- `scene_depth_zones` splits foreground, midground, and background along `z`.
- `midground_horizontal_layout` splits left sidewalk, road, and right sidewalk.
- `road_vertical_layers` limits the road surface and object layer along `y`.
- `car_object_layer` separates lamp posts and parked cars.
- `background_facade_bands` creates base, facade, and parapet layers.

Repeat nodes are `street_lamps` and `parked_cars`. Semantic classes are `air`,
`building`, `car`, `facade`, `foreground`, `lamp_post`, `road`, `sidewalk`, and
`wall`.

## Reproduction

```bash
python -m scene_grammar_kit build-scene-example \
  examples/scene_examples/urban_street/scene_manifest.json \
  --out runs/batch_1_7_demo/urban_street
```

Equivalent canonical edit commands:

```bash
python -m scene_grammar_kit edit split-weight \
  examples/scene_examples/urban_street/grammar.json \
  --split-id midground_horizontal_layout \
  --child-id road_vertical_layers --weight 10 \
  --out runs/urban_road_wider

python -m scene_grammar_kit edit repeat-count \
  examples/scene_examples/urban_street/grammar.json \
  --repeat-id parked_cars --count 7 \
  --out runs/urban_more_cars
```

Render the original primary or structural top view:

```bash
python -m scene_grammar_kit render \
  examples/scene_examples/urban_street/grammar.json \
  --output runs/urban_primary.png --camera isometric \
  --width 1200 --height 800

python -m scene_grammar_kit render \
  examples/scene_examples/urban_street/grammar.json \
  --output runs/urban_top.png --camera top \
  --width 1200 --height 800
```

The builder writes canonical source files, grammar-tree text, primitive JSON,
execution reports, GLB and semantic index files, original views, and complete
before/after artifacts for both edits.

## Limitations

Cars, lamp posts, sidewalks, and facade elements are coarse axis-aligned
semantic proxies. This is not a photorealistic reconstruction, and the grammar
is hand-authored rather than automatically inferred.
