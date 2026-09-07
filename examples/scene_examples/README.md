# Canonical Scene Examples

These three small, hand-authored grammar examples demonstrate SceneGrammarKit's
schema-v0.1 split, repeat, terminal, execution, rendering, and structural-edit
policies:

- `urban_street/`: the primary overview with road-width and car-count edits;
- `repeated_facade/`: a front-facing architectural repeat example;
- `indoor_corridor/`: a depth-oriented passage with repeated door proxies.

Each directory contains a tracked human-readable grammar, a strict
manifest-policy-v0.1 source manifest, and reproduction notes. Build artifacts
belong under the ignored `runs/` directory:

```bash
python -m scene_grammar_kit build-scene-example \
  examples/scene_examples/urban_street/scene_manifest.json \
  --out runs/scene_examples/urban_street
```

These scenes are deterministic semantic proxy layouts, not photorealistic
reconstructions or evidence of automatic grammar induction.
