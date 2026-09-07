# SceneGrammarKit annotation-assisted construction bundle

This bundle is an annotation-assisted proxy 3D scene construction. Semantic regions, object instances, hierarchy, depth zones, and repeat membership were supplied; SceneGrammarKit deterministically derived proxy bounds, split structure, repeat compression, execution geometry, and semantic previews.

## Directories

- `input/`: copied source evidence and canonical supplied documents.
- `review/`: annotation overlay and supplied-evidence summaries.
- `lifting/`: coarse normalized proxy observations.
- `split_only/`: Batch 2.4 grammar and generated artifacts.
- `repeat/`: Batch 2.5 repeat-compressed grammar and artifacts.
- `primary/`: deterministic selected grammar and matching artifacts.
- `edit/`: before/after procedural edit evidence when available.

Inspect grammars with `python -m scene_grammar_kit inspect <grammar.json>`. Open `scene.glb` in a GLB-compatible viewer. Compare `split_only/` against `repeat/` to inspect supplied repeat compression.

The edit/ directory demonstrates a user-requested procedural variation; it is not additional observed reconstruction evidence.

## Reproduction

Run `python -m scene_grammar_kit construct-assisted-scene input/annotation.json --config input/construction_config.json --out reproduced_bundle --width 1200 --height 800 --camera isometric`.

## Limitations

This is coarse normalized proxy geometry, not automatic semantic segmentation, metric depth, camera calibration, hidden-object recovery, physical measurement, or photorealistic reconstruction.
