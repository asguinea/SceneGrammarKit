# Repeated Facade

## Purpose

This secondary grammar-only example shows that SceneGrammarKit repeats can describe
architectural modules rather than only street objects.

## Grammar hierarchy

- `facade_vertical_bands` separates lower/base, window, and parapet bands.
- `lower_base_layout` places a central entrance between facade regions.
- `window_band_layout` surrounds `repeated_windows` with wall piers.
- `repeated_windows` repeats `window_module` along `x`.

Semantic classes are `door`, `facade`, `wall`, and `window`.

## Reproduction

```bash
python -m scene_grammar_kit build-scene-example \
  examples/scene_examples/repeated_facade/scene_manifest.json \
  --out runs/batch_1_7_demo/repeated_facade

python -m scene_grammar_kit edit repeat-count \
  examples/scene_examples/repeated_facade/grammar.json \
  --repeat-id repeated_windows --count 8 \
  --out runs/facade_more_windows

python -m scene_grammar_kit render \
  examples/scene_examples/repeated_facade/grammar.json \
  --output runs/facade_front.png --camera front \
  --width 1200 --height 800
```

The builder writes canonical source files, inspection text, original execution
and GLB artifacts, front and isometric views, and the complete window-count edit
artifact set.

## Limitations

Windows and entrance elements are solid cuboid proxies without glazing, frames,
or textures. This is semantic proxy geometry, not photorealistic reconstruction
or automatically inferred architecture.
